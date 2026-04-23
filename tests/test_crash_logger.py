"""Tests for crash_logger.py"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from crash_logger import APP_VERSION, write_crash_log


@pytest.fixture()
def tmp_log_dir(tmp_path, monkeypatch):
    """Redirect LOG_DIR to a temp directory for each test."""
    import crash_logger

    monkeypatch.setattr(crash_logger, "LOG_DIR", tmp_path / "logs")
    return tmp_path / "logs"


def test_write_crash_log_creates_file(tmp_log_dir):
    path = write_crash_log("startup", "some traceback")
    assert path is not None
    assert path.exists()


def test_write_crash_log_returns_path_object(tmp_log_dir):
    path = write_crash_log("startup", "tb")
    assert isinstance(path, Path)


def test_write_crash_log_filename_format(tmp_log_dir):
    path = write_crash_log("startup", "tb")
    assert path.name.startswith("crash_")
    assert path.suffix == ".log"


def test_write_crash_log_contains_version(tmp_log_dir):
    path = write_crash_log("startup", "tb")
    assert APP_VERSION in path.read_text(encoding="utf-8")


def test_write_crash_log_contains_surface(tmp_log_dir):
    path = write_crash_log("route", "tb")
    assert "route" in path.read_text(encoding="utf-8")


def test_write_crash_log_contains_body(tmp_log_dir):
    path = write_crash_log("startup", "ZeroDivisionError: division by zero")
    assert "ZeroDivisionError: division by zero" in path.read_text(encoding="utf-8")


def test_write_crash_log_contains_context(tmp_log_dir):
    path = write_crash_log("script", "tb", context={"Script:   ": "rekordbox_relocate.py"})
    content = path.read_text(encoding="utf-8")
    assert "rekordbox_relocate.py" in content


def test_write_crash_log_creates_dir_if_missing(tmp_path, monkeypatch):
    import crash_logger

    new_dir = tmp_path / "nested" / "logs"
    assert not new_dir.exists()
    monkeypatch.setattr(crash_logger, "LOG_DIR", new_dir)
    path = write_crash_log("startup", "tb")
    assert path is not None
    assert new_dir.exists()


def test_write_crash_log_returns_none_on_bad_dir():
    import crash_logger

    with patch.object(
        crash_logger.LOG_DIR.__class__, "mkdir", side_effect=PermissionError("denied")
    ):
        result = write_crash_log("startup", "tb")
    assert result is None


def test_write_crash_log_mode_frozen(tmp_log_dir, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    path = write_crash_log("startup", "tb")
    assert "frozen" in path.read_text(encoding="utf-8")


def test_write_crash_log_mode_dev(tmp_log_dir):
    # sys.frozen is not set in normal test runs
    if hasattr(sys, "frozen"):
        pytest.skip("frozen attribute set — not a dev environment")
    path = write_crash_log("startup", "tb")
    assert "dev" in path.read_text(encoding="utf-8")
