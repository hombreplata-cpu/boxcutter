"""
Tests for config and path-handling utilities in app.py.

Covers:
- clean_path() strips surrounding quotes and whitespace (the "Copy as path" bug)
- config_is_complete() gates on all three required keys
- load_config() merges stored JSON over DEFAULT_CONFIG so new keys are available
- /api/config POST round-trips config data
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as flask_app  # noqa: E402

# ---------------------------------------------------------------------------
# clean_path
# ---------------------------------------------------------------------------


def test_clean_path_strips_double_quotes():
    assert flask_app.clean_path('"C:\\Music\\FLAC"') == "C:\\Music\\FLAC"


def test_clean_path_strips_single_quotes():
    assert flask_app.clean_path("'/Users/dj/Music'") == "/Users/dj/Music"


def test_clean_path_strips_leading_trailing_whitespace():
    assert flask_app.clean_path("  C:\\Music  ") == "C:\\Music"


def test_clean_path_strips_quotes_and_whitespace():
    assert flask_app.clean_path('  "C:\\Music\\FLAC"  ') == "C:\\Music\\FLAC"


def test_clean_path_empty_string_unchanged():
    assert flask_app.clean_path("") == ""


def test_clean_path_none_returns_none():
    assert flask_app.clean_path(None) is None


def test_clean_path_plain_path_unchanged():
    assert flask_app.clean_path("C:\\Music\\FLAC") == "C:\\Music\\FLAC"


def test_clean_path_expands_tilde_home():
    raw = "~/Library/Application Support/Pioneer/rekordbox/master.db"
    assert flask_app.clean_path(raw) == os.path.expanduser(raw)
    assert not flask_app.clean_path(raw).startswith("~")


def test_clean_path_expands_tilde_after_quote_strip():
    raw = '"~/Library/foo"'
    assert flask_app.clean_path(raw) == os.path.expanduser("~/Library/foo")


def test_clean_path_absolute_mac_path_unchanged():
    assert flask_app.clean_path("/Users/dj/Music") == "/Users/dj/Music"


def test_clean_path_windows_path_unchanged():
    assert flask_app.clean_path("C:\\Music\\FLAC") == "C:\\Music\\FLAC"


def test_clean_path_short_non_path_string_unchanged():
    assert flask_app.clean_path("flac") == "flac"


# ---------------------------------------------------------------------------
# config_is_complete
# ---------------------------------------------------------------------------


def test_config_is_complete_true():
    cfg = {"music_root": "/music", "flac_root": "/flac", "db_path": "/db/master.db"}
    assert flask_app.config_is_complete(cfg) is True


def test_config_is_complete_missing_db_path():
    cfg = {"music_root": "/music", "flac_root": "/flac", "db_path": ""}
    assert flask_app.config_is_complete(cfg) is False


def test_config_is_complete_missing_music_root():
    cfg = {"music_root": "", "flac_root": "/flac", "db_path": "/db/master.db"}
    assert flask_app.config_is_complete(cfg) is False


def test_config_is_complete_missing_flac_root():
    cfg = {"music_root": "/music", "flac_root": "", "db_path": "/db/master.db"}
    assert flask_app.config_is_complete(cfg) is False


def test_config_is_complete_all_empty():
    assert flask_app.config_is_complete({}) is False


# ---------------------------------------------------------------------------
# load_config — merges new defaults over stored config
# ---------------------------------------------------------------------------


def test_load_config_merges_new_default_keys(tmp_path):
    """A key present in DEFAULT_CONFIG but absent from the stored file is available after load."""
    stored = {"music_root": "/my/music", "db_path": "/db/master.db"}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(stored), encoding="utf-8")

    with patch.object(flask_app, "CONFIG_FILE", config_file):
        cfg = flask_app.load_config()

    assert cfg["music_root"] == "/my/music"
    assert "flac_root" in cfg  # default key added by merge


def test_load_config_returns_defaults_when_file_missing(tmp_path):
    missing = tmp_path / "no_config.json"
    with patch.object(flask_app, "CONFIG_FILE", missing):
        cfg = flask_app.load_config()
    assert "music_root" in cfg
    assert cfg["music_root"] == ""


def test_load_config_returns_defaults_on_corrupt_file(tmp_path):
    bad_file = tmp_path / "config.json"
    bad_file.write_text("{not valid json", encoding="utf-8")
    with patch.object(flask_app, "CONFIG_FILE", bad_file):
        cfg = flask_app.load_config()
    assert "music_root" in cfg


# ---------------------------------------------------------------------------
# /api/config POST
# ---------------------------------------------------------------------------


@pytest.fixture
def config_client(tmp_path):
    flask_app.app.config["TESTING"] = True
    config_file = tmp_path / "config.json"
    with (
        patch.object(flask_app, "CONFIG_FILE", config_file),
        flask_app.app.test_client() as c,
    ):
        yield c


def test_api_config_saves_and_returns_config(config_client):
    payload = {"music_root": "/new/music", "db_path": "/db/master.db"}
    resp = config_client.post(
        "/api/config", data=json.dumps(payload), content_type="application/json"
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["config"]["music_root"] == "/new/music"
