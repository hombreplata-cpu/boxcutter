"""
Phase 2 tests — config allowlist, PIN validation, route fixes.

Covers v1.1 roadmap items S-01, S-11, B-04, B-07, B-13, B-14, R-01.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import Forbidden, NotFound

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as flask_app  # noqa: E402

# ---------------------------------------------------------------------------
# S-01 — /api/config allowlist
# ---------------------------------------------------------------------------


@pytest.fixture
def config_client(tmp_path):
    flask_app.app.config["TESTING"] = True
    cfg_file = tmp_path / "config.json"
    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        flask_app.app.test_client() as c,
    ):
        yield c, cfg_file


def test_api_config_drops_secret_key(config_client):
    """An attacker must not be able to set the Flask session signing key
    via /api/config. Most critical S-01 test."""
    client, cfg_file = config_client
    resp = client.post(
        "/api/config",
        data=json.dumps({"_secret_key": "deadbeef" * 8, "db_path": "/x"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "_secret_key" not in body["config"]
    # Read back from disk too, to make sure it wasn't written
    with open(cfg_file) as f:
        on_disk = json.load(f)
    assert "_secret_key" not in on_disk
    assert on_disk["db_path"] == "/x"


def test_api_config_drops_unknown_keys(config_client):
    """Unknown keys must not be persisted at all."""
    client, cfg_file = config_client
    resp = client.post(
        "/api/config",
        data=json.dumps({"foo": "bar", "__proto__": "evil", "db_path": "/x"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "foo" not in body["config"]
    assert "__proto__" not in body["config"]
    with open(cfg_file) as f:
        on_disk = json.load(f)
    assert "foo" not in on_disk
    assert "__proto__" not in on_disk


def test_api_config_accepts_all_known_keys(config_client):
    """Every key in DEFAULT_CONFIG (the allowlist source) must round-trip."""
    client, _ = config_client
    payload = {
        "music_root": "/music",
        "flac_root": "/flac",
        "mp3_root": "/mp3",
        "delete_dir": "/delete",
        "watch_dir": "/watch",
        "db_path": "/db",
        "target_playlist_id": "42",
        "cleanup_exclude": "/excl",
        "donation_shown": True,
        "listen_pin": "1234",
    }
    resp = client.post("/api/config", data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 200
    body = resp.get_json()
    for k, v in payload.items():
        assert body["config"][k] == v


# ---------------------------------------------------------------------------
# S-11 — listen_pin validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pin", "expected"),
    [
        ("", ""),  # empty disables — allowed
        ("1234", "1234"),
        ("12345", "12345"),
        ("12345678", "12345678"),
        ("  1234  ", "1234"),  # whitespace stripped
    ],
)
def test_validate_listen_pin_accepts_valid(pin, expected):
    out, err = flask_app._validate_listen_pin(pin)
    assert out == expected
    assert err is None


@pytest.mark.parametrize(
    "pin",
    [
        "abc",
        "abcd",
        "12",  # too short
        "123",  # too short
        "123456789",  # too long
        "12 34",  # internal space
        "12-34",  # dash
        "0x1234",
        " a b c d ",
    ],
)
def test_validate_listen_pin_rejects_invalid(pin):
    out, err = flask_app._validate_listen_pin(pin)
    assert out == ""
    assert err is not None
    assert "digit" in err.lower()


def test_api_config_rejects_non_digit_pin(config_client):
    client, cfg_file = config_client
    resp = client.post(
        "/api/config",
        data=json.dumps({"listen_pin": "abcd"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    # And nothing was persisted
    if cfg_file.exists():
        with open(cfg_file) as f:
            on_disk = json.load(f)
        assert on_disk.get("listen_pin", "") != "abcd"


def test_setup_post_rejects_non_digit_pin(tmp_path):
    flask_app.app.config["TESTING"] = True
    cfg_file = tmp_path / "config.json"
    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        flask_app.app.test_client() as c,
    ):
        resp = c.post(
            "/setup",
            data={
                "music_root": "/m",
                "flac_root": "/f",
                "mp3_root": "",
                "delete_dir": "",
                "watch_dir": "",
                "db_path": "/db",
                "listen_pin": "abcd",
            },
        )
        # Rendered with error and 400 status
        assert resp.status_code == 400
        # No config written on rejection
        if cfg_file.exists():
            with open(cfg_file) as f:
                on_disk = json.load(f)
            # listen_pin must not have been persisted as 'abcd'
            assert on_disk.get("listen_pin", "") != "abcd"


def test_setup_post_accepts_valid_pin(tmp_path):
    flask_app.app.config["TESTING"] = True
    cfg_file = tmp_path / "config.json"
    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        flask_app.app.test_client() as c,
    ):
        resp = c.post(
            "/setup",
            data={
                "music_root": "/m",
                "flac_root": "/f",
                "mp3_root": "",
                "delete_dir": "",
                "watch_dir": "",
                "db_path": "/db",
                "listen_pin": "987654",
            },
            follow_redirects=False,
        )
        # Either redirect (config complete) or 200 — never 400
        assert resp.status_code in (200, 302)
        with open(cfg_file) as f:
            on_disk = json.load(f)
        assert on_disk["listen_pin"] == "987654"


# ---------------------------------------------------------------------------
# B-14 — abort(N) is no longer swallowed by the global handler
# ---------------------------------------------------------------------------


def test_handle_exception_returns_httpexception_unchanged():
    """The global handler must let werkzeug HTTPExceptions render themselves
    rather than turning every abort(N) into a 500 + crash log (B-14)."""
    with flask_app.app.test_request_context("/some/path"):
        not_found = NotFound()
        result = flask_app.handle_exception(not_found)
        # Flask returns the exception itself; status code must be 404
        assert result is not_found
        assert result.code == 404

        forbidden = Forbidden()
        result = flask_app.handle_exception(forbidden)
        assert result is forbidden
        assert result.code == 403


def test_handle_exception_still_500s_on_real_exception(tmp_path):
    """A non-HTTPException must still produce a 500 with crash log."""
    fake_log = tmp_path / "fake.log"
    with (
        flask_app.app.test_request_context("/some/path"),
        patch("app.write_crash_log", return_value=fake_log),
    ):
        result = flask_app.handle_exception(RuntimeError("boom"))
    # result is a (response, status) tuple
    if isinstance(result, tuple):
        _, status = result
    else:
        status = result.status_code
    assert status == 500


# ---------------------------------------------------------------------------
# R-01 — /api/history int parse failure → 400, not 500
# ---------------------------------------------------------------------------


def test_history_invalid_page_returns_400(tmp_path):
    flask_app.app.config["TESTING"] = True
    hist_file = tmp_path / "history.json"
    with (
        patch.object(flask_app, "HISTORY_FILE", hist_file),
        flask_app.app.test_client() as c,
    ):
        resp = c.get("/api/history?page=abc")
        assert resp.status_code == 400
        resp = c.get("/api/history?per_page=xyz")
        assert resp.status_code == 400
        # Valid still works
        resp = c.get("/api/history?page=1&per_page=20")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# B-04 — strip_comments dry_run flag preserved in history
# ---------------------------------------------------------------------------


def test_strip_comments_dry_run_flag_preserved_in_history(tmp_path):
    """A dry-run strip_comments call must record dry_run=True in history.
    Previously the route force-set it to False unconditionally."""
    flask_app.app.config["TESTING"] = True
    cfg_file = tmp_path / "config.json"
    hist_file = tmp_path / "history.json"
    cfg_file.write_text(json.dumps({"music_root": str(tmp_path / "music"), "db_path": "/x"}))
    (tmp_path / "music").mkdir()

    fake_proc = MagicMock()
    fake_proc.stdout.readline.side_effect = ["", ""]  # immediate EOF
    fake_proc.wait.return_value = None
    fake_proc.returncode = 0
    fake_proc.stdout.close = MagicMock()

    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        patch.object(flask_app, "HISTORY_FILE", hist_file),
        patch("app.subprocess.Popen", return_value=fake_proc),
        flask_app.app.test_client() as c,
    ):
        resp = c.get("/api/run/strip_comments?dry_run=1&dir1=" + str(tmp_path / "music"))
        # Drain the SSE stream so generate() finishes and writes the history entry
        resp.get_data()

    with open(hist_file) as f:
        history = json.load(f)
    assert len(history) == 1
    assert history[0]["dry_run"] is True


def test_strip_comments_live_flag_preserved_in_history(tmp_path):
    """A live (non-dry-run) call records dry_run=False."""
    flask_app.app.config["TESTING"] = True
    cfg_file = tmp_path / "config.json"
    hist_file = tmp_path / "history.json"
    cfg_file.write_text(json.dumps({"music_root": str(tmp_path / "music"), "db_path": "/x"}))
    (tmp_path / "music").mkdir()

    fake_proc = MagicMock()
    fake_proc.stdout.readline.side_effect = ["", ""]
    fake_proc.wait.return_value = None
    fake_proc.returncode = 0
    fake_proc.stdout.close = MagicMock()

    captured_cmd = {}

    def _record_popen(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        return fake_proc

    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        patch.object(flask_app, "HISTORY_FILE", hist_file),
        patch("app.subprocess.Popen", side_effect=_record_popen),
        flask_app.app.test_client() as c,
    ):
        resp = c.get("/api/run/strip_comments?dir1=" + str(tmp_path / "music"))
        resp.get_data()

    # --write must be in cmd; --dry-run must NOT be (script doesn't accept it)
    assert "--write" in captured_cmd["cmd"]
    assert "--dry-run" not in captured_cmd["cmd"]
    with open(hist_file) as f:
        history = json.load(f)
    assert history[0]["dry_run"] is False


# ---------------------------------------------------------------------------
# B-07 — relocate.py does not commit when zero updates
# ---------------------------------------------------------------------------


def test_relocate_no_commit_when_zero_updates(tmp_path):
    """Live mode with id_filter matching nothing must NOT call db.commit()."""
    from scripts import rekordbox_relocate as rr  # noqa: PLC0415

    target = tmp_path / "target"
    target.mkdir()

    db = MagicMock()
    db.engine.url.database = str(tmp_path / "fake.db")
    db.get_content().filter_by().all.return_value = []  # zero contents

    # Build args namespace
    args = MagicMock()
    args.target_root = str(target)
    args.source_root = []
    args.target_ext = "flac"
    args.source_ext = ""
    args.prefer_ext = ""
    args.extensions = None
    args.dry_run = False
    args.all_tracks = False
    args.missing_only = False
    args.ids = None
    args.db_path = str(tmp_path / "fake.db")

    with patch("scripts.rekordbox_relocate.MasterDatabase", return_value=db):
        rr.run(args)

    assert not db.commit.called, "db.commit() was called even though no rows were updated"


# ---------------------------------------------------------------------------
# B-13 — add_new.py: zero-valued numeric tags are not persisted
# ---------------------------------------------------------------------------


def test_add_new_zero_bpm_not_persisted():
    from scripts import rekordbox_add_new as ran  # noqa: PLC0415

    fake_audio = MagicMock()
    fake_audio.get.side_effect = lambda k: {
        "title": ["Track"],
        "bpm": ["0"],
        "date": ["0000"],
        "tracknumber": ["0/12"],
    }.get(k)
    fake_audio.info = MagicMock(length=180.0, bitrate=320000, sample_rate=44100)

    with patch("mutagen.File", return_value=fake_audio):
        tags = ran.read_audio_tags("/fake.mp3")

    assert "bpm" not in tags
    assert "year" not in tags
    assert "track_no" not in tags
    # But valid stream info still stored
    assert tags.get("length_ms") == 180000
    assert tags.get("bitrate") == 320


def test_add_new_real_bpm_persisted():
    """Sanity: a real BPM is still stored (the filter only excludes 0)."""
    from scripts import rekordbox_add_new as ran  # noqa: PLC0415

    fake_audio = MagicMock()
    fake_audio.get.side_effect = lambda k: {
        "title": ["Track"],
        "bpm": ["128"],
        "date": ["2024"],
        "tracknumber": ["3"],
    }.get(k)
    fake_audio.info = MagicMock(length=180.0, bitrate=320000, sample_rate=44100)

    with patch("mutagen.File", return_value=fake_audio):
        tags = ran.read_audio_tags("/fake.mp3")

    assert tags["bpm"] == 12800  # 128 × 100
    assert tags["year"] == 2024
    assert tags["track_no"] == 3
