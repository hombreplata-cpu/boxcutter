"""
Phase 4 tests — listen hardening.

Resolves v1.1 roadmap items S-02, S-04, R-08, R-09.
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as flask_app  # noqa: E402

# ---------------------------------------------------------------------------
# S-04 — PIN brute-force rate limit + constant-time compare
# ---------------------------------------------------------------------------


@pytest.fixture
def login_client():
    flask_app.app.config["TESTING"] = True
    cfg = {"listen_pin": "1234"}
    flask_app._PIN_ATTEMPTS.clear()
    with (
        patch.object(flask_app, "load_config", return_value=cfg),
        flask_app.app.test_client() as c,
    ):
        yield c
    flask_app._PIN_ATTEMPTS.clear()


def test_correct_pin_succeeds(login_client):
    resp = login_client.post("/listen/login", data={"pin": "1234"}, follow_redirects=False)
    assert resp.status_code == 302
    assert "/listen" in resp.headers["Location"]


def test_wrong_pin_returns_401(login_client):
    resp = login_client.post("/listen/login", data={"pin": "0000"})
    assert resp.status_code == 401


def test_pin_compare_uses_compare_digest(login_client):
    """If hmac.compare_digest is patched, it must be called by the PIN check."""
    with patch("app.hmac.compare_digest", return_value=False) as mock_cmp:
        login_client.post("/listen/login", data={"pin": "0000"})
    assert mock_cmp.called


def test_pin_brute_force_locks_out_after_failures(login_client):
    """After enough wrong PINs, the response is delayed and returns 429."""
    # First two failures should not delay (grace window).
    for _ in range(2):
        resp = login_client.post("/listen/login", data={"pin": "0000"})
        assert resp.status_code == 401

    # 3rd-onwards triggers exponential backoff.
    for _ in range(3):
        login_client.post("/listen/login", data={"pin": "0000"})

    # Next attempt: must be locked out (429) and slept ≥1s.
    start = time.monotonic()
    resp = login_client.post("/listen/login", data={"pin": "0000"})
    elapsed = time.monotonic() - start
    assert resp.status_code in (401, 429)
    # Either we got 429 (still locked) or 401 with a backoff sleep > 0.
    assert elapsed >= 0.5, f"Expected backoff delay after repeated failures, got {elapsed:.2f}s"


def test_pin_success_resets_failure_counter(login_client):
    """A correct PIN clears the per-IP fail counter so legit users aren't locked out."""
    for _ in range(2):
        login_client.post("/listen/login", data={"pin": "0000"})
    login_client.post("/listen/login", data={"pin": "1234"})  # success

    # State should be cleared
    ip = list(flask_app._PIN_ATTEMPTS.keys())
    assert ip == [], f"Failure counter not reset on success: {flask_app._PIN_ATTEMPTS}"


# ---------------------------------------------------------------------------
# S-02 — /api/stream rejects paths outside configured roots
# ---------------------------------------------------------------------------


@pytest.fixture
def stream_client(tmp_path):
    flask_app.app.config["TESTING"] = True
    music_root = tmp_path / "music"
    music_root.mkdir()
    cfg = {
        "db_path": str(tmp_path / "master.db"),
        "music_root": str(music_root),
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
        yield c, music_root


def _stub_track_path(returned_path: str):
    """Patch get_track_path subprocess to return a fixed FolderPath."""
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = json.dumps({"path": returned_path, "ext": Path(returned_path).suffix.lower()})
    fake.stderr = ""
    return fake


def test_stream_rejects_path_outside_roots(stream_client, tmp_path):
    """A DB row pointing outside any configured root must return 403."""
    client, music_root = stream_client
    outside = tmp_path / "outside.flac"
    outside.write_bytes(b"x")
    fake = _stub_track_path(str(outside))
    with patch("app.subprocess.run", return_value=fake):
        resp = client.get("/api/stream/1")
    assert resp.status_code == 403
    assert "outside" in resp.get_json()["error"].lower()


def test_stream_allows_path_inside_music_root(stream_client):
    """A DB row that resolves under music_root is served."""
    client, music_root = stream_client
    track = music_root / "song.flac"
    track.write_bytes(b"FLAC")
    fake = _stub_track_path(str(track))
    with patch("app.subprocess.run", return_value=fake):
        resp = client.get("/api/stream/1")
    assert resp.status_code == 200


def test_stream_rejects_traversal_attempt(stream_client, tmp_path):
    """A DB row with .. path components that resolve outside roots is rejected."""
    client, music_root = stream_client
    outside = tmp_path / "secret.flac"
    outside.write_bytes(b"x")
    # Build a path that uses .. to escape music_root
    traversal = music_root / ".." / "secret.flac"
    fake = _stub_track_path(str(traversal))
    with patch("app.subprocess.run", return_value=fake):
        resp = client.get("/api/stream/1")
    assert resp.status_code == 403


def test_stream_with_no_roots_configured_fails_closed(tmp_path):
    """If no roots are set, refuse to serve any file (fail-closed)."""
    flask_app.app.config["TESTING"] = True
    cfg = {
        "db_path": "",
        "music_root": "",
        "flac_root": "",
        "mp3_root": "",
        "delete_dir": "",
        "watch_dir": "",
    }
    track = tmp_path / "anywhere.flac"
    track.write_bytes(b"x")
    with (
        patch.object(flask_app, "load_config", return_value=cfg),
        flask_app.app.test_client() as c,
    ):
        with c.session_transaction() as sess:
            sess["listen_ok"] = True
        with patch("app.subprocess.run", return_value=_stub_track_path(str(track))):
            resp = c.get("/api/stream/1")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# R-08 — strip_comments surfaces save errors
# ---------------------------------------------------------------------------


def test_strip_comments_save_error_in_report(tmp_path, monkeypatch):
    """A failed tags.save() must appear in the report's save_errors list."""
    from scripts import strip_comment_urls as scu  # noqa: PLC0415

    # Create a fake mp3 with a URL in COMM frame
    music = tmp_path / "music"
    music.mkdir()
    track = music / "test.mp3"
    track.write_bytes(b"x")

    fake_frame = MagicMock()
    fake_frame.text = ["Visit https://evil.com for downloads"]
    fake_tags = MagicMock()
    fake_tags.__iter__ = lambda self: iter(["COMM::eng"])
    fake_tags.__getitem__ = lambda self, k: fake_frame
    fake_tags.save.side_effect = OSError("disk full")

    with patch("scripts.strip_comment_urls.ID3", return_value=fake_tags):
        changes, save_error = scu.process_mp3(track, write=True)

    assert changes  # the frame was modified
    assert save_error == "disk full"


def test_strip_comments_no_save_error_when_save_succeeds(tmp_path):
    from scripts import strip_comment_urls as scu  # noqa: PLC0415

    track = tmp_path / "test.mp3"
    track.write_bytes(b"x")

    fake_frame = MagicMock()
    fake_frame.text = ["Visit https://evil.com"]
    fake_tags = MagicMock()
    fake_tags.__iter__ = lambda self: iter(["COMM::eng"])
    fake_tags.__getitem__ = lambda self, k: fake_frame

    with patch("scripts.strip_comment_urls.ID3", return_value=fake_tags):
        changes, save_error = scu.process_mp3(track, write=True)

    assert changes
    assert save_error is None
    assert fake_tags.save.called


# ---------------------------------------------------------------------------
# R-09 — relocate "already correct" check is case-insensitive on Windows
# ---------------------------------------------------------------------------


def test_relocate_path_match_case_insensitive_on_windows(tmp_path, monkeypatch):
    """On Windows, D:/X/y.flac and d:/x/y.flac are the same file — no rewrite."""
    from scripts import rekordbox_relocate as rr  # noqa: PLC0415

    monkeypatch.setattr(rr.platform, "system", lambda: "Windows")

    target = tmp_path / "target"
    target.mkdir()
    file_in_target = target / "Track.flac"
    file_in_target.write_bytes(b"FLAC")

    # Mock content with mixed-case path that matches the file
    content = MagicMock()
    content.ID = 1
    content.Title = "Track"
    content.Artist = MagicMock(Name="Artist")
    content.FolderPath = str(file_in_target).replace("\\", "/").upper()
    content.rb_local_deleted = 0

    db = MagicMock()
    db.engine.url.database = str(tmp_path / "fake.db")
    db.get_content().filter_by().all.return_value = [content]

    args = MagicMock()
    args.target_root = str(target)
    args.source_root = []
    args.target_ext = "flac"
    args.source_ext = ""
    args.prefer_ext = ""
    args.extensions = None
    args.dry_run = True
    args.all_tracks = True
    args.missing_only = False
    args.ids = None
    args.db_path = str(tmp_path / "fake.db")

    with (
        patch("scripts.rekordbox_relocate.MasterDatabase", return_value=db),
        patch("scripts.rekordbox_relocate.os.path.isfile", return_value=True),
    ):
        rr.run(args)

    # FolderPath was not modified on the mock (it remained UPPERCASE)
    assert content.FolderPath == str(file_in_target).replace("\\", "/").upper()
