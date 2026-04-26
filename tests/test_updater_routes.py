"""
Tests for the in-app auto-updater routes (PLAN 015).

Covers (security-critical):
- _version_gt: semver comparison correctness
- GET  /api/update_check    — must return {available: false} in dev mode (no GitHub hit)
- GET  /api/download_update — must reject any URL not starting with the hard-coded
                              GitHub download prefix (CRITICAL: the only barrier
                              between the client and arbitrary executable download)
- POST /api/apply_update    — must reject when no installer path is staged

These routes had ZERO test coverage before this file. The download/apply pair
executes a binary, so the URL allowlist is the only thing keeping it safe.
"""

from unittest.mock import patch

import pytest

import app as flask_app

# ---------------------------------------------------------------------------
# _version_gt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("1.1.0", "1.0.0", True),
        ("1.0.1", "1.0.0", True),
        ("2.0.0", "1.9.9", True),
        ("1.0.0", "1.0.0", False),  # equal is not strictly greater
        ("1.0.0", "1.1.0", False),
        ("1.0.0", "2.0.0", False),
        ("1.10.0", "1.9.0", True),  # numeric, not lexicographic
    ],
)
def test_version_gt(a, b, expected):
    assert flask_app._version_gt(a, b) is expected


def test_version_gt_handles_garbage_input():
    """Bad input must not crash — falls back to (0,) tuple."""
    # Both garbage → both (0,) → not strictly greater
    assert flask_app._version_gt("garbage", "junk") is False


# ---------------------------------------------------------------------------
# GET /api/update_check
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as c:
        yield c


def test_update_check_dev_mode_returns_false_without_github_hit(client):
    """In dev mode (sys.frozen unset), the route must short-circuit and not call urlopen."""
    # sys.frozen is unset by default in the test environment.
    with patch("app.urllib.request.urlopen") as mock_urlopen:
        resp = client.get("/api/update_check")
    assert resp.status_code == 200
    assert resp.get_json() == {"available": False}
    assert not mock_urlopen.called  # critical: no network in dev mode


# ---------------------------------------------------------------------------
# GET /api/download_update — URL allowlist (security-critical)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "evil_url",
    [
        "https://evil.com/installer.exe",
        "http://github.com/hombreplata-cpu/boxcutter/releases/download/v1/x.exe",  # http not https
        "https://github.com/other-user/boxcutter/releases/download/v1/x.exe",  # wrong owner
        "https://github.com.evil.com/hombreplata-cpu/boxcutter/releases/download/v1/x.exe",
        "file:///C:/Windows/System32/calc.exe",
        "javascript:alert(1)",
        "",
    ],
)
def test_download_update_rejects_non_github_urls(client, evil_url):
    """The download endpoint must reject any URL not starting with the hard-coded prefix.
    This is the ONLY barrier between a client and arbitrary executable download."""
    resp = client.get("/api/download_update", query_string={"url": evil_url})
    assert resp.status_code == 400
    assert "Invalid" in resp.get_json()["error"]


def test_download_update_accepts_valid_github_prefix(client, tmp_path):
    """A URL with the correct prefix must NOT be rejected at the validation gate.
    We don't actually download — we just confirm validation passes by patching urlopen
    to raise immediately, which means we got past the prefix check."""
    valid_url = f"{flask_app.GITHUB_DOWNLOAD_PREFIX}v1.1.0/BoxCutter-Setup-1.1.0.exe"
    with patch("app.urllib.request.urlopen", side_effect=RuntimeError("stub")):
        resp = client.get("/api/download_update", query_string={"url": valid_url})
    # 200 response (SSE stream) — error is reported in the stream body, not status code
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "stub" in body  # the stub error made it into the SSE stream


# ---------------------------------------------------------------------------
# POST /api/apply_update — must reject when no installer is staged
# ---------------------------------------------------------------------------


def test_apply_update_returns_400_when_no_path_staged(client):
    """If no installer has been downloaded, the endpoint must refuse —
    a client cannot supply a path of its own."""
    # Reset state to be safe — other tests may have populated it.
    flask_app._update_state["path"] = None
    resp = client.post("/api/apply_update")
    assert resp.status_code == 400
    assert "No update ready" in resp.get_json()["error"]


def test_apply_update_returns_400_when_staged_path_missing(client, tmp_path):
    """If the path was staged but the file no longer exists on disk, refuse."""
    flask_app._update_state["path"] = str(tmp_path / "does-not-exist.exe")
    resp = client.post("/api/apply_update")
    assert resp.status_code == 400


def test_apply_update_clears_path_after_use(client, tmp_path):
    """One-shot semantics: a staged path must be cleared after the call,
    so a second invocation cannot replay the install."""
    fake_installer = tmp_path / "BoxCutter-Setup-1.1.0.exe"
    fake_installer.write_bytes(b"PK")  # pretend executable
    flask_app._update_state["path"] = str(fake_installer)
    with (
        patch("app.subprocess.Popen"),
        patch("app.threading.Timer"),  # don't actually schedule os._exit
    ):
        resp = client.post("/api/apply_update")
    # First call should succeed (Windows path → Popen + return ok=True)
    # On non-Windows, the path branches to "open" the DMG — assert path is cleared either way
    assert flask_app._update_state["path"] is None
    # Second call must now fail because state is cleared
    resp2 = client.post("/api/apply_update")
    assert resp2.status_code == 400
    # silence unused-var lint
    _ = resp


# ---------------------------------------------------------------------------
# Hard-coded constants — must not drift
# ---------------------------------------------------------------------------


def test_github_releases_url_is_hardcoded_to_canonical_repo():
    """If this URL changes, the auto-updater talks to a different repo. Guard it."""
    assert flask_app.GITHUB_RELEASES_URL == (
        "https://api.github.com/repos/hombreplata-cpu/boxcutter/releases/latest"
    )


def test_github_download_prefix_is_hardcoded_to_canonical_repo():
    """The download allowlist prefix — if this changes, the security boundary moves."""
    assert flask_app.GITHUB_DOWNLOAD_PREFIX == (
        "https://github.com/hombreplata-cpu/boxcutter/releases/download/"
    )
    # And it must end with a slash so prefix matching can't be bypassed by
    # e.g. https://github.com/hombreplata-cpu/boxcutter/releases/download.evil.com/...
    assert flask_app.GITHUB_DOWNLOAD_PREFIX.endswith("/")
