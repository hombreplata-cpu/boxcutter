"""
Regression tests: scripts must be runnable as subprocesses via sys.executable.

Root cause of the regression these tests guard against:
  In the frozen .exe, sys.executable is BoxCutter.exe, not Python.
  app.py builds cmd = [sys.executable, script.py, ...] for every tool run.
  Without the launcher.py dispatch fix, that launches a second BoxCutter.exe
  which detects port 5000 is taken and calls sys.exit(0) — silent, no output,
  exit code 0, so generate() yields %%DONE%% immediately with no report.

These tests exercise the subprocess invocation path directly. In-process unit
tests that mock pyrekordbox cannot catch this class of regression.
"""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"

_DB_SCRIPTS = [
    "rekordbox_relocate.py",
    "rekordbox_cleanup.py",
    "rekordbox_fix_metadata.py",
    "rekordbox_add_new.py",
]


@pytest.mark.skipif(sys.platform != "win32", reason="DB scripts require SQLCipher — Windows only")
@pytest.mark.parametrize("script", _DB_SCRIPTS)
def test_db_script_runnable_via_subprocess(script):
    """Each DB script must be invokable as a subprocess and produce --help output."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"{script}: exit {result.returncode}\n{result.stderr}"
    assert result.stdout.strip(), f"{script}: no stdout on --help"


def test_strip_comments_runnable_via_subprocess(tmp_path):
    """strip_comment_urls.py must be runnable via sys.executable on any platform."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "strip_comment_urls.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"exit {result.returncode}\n{result.stderr}"


def test_strip_comments_emits_report_sentinels(tmp_path):
    """strip_comment_urls.py must emit %%REPORT_START%% / %%REPORT_END%% when run as a subprocess.

    Regression: if the script exits before reaching its report block (e.g. because
    sys.executable dispatches to the wrong binary), the SSE stream gets %%DONE%%
    immediately with no report card rendered in the UI.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "strip_comment_urls.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"exit {result.returncode}\n{result.stderr}"
    assert "%%REPORT_START%%" in result.stdout, "Missing %%REPORT_START%% sentinel"
    assert "%%REPORT_END%%" in result.stdout, "Missing %%REPORT_END%% sentinel"
