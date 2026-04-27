"""
Anti-drift invariants — auto-discover routes from app.url_map.

If you add a new state-mutating route, you do NOT need to update this file.
The tests below iterate every route Flask knows about and assert each one
satisfies the documented contracts. A new route that violates a contract
fails CI, forcing the change to be deliberate.

If you genuinely need an exemption (rare), add it to the EXEMPTIONS set
below with a justification comment. The exemption itself goes through code
review.

Contracts asserted:
  1. Every POST/PUT/PATCH/DELETE route returns 403 without the CSRF token.
  2. Every side-effecting GET prefix (/api/run/*, /api/download_update)
     returns 403 without the token.
  3. Every mutating route under /api/tracks/* and /api/mytags/* is in a
     pinned inventory list, forcing new ones to be added explicitly to
     the rekordbox-running guard matrix in
     test_adversarial_rekordbox_race.py.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as flask_app  # noqa: E402

# Routes that legitimately do NOT require the CSRF token. Empty by design —
# defensive default. Every entry MUST carry a justification comment.
CSRF_EXEMPTIONS: set[tuple[str, str]] = set()

# Side-effecting GET prefixes that DO require the token even though they're
# read-shaped (SSE streams that fork subprocesses or download installers).
# When you add a new such prefix, append it here so the auto-discovery
# meta-test (below) can find it.
SIDE_EFFECTING_GET_PREFIXES = ("/api/run/", "/api/download_update")

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _materialise_path(rule) -> str | None:
    """Substitute Flask URL converters with valid sample values.

    Returns None if the rule contains a converter we don't recognise —
    those are skipped from the auto-discovery (and a maintainer should
    add them to this function rather than letting them go untested).
    """
    path = rule.rule
    for arg in rule.arguments:
        for tmpl, value in [
            (f"<int:{arg}>", "1"),
            (f"<float:{arg}>", "1.0"),
            (f"<path:{arg}>", "x"),
            (f"<string:{arg}>", "x"),
            (f"<{arg}>", "x"),
        ]:
            path = path.replace(tmpl, value)
    if "<" in path:
        return None
    return path


def _all_mutating_endpoints():
    for rule in flask_app.app.url_map.iter_rules():
        path = _materialise_path(rule)
        if path is None:
            continue
        methods = rule.methods or set()
        for method in methods & MUTATING_METHODS:
            yield path, method


def _all_side_effecting_get_endpoints():
    for rule in flask_app.app.url_map.iter_rules():
        path = _materialise_path(rule)
        if path is None:
            continue
        methods = rule.methods or set()
        if "GET" not in methods:
            continue
        if any(path.startswith(p) for p in SIDE_EFFECTING_GET_PREFIXES):
            yield path, "GET"


# ---------------------------------------------------------------------------
# Contract 1: every state-mutating endpoint requires the CSRF token
# ---------------------------------------------------------------------------


@pytest.fixture
def gated_client(tmp_path):
    """Client with CSRF gate enforced — for testing the gate itself."""
    flask_app.app.config["TESTING"] = True
    flask_app.app.config["BOXCUTTER_TEST_ENFORCE_CSRF"] = True
    cfg_file = tmp_path / "config.json"
    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        flask_app.app.test_client() as c,
    ):
        yield c
    flask_app.app.config["BOXCUTTER_TEST_ENFORCE_CSRF"] = False


def test_every_mutating_route_rejects_missing_token(gated_client):
    """Drift guard: any new POST/PUT/PATCH/DELETE route MUST be behind the
    CSRF gate. If you add a new route and this test fails, either rely on
    the existing before_request hook (the default — no opt-in needed) or
    add a justified entry to CSRF_EXEMPTIONS.
    """
    failures = []
    for path, method in _all_mutating_endpoints():
        if (path, method) in CSRF_EXEMPTIONS:
            continue
        try:
            resp = gated_client.open(path, method=method)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{method} {path}: raised before gate fired: {exc}")
            continue
        if resp.status_code != 403:
            failures.append(
                f"{method} {path}: returned {resp.status_code}, not 403. "
                "CSRF gate is not protecting this route."
            )
    assert not failures, "CSRF drift detected:\n  " + "\n  ".join(failures)


def test_every_side_effecting_get_rejects_missing_token(gated_client):
    """Side-effecting GETs (SSE: run scripts, download installers) must
    also be gated. If you add another such prefix, update
    SIDE_EFFECTING_GET_PREFIXES at the top of this file.
    """
    failures = []
    for path, method in _all_side_effecting_get_endpoints():
        try:
            resp = gated_client.open(path, method=method)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{method} {path}: raised before gate fired: {exc}")
            continue
        if resp.status_code != 403:
            failures.append(f"{method} {path}: returned {resp.status_code}, not 403.")
    assert not failures, "Side-effecting GET drift detected:\n  " + "\n  ".join(failures)


# ---------------------------------------------------------------------------
# Contract 2: every "DB write" route is pinned in the rekordbox-running
# guard inventory (test_adversarial_rekordbox_race.WRITE_ROUTES).
# ---------------------------------------------------------------------------

# Inventory of paths under /api/tracks/* and /api/mytags/* that have at
# least one mutating method. New mutating routes in those namespaces MUST
# be added here AND to WRITE_ROUTES in test_adversarial_rekordbox_race.py
# so they're guaranteed to be covered by the rekordbox-running guard test.
KNOWN_DB_WRITE_PATHS = {
    "/api/tracks/<content_id>/rating",
    "/api/tracks/<content_id>/cues",
    "/api/tracks/<content_id>/mytags",
    "/api/tracks/<content_id>/mytags/<assignment_id>",
    "/api/tracks/<content_id>/playlists/<playlist_id>",
    "/api/mytags/backup",
}


def test_db_write_route_inventory_is_complete():
    """Drift guard: any new mutating route under /api/tracks/* or
    /api/mytags/* must be added to KNOWN_DB_WRITE_PATHS so it appears
    in WRITE_ROUTES (in test_adversarial_rekordbox_race.py) — that's
    how we guarantee every write is gated by rekordbox_is_running().
    """
    discovered = set()
    for rule in flask_app.app.url_map.iter_rules():
        if not rule.rule.startswith(("/api/tracks/", "/api/mytags/")):
            continue
        methods = rule.methods or set()
        if not (methods & MUTATING_METHODS):
            continue
        discovered.add(rule.rule)

    new_routes = discovered - KNOWN_DB_WRITE_PATHS
    assert not new_routes, (
        f"New mutating /api/tracks/ or /api/mytags/ route(s) not yet pinned: "
        f"{sorted(new_routes)}.\n"
        "Add to KNOWN_DB_WRITE_PATHS in tests/test_invariants_routes.py "
        "AND to WRITE_ROUTES in tests/test_adversarial_rekordbox_race.py "
        "to ensure rekordbox_is_running guard coverage."
    )

    # Also flag stale entries: paths in the inventory that no longer exist
    # in url_map. This catches deletions/renames that left the inventory out of date.
    stale = KNOWN_DB_WRITE_PATHS - discovered
    assert not stale, (
        f"Inventory entries no longer present in url_map: {sorted(stale)}.\n"
        "Remove them from KNOWN_DB_WRITE_PATHS (and WRITE_ROUTES if applicable)."
    )
