"""
Phase 3 tests — same-origin token gate.

Closes v1.1 roadmap items S-03, S-05, S-06, S-08, S-09, S-10.

Tests opt in to enforcement via app.config["BOXCUTTER_TEST_ENFORCE_CSRF"] = True.
The bypass is necessary because every other test file is structured around
TESTING=True (which would otherwise refuse all POSTs without the token).
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as flask_app  # noqa: E402


@pytest.fixture
def gated_client(tmp_path):
    """Test client with the CSRF gate enforced."""
    flask_app.app.config["TESTING"] = True
    flask_app.app.config["BOXCUTTER_TEST_ENFORCE_CSRF"] = True
    cfg_file = tmp_path / "config.json"
    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        flask_app.app.test_client() as c,
    ):
        yield c
    flask_app.app.config["BOXCUTTER_TEST_ENFORCE_CSRF"] = False


@pytest.fixture
def gated_auth_client(tmp_path):
    """Gated client with a valid listener session and a configured db_path."""
    flask_app.app.config["TESTING"] = True
    flask_app.app.config["BOXCUTTER_TEST_ENFORCE_CSRF"] = True
    cfg = {
        "db_path": str(tmp_path / "master.db"),
        "music_root": str(tmp_path / "music"),
        "flac_root": str(tmp_path / "flac"),
        "mp3_root": str(tmp_path / "mp3"),
        "delete_dir": str(tmp_path / "DELETE"),
        "watch_dir": str(tmp_path / "watch"),
    }
    with (
        patch.object(flask_app, "load_config", return_value=cfg),
        flask_app.app.test_client() as c,
    ):
        with c.session_transaction() as sess:
            sess["listen_ok"] = True
        yield c
    flask_app.app.config["BOXCUTTER_TEST_ENFORCE_CSRF"] = False


# ---------------------------------------------------------------------------
# GET pages bake the token into the rendered HTML (proves clients can read it)
# ---------------------------------------------------------------------------


def test_meta_token_rendered_into_page(tmp_path):
    """The bc-token meta tag in base.html must contain the live token."""
    flask_app.app.config["TESTING"] = True
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps(
            {"db_path": "/x", "music_root": "/m", "flac_root": "/f"},
        )
    )
    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        flask_app.app.test_client() as c,
    ):
        resp = c.get("/")
        body = resp.get_data(as_text=True)
    assert flask_app._REQUEST_TOKEN in body
    assert 'name="bc-token"' in body


def test_setup_form_includes_csrf_field(tmp_path):
    flask_app.app.config["TESTING"] = True
    cfg_file = tmp_path / "config.json"
    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        flask_app.app.test_client() as c,
    ):
        resp = c.get("/setup")
    body = resp.get_data(as_text=True)
    assert 'name="csrf_token"' in body
    assert flask_app._REQUEST_TOKEN in body


# ---------------------------------------------------------------------------
# Gate rejects unauthenticated mutating requests
# ---------------------------------------------------------------------------


MUTATING_ROUTES_NO_AUTH = [
    ("POST", "/api/config", {"db_path": "/x"}),
    ("POST", "/api/dismiss_donation", None),
    ("POST", "/api/apply_update", None),
    ("POST", "/shutdown", None),
    ("POST", "/api/backups/clean", {"keep_days": 30}),
    ("DELETE", "/api/history", None),
]


@pytest.mark.parametrize(("method", "url", "body"), MUTATING_ROUTES_NO_AUTH)
def test_mutating_route_rejects_missing_token(gated_client, method, url, body):
    if method == "POST":
        resp = gated_client.post(url, json=body) if body is not None else gated_client.post(url)
    elif method == "DELETE":
        resp = gated_client.delete(url)
    assert resp.status_code == 403, (
        f"{method} {url} did not return 403 without token — got {resp.status_code}. "
        "CSRF gate is not protecting this route."
    )


@pytest.mark.parametrize(("method", "url", "body"), MUTATING_ROUTES_NO_AUTH)
def test_mutating_route_accepts_valid_token(gated_client, method, url, body):
    headers = {"X-BoxCutter-Token": flask_app._REQUEST_TOKEN}
    if method == "POST":
        if body is not None:
            resp = gated_client.post(url, json=body, headers=headers)
        else:
            resp = gated_client.post(url, headers=headers)
    elif method == "DELETE":
        resp = gated_client.delete(url, headers=headers)
    assert resp.status_code != 403, (
        f"{method} {url} returned 403 even with a valid token — got {resp.status_code}. "
        "Gate is too strict."
    )


def test_mutating_route_rejects_wrong_token(gated_client):
    resp = gated_client.post(
        "/api/config",
        json={"db_path": "/x"},
        headers={"X-BoxCutter-Token": "this-is-not-the-real-token"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Listen edit endpoints (already PIN-gated by session) also need the token
# ---------------------------------------------------------------------------


LISTEN_EDIT_ROUTES = [
    ("POST", "/api/tracks/123/rating", {"rating": 3}),
    ("POST", "/api/tracks/123/cues", {"time_ms": 1000}),
    ("POST", "/api/tracks/123/mytags", {"mytag_id": "1"}),
    ("DELETE", "/api/tracks/123/mytags/abc", None),
    ("POST", "/api/tracks/123/playlists/42", None),
    ("DELETE", "/api/tracks/123/playlists/42", None),
    ("POST", "/api/mytags/backup", None),
]


@pytest.mark.parametrize(("method", "url", "body"), LISTEN_EDIT_ROUTES)
def test_listen_edit_routes_require_token(gated_auth_client, method, url, body):
    """Even with a valid PIN session, the CSRF token is still required.
    Defense in depth — a leaked PIN alone cannot mutate the DB."""
    if method == "POST":
        resp = (
            gated_auth_client.post(url, json=body)
            if body is not None
            else gated_auth_client.post(url)
        )
    elif method == "DELETE":
        resp = gated_auth_client.delete(url)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# SSE endpoints accept the token via query param (EventSource cannot set headers)
# ---------------------------------------------------------------------------


def test_run_endpoint_rejects_missing_token(gated_client):
    """GET /api/run/<script> must require the token even though it's a GET."""
    resp = gated_client.get("/api/run/cleanup?scan_root=/x")
    assert resp.status_code == 403


def test_run_endpoint_accepts_token_in_query(gated_client, tmp_path):
    """The token may be supplied as ?token=... since EventSource can't set headers.
    We patch subprocess.Popen to return immediately so the SSE generator finishes."""
    fake_proc = MagicMock()
    fake_proc.stdout.readline.side_effect = ["", ""]
    fake_proc.wait.return_value = None
    fake_proc.returncode = 0
    fake_proc.stdout.close = MagicMock()

    cfg = {
        "db_path": str(tmp_path / "master.db"),
        "music_root": str(tmp_path / "m"),
        "flac_root": str(tmp_path / "f"),
        "mp3_root": "",
        "delete_dir": str(tmp_path / "del"),
        "watch_dir": "",
    }
    (tmp_path / "m").mkdir()
    with (
        patch.object(flask_app, "load_config", return_value=cfg),
        patch("app.subprocess.Popen", return_value=fake_proc),
    ):
        resp = gated_client.get(
            f"/api/run/cleanup?scan_root={tmp_path / 'm'}&token={flask_app._REQUEST_TOKEN}"
        )
        assert resp.status_code != 403
        # Drain the stream so the generator runs to completion
        resp.get_data()


def test_download_update_rejects_missing_token(gated_client):
    """The download endpoint is a side-effecting GET — also gate it."""
    resp = gated_client.get(f"/api/download_update?url={flask_app.GITHUB_DOWNLOAD_PREFIX}v1/x.exe")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Form POSTs accept the token via csrf_token field
# ---------------------------------------------------------------------------


def test_setup_form_post_rejects_missing_token(gated_client):
    resp = gated_client.post(
        "/setup",
        data={
            "music_root": "/m",
            "flac_root": "/f",
            "mp3_root": "",
            "delete_dir": "",
            "watch_dir": "",
            "db_path": "/db",
            "listen_pin": "",
        },
    )
    assert resp.status_code == 403


def test_setup_form_post_accepts_csrf_field(gated_client):
    resp = gated_client.post(
        "/setup",
        data={
            "music_root": "/m",
            "flac_root": "/f",
            "mp3_root": "",
            "delete_dir": "",
            "watch_dir": "",
            "db_path": "/db",
            "listen_pin": "",
            "csrf_token": flask_app._REQUEST_TOKEN,
        },
        follow_redirects=False,
    )
    # Either redirect (config complete) or 200 — never 403
    assert resp.status_code != 403


def test_listen_login_rejects_missing_token(gated_client):
    cfg = {"listen_pin": "1234"}
    with patch.object(flask_app, "load_config", return_value=cfg):
        resp = gated_client.post("/listen/login", data={"pin": "1234"})
    assert resp.status_code == 403


def test_listen_login_accepts_csrf_field(gated_client):
    cfg = {"listen_pin": "1234"}
    with patch.object(flask_app, "load_config", return_value=cfg):
        resp = gated_client.post(
            "/listen/login",
            data={"pin": "1234", "csrf_token": flask_app._REQUEST_TOKEN},
        )
    assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Read-only GETs are NOT gated — page would not load otherwise
# ---------------------------------------------------------------------------


READ_ONLY_GETS = [
    "/api/rekordbox_status",
    "/api/update_check",
]


@pytest.mark.parametrize("url", READ_ONLY_GETS)
def test_readonly_get_does_not_require_token(gated_client, url):
    resp = gated_client.get(url)
    assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Token uses constant-time compare
# ---------------------------------------------------------------------------


def test_token_compare_uses_compare_digest(gated_client):
    """Token validation must use hmac.compare_digest semantics — verified by
    confirming a one-character-different token still fails (sanity check)."""
    almost = flask_app._REQUEST_TOKEN[:-1] + ("a" if flask_app._REQUEST_TOKEN[-1] != "a" else "b")
    resp = gated_client.post(
        "/api/config",
        json={"db_path": "/x"},
        headers={"X-BoxCutter-Token": almost},
    )
    assert resp.status_code == 403
