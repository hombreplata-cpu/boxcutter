"""
Anti-drift invariants — source-level static checks against app.py.

These tests grep app.py for patterns that prior audit findings established
as either required (must be present) or forbidden (must not appear). They
catch the kind of regression that auto-discovery from url_map can't see —
e.g. someone swapping `hmac.compare_digest` back to `==` for the PIN check.

Each assertion includes the roadmap ID it's protecting so the rationale
stays attached to the test as the codebase evolves.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_SRC = (REPO_ROOT / "app.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# S-01 — _secret_key must NOT be in the writable config allowlist
# ---------------------------------------------------------------------------


def test_secret_key_not_in_allowed_config_keys():
    """The /api/config endpoint must reject _secret_key. If a future change
    accidentally adds it to ALLOWED_CONFIG_KEYS — or removes the allowlist
    entirely — this test fires."""
    # Find the ALLOWED_CONFIG_KEYS literal by capturing the assignment.
    match = re.search(
        r"ALLOWED_CONFIG_KEYS\s*=\s*frozenset\(([^)]+)\)",
        APP_SRC,
        re.DOTALL,
    )
    assert match, (
        "ALLOWED_CONFIG_KEYS literal not found in app.py — has the allowlist been "
        "removed? Without it /api/config silently accepts any key (S-01 regression)."
    )
    body = match.group(1)
    assert "_secret_key" not in body, (
        "_secret_key is in the ALLOWED_CONFIG_KEYS literal. The session signing key "
        "must be writable only via SECRET_FILE, never via /api/config (S-01/S-07)."
    )
    # Also assert the allowlist is sourced from DEFAULT_CONFIG.keys(), not a
    # hand-maintained list that can drift out of sync.
    assert "DEFAULT_CONFIG" in body, (
        "ALLOWED_CONFIG_KEYS should be derived from DEFAULT_CONFIG.keys() so the "
        "allowlist cannot drift from the schema."
    )


# ---------------------------------------------------------------------------
# Subprocess hygiene — no shell=True
# ---------------------------------------------------------------------------


def test_no_subprocess_shell_true_in_app():
    """Shell injection is one of OWASP's top concerns. Every subprocess call
    in app.py must use list form (default shell=False). This test fires
    if anyone adds shell=True."""
    # Match shell=True with optional whitespace.
    pattern = re.compile(r"shell\s*=\s*True", re.IGNORECASE)
    matches = pattern.findall(APP_SRC)
    assert not matches, (
        f"Found {len(matches)} subprocess call(s) using shell=True in app.py. "
        "Always use list form for subprocess.* calls — shell=True turns user "
        "input into shell metacharacters."
    )


# ---------------------------------------------------------------------------
# S-04 — listen_login uses constant-time PIN compare
# ---------------------------------------------------------------------------


def test_listen_login_uses_compare_digest():
    """The PIN check must use hmac.compare_digest (constant-time) to defeat
    timing side-channels. If anyone reverts to == comparison this fires."""
    # Locate the listen_login function body by looking for its def line and
    # the next def line.
    body = _function_body(APP_SRC, "def listen_login")
    assert "hmac.compare_digest" in body, (
        "listen_login no longer uses hmac.compare_digest for the PIN check. "
        "Constant-time compare is required (S-04). String == invites timing "
        "side-channels and brute-force feedback."
    )


# ---------------------------------------------------------------------------
# S-05 — /shutdown is gated by sys.frozen
# ---------------------------------------------------------------------------


def test_shutdown_route_requires_frozen():
    """The /shutdown POST is destructive (kills the server process). It
    must be reachable only from the frozen binary, never from dev mode —
    otherwise tests or dev scripts that POST it kill the user's process."""
    body = _function_body(APP_SRC, "def shutdown")
    assert "sys.frozen" in body or "getattr(sys" in body, (
        "/shutdown route no longer checks sys.frozen — a stray POST from "
        "any client kills the server (S-05 regression)."
    )


# ---------------------------------------------------------------------------
# Tailscale-binding documentation invariants
# ---------------------------------------------------------------------------


def test_zero_zero_zero_zero_binding_has_nosec_documentation():
    """app.run(host="0.0.0.0") is intentional (Tailscale listener) but must
    be explicitly annotated. If the comment vanishes, a future maintainer
    might think it's a bug and try to "fix" it (or worse, miss the
    intentionality entirely)."""
    binding_lines = [line for line in APP_SRC.splitlines() if 'host="0.0.0.0"' in line]
    assert binding_lines, (
        'Could not find the host="0.0.0.0" binding — has it moved? Update '
        "this test to match the new location."
    )
    for line in binding_lines:
        assert "nosec" in line or "noqa" in line, (
            f'host="0.0.0.0" binding lacks nosec/noqa comment: {line.strip()}\n'
            "The comment is what tells future maintainers this is intentional."
        )


# ---------------------------------------------------------------------------
# B-09 — _DB_ID_LOCK protects every read-MAX→INSERT call site
# ---------------------------------------------------------------------------


def test_db_id_generators_held_under_lock():
    """Every place that computes a next-ID via `SELECT MAX(...) ... FROM`
    or by calling `_next_song_*_id()` must be inside a `with _DB_ID_LOCK`
    block. A new caller that forgets the lock re-introduces the
    duplicate-ID race fixed in Phase 5 (B-09).

    Detection strategy: find every line that *originates* a next-ID
    computation, then walk up ~30 source lines looking for the lock.
    """
    # Patterns that introduce a next-ID. Reading-MAX patterns include
    # the literal SQL string we use in app.py.
    originator_patterns = [
        r"SELECT MAX\(CAST\(ID AS INTEGER\)\)",
        r"\b_next_song_mytag_id\s*\(",
        r"\b_next_song_playlist_id\s*\(",
    ]
    failures = []
    for pat in originator_patterns:
        for match in re.finditer(pat, APP_SRC):
            # Skip the def-site of the helper itself.
            line_start = APP_SRC.rfind("\n", 0, match.start()) + 1
            line = APP_SRC[line_start : APP_SRC.find("\n", match.start())]
            if line.lstrip().startswith("def "):
                continue
            # Walk back up to 30 lines looking for context: either
            # `with _DB_ID_LOCK` (caller holds the lock — good) or
            # `def _next_song_` (we're inside a helper whose contract is
            # "caller must hold the lock" — also good, the helper site is
            # validated separately by the originator pattern matching the
            # helper *call*).
            preceding = APP_SRC[: match.start()].splitlines()[-30:]
            window = "\n".join(preceding)
            inside_helper = any(line.lstrip().startswith("def _next_song_") for line in preceding)
            if "_DB_ID_LOCK" not in window and not inside_helper:
                snippet = line.strip()
                failures.append(f"  {pat!r} at: {snippet}")
    assert not failures, (
        "B-09 regression risk — next-ID computation without _DB_ID_LOCK:\n"
        + "\n".join(failures)
        + "\n\nWrap the read-MAX → INSERT block in `with _DB_ID_LOCK:` so "
        "concurrent requests can't compute the same next-ID."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _function_body(src: str, def_signature: str) -> str:
    """Return the source of the function whose def line contains
    def_signature, up to the next top-level def/class or end of file."""
    lines = src.splitlines()
    start = None
    for i, line in enumerate(lines):
        if def_signature in line:
            start = i
            break
    assert start is not None, f"Could not find {def_signature} in source"
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("def ") or line.startswith("class "):
            break
        body.append(line)
    return "\n".join(body)


def _functions_containing(src: str, keyword: str) -> dict:
    """Return {function_name: body} for every top-level function whose body
    contains *keyword*."""
    result = {}
    lines = src.splitlines()
    current_name = None
    current_body: list = []
    for line in lines:
        stripped = line.lstrip()
        if line.startswith("def ") or stripped.startswith("@app.route"):
            if current_name is not None and keyword in "\n".join(current_body):
                result[current_name] = "\n".join(current_body)
            current_body = [line]
            if line.startswith("def "):
                current_name = line.split("(")[0].replace("def ", "")
        else:
            current_body.append(line)
    if current_name is not None and keyword in "\n".join(current_body):
        result[current_name] = "\n".join(current_body)
    return result
