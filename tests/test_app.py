"""
Tests for app.py Flask routes.

Covers:
- /api/run/relocate passes --target-ext and --source-ext to the subprocess
- /api/run/relocate defaults --target-ext to flac when not supplied
- /api/run/relocate omits --source-ext when blank
- /api/run/relocate returns 400 when target_root is missing
- /api/run/<unknown> returns 400
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as flask_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    flask_app.app.config["TESTING"] = True
    # Patch load_config so tests don't need real config files.
    # db_path must be non-empty: the api_run guard now rejects DB-tool runs without it.
    with patch.object(
        flask_app, "load_config", return_value={"db_path": "/fake/master.db"}
    ), flask_app.app.test_client() as c:
        yield c


def _captured_cmd(mock_popen):
    """Extract the command list passed to the most recent Popen call."""
    assert mock_popen.called, "Popen was not called"
    return mock_popen.call_args[0][0]


# ---------------------------------------------------------------------------
# target_ext and source_ext forwarding
# ---------------------------------------------------------------------------


def _make_proc_mock():
    """Create a mock Popen process whose stdout ends immediately."""
    mock_proc = MagicMock()
    # iter(proc.stdout.readline, "") terminates when readline() returns "".
    mock_proc.stdout.readline.return_value = ""
    mock_proc.stdout.close = MagicMock()
    mock_proc.wait = MagicMock(return_value=0)
    mock_proc.returncode = 0
    return mock_proc


def _run_sse(client, url, query_string):
    """Issue a GET and consume the full streaming SSE response to trigger Popen."""
    resp = client.get(url, query_string=query_string)
    # Drain the generator so subprocess.Popen is actually invoked.
    _ = resp.get_data()
    return resp


def test_relocate_passes_target_ext(client, tmp_path):
    """--target-ext is forwarded from the request param."""
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = _make_proc_mock()
        _run_sse(
            client,
            "/api/run/relocate",
            {"target_root": str(tmp_path), "target_ext": "wav", "dry_run": "1"},
        )
    cmd = _captured_cmd(mock_popen)
    assert "--target-ext" in cmd
    assert cmd[cmd.index("--target-ext") + 1] == "wav"


def test_relocate_passes_source_ext_when_set(client, tmp_path):
    """--source-ext is forwarded when the request param is non-empty."""
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = _make_proc_mock()
        _run_sse(
            client,
            "/api/run/relocate",
            {
                "target_root": str(tmp_path),
                "target_ext": "flac",
                "source_ext": "mp3",
                "dry_run": "1",
            },
        )
    cmd = _captured_cmd(mock_popen)
    assert "--source-ext" in cmd
    assert cmd[cmd.index("--source-ext") + 1] == "mp3"


def test_relocate_omits_source_ext_when_blank(client, tmp_path):
    """--source-ext is NOT added to the command when the param is empty."""
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = _make_proc_mock()
        _run_sse(
            client,
            "/api/run/relocate",
            {
                "target_root": str(tmp_path),
                "target_ext": "flac",
                "source_ext": "",
                "dry_run": "1",
            },
        )
    cmd = _captured_cmd(mock_popen)
    assert "--source-ext" not in cmd


def test_relocate_defaults_target_ext_to_flac(client, tmp_path):
    """When target_ext is omitted, --target-ext flac is used."""
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = _make_proc_mock()
        _run_sse(client, "/api/run/relocate", {"target_root": str(tmp_path), "dry_run": "1"})
    cmd = _captured_cmd(mock_popen)
    assert "--target-ext" in cmd
    assert cmd[cmd.index("--target-ext") + 1] == "flac"


def test_relocate_prefer_ext_not_in_cmd(client, tmp_path):
    """Old --prefer-ext flag must not appear in the subprocess command."""
    with patch("app.subprocess.Popen") as mock_popen, patch("app.save_history_entry"):
        mock_popen.return_value = _make_proc_mock()
        _run_sse(client, "/api/run/relocate", {"target_root": str(tmp_path), "dry_run": "1"})
    cmd = _captured_cmd(mock_popen)
    assert "--prefer-ext" not in cmd


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_relocate_missing_target_root_returns_400(client):
    """Omitting target_root must return HTTP 400."""
    resp = client.get("/api/run/relocate", query_string={"dry_run": "1"})
    assert resp.status_code == 400


def test_unknown_script_returns_400(client):
    """Requesting an unknown script name returns HTTP 400."""
    resp = client.get("/api/run/not_a_real_script")
    assert resp.status_code == 400
