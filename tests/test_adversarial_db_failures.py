"""
Adversarial tests for DB-failure handling on /api/stats and /api/playlists.

These are the most likely user-hit failure modes:
- db_path not configured at all
- db_path points to a file that doesn't exist
- db_path points to a 0-byte file
- db_path points to a file that isn't SQLite at all (e.g. user picked an .mp3)
- db_path points to a SQLite file that isn't Rekordbox's schema
- db_path points to a locked file (Rekordbox is open)

The promise: every failure mode returns a JSON error with a useful status code,
never a 500 traceback in the user's face.
"""

from unittest.mock import MagicMock, patch

import pytest

import app as flask_app


@pytest.fixture
def client(tmp_path):
    flask_app.app.config["TESTING"] = True
    cfg = {
        "db_path": str(tmp_path / "master.db"),
        "music_root": "",
        "flac_root": "",
        "mp3_root": "",
        "delete_dir": "",
        "watch_dir": "",
    }
    with (
        patch.object(flask_app, "load_config", return_value=cfg),
        flask_app.app.test_client() as c,
    ):
        yield c


@pytest.fixture
def client_no_db(tmp_path):
    flask_app.app.config["TESTING"] = True
    cfg = {
        "db_path": "",
        "music_root": "",
        "flac_root": "",
        "mp3_root": "",
        "delete_dir": "",
        "watch_dir": "",
    }
    with (
        patch.object(flask_app, "load_config", return_value=cfg),
        flask_app.app.test_client() as c,
    ):
        yield c


# ---------------------------------------------------------------------------
# /api/stats
# ---------------------------------------------------------------------------


def test_stats_returns_400_when_db_path_not_configured(client_no_db):
    """Most common user error: hit Stats before going through Setup."""
    resp = client_no_db.get("/api/stats")
    assert resp.status_code == 400
    body = resp.get_json()
    assert "Setup" in body["error"]


def test_stats_returns_500_with_useful_error_when_db_file_missing(client):
    """A configured-but-missing db_path: subprocess fails, route returns the stderr."""
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stdout = ""
    fake_result.stderr = "DB path not found: /fake/master.db"
    with patch("app.subprocess.run", return_value=fake_result):
        resp = client.get("/api/stats")
    assert resp.status_code == 500
    body = resp.get_json()
    assert "DB path not found" in body["error"]


def test_stats_returns_500_with_useful_error_on_corrupt_db(client):
    """User picked a non-SQLite file (e.g. an .mp3) as db_path."""
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stdout = ""
    fake_result.stderr = "file is not a database"
    with patch("app.subprocess.run", return_value=fake_result):
        resp = client.get("/api/stats")
    assert resp.status_code == 500
    body = resp.get_json()
    assert "not a database" in body["error"]


def test_stats_returns_useful_error_when_subprocess_times_out(client):
    """Locked / huge / hung DB: subprocess hits the 15s timeout."""
    import subprocess as sp  # noqa: PLC0415

    with patch(
        "app.subprocess.run",
        side_effect=sp.TimeoutExpired(cmd=["x"], timeout=15),
    ):
        resp = client.get("/api/stats")
    assert resp.status_code == 500
    body = resp.get_json()
    assert "Timed out" in body["error"]


def test_stats_returns_useful_error_when_subprocess_raises(client):
    """Worst case: Popen itself raises (e.g. python interpreter missing)."""
    with patch("app.subprocess.run", side_effect=OSError("python not found")):
        resp = client.get("/api/stats")
    assert resp.status_code == 500
    body = resp.get_json()
    assert "python not found" in body["error"]


def test_stats_returns_500_with_unknown_error_message_when_stderr_empty(client):
    """Subprocess fails silently — route must still produce a useful error string."""
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stdout = ""
    fake_result.stderr = ""
    with patch("app.subprocess.run", return_value=fake_result):
        resp = client.get("/api/stats")
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"]  # non-empty string, not None / not missing


# ---------------------------------------------------------------------------
# /api/playlists  (same surface — duplicate the high-value tests)
# ---------------------------------------------------------------------------


def test_playlists_returns_400_when_db_path_not_configured(client_no_db):
    resp = client_no_db.get("/api/playlists")
    assert resp.status_code == 400
    assert "Setup" in resp.get_json()["error"]


def test_playlists_returns_500_with_useful_error_on_corrupt_db(client):
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stdout = ""
    fake_result.stderr = "file is encrypted or is not a database"
    with patch("app.subprocess.run", return_value=fake_result):
        resp = client.get("/api/playlists")
    assert resp.status_code == 500
    body = resp.get_json()
    assert "encrypted" in body["error"] or "not a database" in body["error"]


def test_playlists_handles_subprocess_timeout(client):
    import subprocess as sp  # noqa: PLC0415

    with patch(
        "app.subprocess.run",
        side_effect=sp.TimeoutExpired(cmd=["x"], timeout=15),
    ):
        resp = client.get("/api/playlists")
    assert resp.status_code == 500
    assert "Timed out" in resp.get_json()["error"]
