# Contributing to BoxCutter

Thanks for your interest in contributing. These tools are built by DJs for DJs — practical, safe, and focused on real library management problems.

## Dev setup

```bash
git clone https://github.com/YOUR_USERNAME/BoxCutter
cd BoxCutter
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

You'll also need a Rekordbox 7 installation and a valid `pyrekordbox` decryption key set up. See the [pyrekordbox setup guide](https://dylanljones.github.io/pyrekordbox/tutorial/setup.html).

## Guidelines

- **Always dry-run first** — any script that touches `master.db` must support `--dry-run` and create a backup before writing.
- **No personal paths in code** — all paths must be arguments or auto-detected at runtime.
- **Soft deletes only** — use `rb_local_deleted=1`, never `DELETE FROM`.
- **Keep it scriptable** — the CLI must always work without the GUI.

## Reporting issues

Please include:
- OS and Python version
- Rekordbox version
- The exact command you ran
- Full terminal output (sanitize any personal paths)

## Pull requests

Open an issue first for significant changes. Small fixes and new matching strategies for `rekordbox_relocate.py` are always welcome.

## Local quality gate

Run before every push:

```bash
python tools/check.py            # ruff + invariant tests + pytest unit + bandit baseline (~30s)
python tools/check.py --fast     # ruff + invariant tests only (~5s; same as pre-commit)
python tools/check.py --strict   # adds e2e + installer-spec smoke (release gate)
```

A green local run mirrors CI exactly (modulo platform-specific bugs). Pre-commit hooks run `--fast` automatically once you `pre-commit install`.

## Release gate (Step 0 — before tagging v*)

Every release tag must be preceded by a green run of:

```bash
python tools/release_preflight.py
```

(equivalent to `python tools/check.py --strict`). The same check runs as the **Release Gate** GitHub workflow on tag pushes. Do not tag if the gate is red — the v1.1 hardening sweep added the gate specifically to prevent silent regressions on release.

If the gate fails:
1. Fix the failure on a feature branch.
2. Open a PR. Get full CI green.
3. Merge to `main`.
4. Re-run the gate against `main`.
5. Only tag once it exits 0.

## Anti-drift invariants

`tests/test_invariants_routes.py` and `tests/test_invariants_static.py` codify contracts established by the v1.1 audit (CSRF coverage, DB-write inventory, constant-time PIN compare, `_DB_ID_LOCK` discipline, etc.). They run on every PR via the existing CI matrix.

If you add a state-mutating route, the invariant tests will tell you if you forgot the CSRF gate or the rekordbox-running guard. If you add an INSERT-with-MAX(ID)+1 pattern, the static test will tell you if you forgot to wrap it in `_DB_ID_LOCK`. **Don't suppress these tests** — fix the underlying issue.

If you genuinely need an exemption (rare), add an entry to the relevant exemption set with a justification comment. The exemption itself goes through code review.
