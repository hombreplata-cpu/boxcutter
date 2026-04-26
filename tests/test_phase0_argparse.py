"""
Phase 0 / R-11 — Subprocess wrapper scripts now use argparse.

Confirms unknown flags exit with the standard argparse exit code (2) instead
of being silently ignored (the old hand-rolled `if len(sys.argv) == 3` pattern
ignored everything except a single `--db-path VALUE` pair).

Also confirms the help flag works.
"""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = [
    "scripts/get_stats.py",
    "scripts/get_playlists.py",
    "scripts/get_listen_tree.py",
]

REPO_ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize("script", SCRIPTS)
def test_unknown_flag_exits_with_argparse_error(script):
    """Argparse returns exit code 2 on unknown flag — proves we're using argparse."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / script), "--this-flag-does-not-exist"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2, (
        f"{script} did not return argparse's exit code 2 for unknown flag — "
        f"got {result.returncode}. Stderr: {result.stderr!r}"
    )
    assert "unrecognized arguments" in result.stderr or "error" in result.stderr.lower()


@pytest.mark.parametrize("script", SCRIPTS)
def test_help_flag_works(script):
    """--help must exit 0 and print usage info."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / script), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "--db-path" in result.stdout
