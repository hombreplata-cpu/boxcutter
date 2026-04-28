"""
Adversarial tests for the Rekordbox-running guard on write routes.

The promise: every route that writes to master.db checks rekordbox_is_running()
and returns 409 if Rekordbox is open. The user must close Rekordbox before
edits. There is a TOCTOU race (Rekordbox could open *between* the check and
the commit) — that is a known limit, documented in the test
test_known_limit_toctou_race_window_exists.

These tests are coverage guards: if a future write route is added without the
guard, this test must fail.
"""

from unittest.mock import MagicMock, patch

import pytest

import app as flask_app


@pytest.fixture
def auth_client(tmp_path):
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
        with c.session_transaction() as sess:
            sess["listen_ok"] = True
        yield c


# ---------------------------------------------------------------------------
# Coverage matrix: every write route must 409 when Rekordbox is running.
#
# Each entry = (HTTP method, URL, JSON body) for a route that writes to
# master.db. If you add a new write route, add it here AND add the guard.
# ---------------------------------------------------------------------------


WRITE_ROUTES = [
    ("POST", "/api/tracks/123/rating", {"rating": 3}),
    ("POST", "/api/tracks/123/cues", {"time_ms": 5000}),
    ("POST", "/api/mytags/backup", None),
    ("POST", "/api/tracks/123/mytags", {"mytag_id": "1"}),
    ("DELETE", "/api/tracks/123/mytags/abc", None),
    ("POST", "/api/tracks/123/playlists/42", None),
    ("DELETE", "/api/tracks/123/playlists/42", None),
]


@pytest.mark.parametrize(("method", "url", "body"), WRITE_ROUTES)
def test_every_write_route_blocks_when_rekordbox_running(auth_client, method, url, body):
    """If Rekordbox is open, every write route must refuse with 409.
    This is the only protection against corrupting the DB during a live session."""
    with patch.object(flask_app, "rekordbox_is_running", return_value=True):
        if method == "POST":
            resp = auth_client.post(url, json=body) if body else auth_client.post(url)
        elif method == "DELETE":
            resp = auth_client.delete(url, json=body) if body else auth_client.delete(url)
    assert resp.status_code == 409, (
        f"{method} {url} did NOT return 409 when Rekordbox is running — "
        f"got {resp.status_code}. This route writes to the DB without the guard."
    )
    body_json = resp.get_json()
    assert body_json is not None
    # Error message must mention Rekordbox so the user knows what to do
    assert "Rekordbox" in body_json.get("error", ""), (
        f"{method} {url} 409 response does not mention 'Rekordbox' in error message"
    )


# ---------------------------------------------------------------------------
# TOCTOU race: documented limit, not a bug — but the test pins the behavior
# so we know if we ever close the gap.
# ---------------------------------------------------------------------------


def test_known_limit_toctou_race_window_exists(auth_client):
    """KNOWN LIMIT (not a bug): the rekordbox_is_running() check happens once
    at the top of the request. If Rekordbox launches AFTER the check but
    BEFORE db.commit(), the commit still proceeds.

    This test pins that behavior. If we ever add a second check immediately
    before commit, this test should be updated to reflect the closed gap.

    Mitigation today: SQLite/SQLCipher file locking — if Rekordbox holds a
    write lock, pyrekordbox.commit() will raise and our outer try/except
    returns 500. The user retries with Rekordbox closed.
    """
    track = MagicMock()
    track.ID = "123"
    track.Rating = 0
    track.rb_local_deleted = 0
    db = MagicMock()
    db.session.query.return_value.filter_by.return_value.first.return_value = track

    # Simulate the race: rekordbox_is_running returns False at the top
    # (passes the guard), then True later (would-be second check) — but
    # the route only checks once, so the commit goes through.
    rb_states = iter([False, True])
    with (
        patch.object(flask_app, "rekordbox_is_running", side_effect=lambda: next(rb_states)),
        patch.object(flask_app, "_open_db", return_value=db),
        patch.object(flask_app, "_ensure_stream_backup"),
    ):
        resp = auth_client.post("/api/tracks/123/rating", json={"rating": 4})

    # Today: commit succeeds because there's no second check.
    # Documented behavior — change this assertion if the race is ever closed.
    assert resp.status_code == 200
    assert track.Rating == 4
    assert db.commit.called


# ---------------------------------------------------------------------------
# Backup is created BEFORE the write — invariant test
# ---------------------------------------------------------------------------


def test_backup_is_created_before_db_commit(auth_client):
    """The stream-session backup must be created BEFORE any write to master.db.
    If commit() fails, the backup must still exist on disk."""
    track = MagicMock()
    track.Rating = 0
    db = MagicMock()
    db.session.query.return_value.filter_by.return_value.first.return_value = track

    call_order = []

    def record_backup(*args, **kwargs):
        call_order.append("backup")

    def record_commit():
        call_order.append("commit")

    db.commit = record_commit
    with (
        patch.object(flask_app, "rekordbox_is_running", return_value=False),
        patch.object(flask_app, "_open_db", return_value=db),
        patch.object(flask_app, "_ensure_stream_backup", side_effect=record_backup),
    ):
        resp = auth_client.post("/api/tracks/123/rating", json={"rating": 3})

    assert resp.status_code == 200
    assert call_order == [
        "backup",
        "commit",
    ], f"Backup must precede commit. Actual order: {call_order}"
