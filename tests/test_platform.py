"""
Unit tests for platform-specific functions in app.py.

Each function is tested for both Windows and Darwin (macOS) branches by
patching platform.system() and the relevant subprocess calls.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import app  # noqa: E402

# ---------------------------------------------------------------------------
# rekordbox_is_running
# ---------------------------------------------------------------------------


def test_rekordbox_running_windows_true():
    with (
        patch("app.platform.system", return_value="Windows"),
        patch("app.subprocess.check_output", return_value="rekordbox.exe INFO"),
    ):
        assert app.rekordbox_is_running() is True


def test_rekordbox_running_windows_false():
    with (
        patch("app.platform.system", return_value="Windows"),
        patch("app.subprocess.check_output", return_value="No tasks running"),
    ):
        assert app.rekordbox_is_running() is False


def test_rekordbox_running_mac_true():
    mock_result = MagicMock()
    mock_result.returncode = 0
    with (
        patch("app.platform.system", return_value="Darwin"),
        patch("app.subprocess.run", return_value=mock_result),
    ):
        assert app.rekordbox_is_running() is True


def test_rekordbox_running_mac_false():
    mock_result = MagicMock()
    mock_result.returncode = 1
    with (
        patch("app.platform.system", return_value="Darwin"),
        patch("app.subprocess.run", return_value=mock_result),
    ):
        assert app.rekordbox_is_running() is False


def test_rekordbox_running_returns_false_on_exception():
    with (
        patch("app.platform.system", return_value="Windows"),
        patch("app.subprocess.check_output", side_effect=Exception("no tasklist")),
    ):
        assert app.rekordbox_is_running() is False


# ---------------------------------------------------------------------------
# get_rekordbox_backup_dir
# ---------------------------------------------------------------------------


def test_backup_dir_windows_uses_appdata():
    with (
        patch("app.platform.system", return_value="Windows"),
        patch.dict("os.environ", {"APPDATA": "C:\\Users\\dj\\AppData\\Roaming"}),
    ):
        result = app.get_rekordbox_backup_dir()
    assert "Pioneer" in str(result)
    assert "rekordbox" in str(result)


def test_backup_dir_mac_uses_library():
    with patch("app.platform.system", return_value="Darwin"):
        result = app.get_rekordbox_backup_dir()
    assert "Library" in str(result)
    assert "Pioneer" in str(result)
    assert "rekordbox" in str(result)


def test_backup_dir_db_path_overrides_platform():
    """When db_path is provided, the parent dir is used regardless of OS."""
    with patch("app.platform.system", return_value="Windows"):
        result = app.get_rekordbox_backup_dir(db_path="/custom/path/master.db")
    assert str(result) == str(Path("/custom/path"))


# ---------------------------------------------------------------------------
# _port_pid
# ---------------------------------------------------------------------------


def test_port_pid_windows_returns_pid():
    mock_result = MagicMock()
    mock_result.stdout = "  TCP  0.0.0.0:5000  0.0.0.0:0  LISTENING  1234\n"
    with (
        patch("app.platform.system", return_value="Windows"),
        patch("app.subprocess.run", return_value=mock_result),
    ):
        pid = app._port_pid(5000)
    assert pid == 1234


def test_port_pid_windows_returns_none_when_not_listening():
    mock_result = MagicMock()
    mock_result.stdout = "Active Connections\n"
    with (
        patch("app.platform.system", return_value="Windows"),
        patch("app.subprocess.run", return_value=mock_result),
    ):
        pid = app._port_pid(5000)
    assert pid is None


def test_port_pid_mac_returns_pid():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "5678\n"
    with (
        patch("app.platform.system", return_value="Darwin"),
        patch("app.subprocess.run", return_value=mock_result),
    ):
        pid = app._port_pid(5000)
    assert pid == 5678


def test_port_pid_mac_returns_none_when_free():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    with (
        patch("app.platform.system", return_value="Darwin"),
        patch("app.subprocess.run", return_value=mock_result),
    ):
        pid = app._port_pid(5000)
    assert pid is None


# ---------------------------------------------------------------------------
# _is_our_app
# ---------------------------------------------------------------------------


def test_is_our_app_windows_true():
    """Match only on the actual app.py absolute path or BoxCutter binary (B-11)."""
    from pathlib import Path  # noqa: PLC0415

    our_path = str(Path(app.__file__).resolve())
    mock_result = MagicMock()
    mock_result.stdout = f"python {our_path}\n"
    with (
        patch("app.platform.system", return_value="Windows"),
        patch("app.subprocess.run", return_value=mock_result),
    ):
        assert app._is_our_app(1234) is True


def test_is_our_app_windows_false():
    mock_result = MagicMock()
    mock_result.stdout = "other_process.exe\n"
    with (
        patch("app.platform.system", return_value="Windows"),
        patch("app.subprocess.run", return_value=mock_result),
    ):
        assert app._is_our_app(1234) is False


def test_is_our_app_windows_rejects_unrelated_app_py():
    """B-11: a Python project that happens to have an app.py must not match."""
    mock_result = MagicMock()
    mock_result.stdout = r"python C:\Users\Other\Project\app.py" + "\n"
    with (
        patch("app.platform.system", return_value="Windows"),
        patch("app.subprocess.run", return_value=mock_result),
    ):
        assert app._is_our_app(1234) is False


def test_is_our_app_mac_true():
    from pathlib import Path  # noqa: PLC0415

    our_path = str(Path(app.__file__).resolve())
    mock_result = MagicMock()
    mock_result.stdout = f"/usr/bin/python {our_path}\n"
    with (
        patch("app.platform.system", return_value="Darwin"),
        patch("app.subprocess.run", return_value=mock_result),
    ):
        assert app._is_our_app(5678) is True


def test_is_our_app_mac_false():
    mock_result = MagicMock()
    mock_result.stdout = "nginx\n"
    with (
        patch("app.platform.system", return_value="Darwin"),
        patch("app.subprocess.run", return_value=mock_result),
    ):
        assert app._is_our_app(5678) is False


# ---------------------------------------------------------------------------
# resolve_server_port — kill branch
# ---------------------------------------------------------------------------


def test_resolve_server_port_uses_taskkill_on_windows():
    with (
        patch("app._port_pid", return_value=9999),
        patch("app._is_our_app", return_value=True),
        patch("app.platform.system", return_value="Windows"),
        patch("app.subprocess.run") as mock_run,
    ):
        port = app.resolve_server_port(preferred=5000)
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "taskkill" in cmd
    assert port == 5000


def test_resolve_server_port_uses_kill_on_mac():
    with (
        patch("app._port_pid", return_value=9999),
        patch("app._is_our_app", return_value=True),
        patch("app.platform.system", return_value="Darwin"),
        patch("app.subprocess.run") as mock_run,
    ):
        port = app.resolve_server_port(preferred=5000)
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "kill" in cmd
    assert "-9" in cmd
    assert port == 5000


# ---------------------------------------------------------------------------
# resolve_server_port — BOXCUTTER_PORT env override (R-10)
# ---------------------------------------------------------------------------


def test_resolve_server_port_honors_valid_env(monkeypatch):
    monkeypatch.setenv("BOXCUTTER_PORT", "5500")
    assert app.resolve_server_port(preferred=5000) == 5500


def test_resolve_server_port_falls_back_on_invalid_env(monkeypatch, capsys):
    """A non-numeric BOXCUTTER_PORT must not crash — fall back to default discovery."""
    monkeypatch.setenv("BOXCUTTER_PORT", "garbage")
    with (
        patch("app._port_pid", return_value=None),
    ):
        port = app.resolve_server_port(preferred=5000)
    assert port == 5000
    captured = capsys.readouterr()
    assert "BOXCUTTER_PORT" in captured.out
