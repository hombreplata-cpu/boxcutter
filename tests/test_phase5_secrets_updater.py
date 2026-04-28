"""
Phase 5 + Phase C tests — secret-key file isolation, updater hardening,
SHA256 verification, ID race fix, crash log uniqueness.

Resolves v1.1 roadmap items S-07, R-03 (cap + SHA verification), R-06,
B-09, B-11.
"""

import hashlib
import json
import os
import sys
import threading
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as flask_app  # noqa: E402
from crash_logger import write_crash_log  # noqa: E402

# ---------------------------------------------------------------------------
# S-07 — secret key file isolation + migration from config
# ---------------------------------------------------------------------------


@pytest.fixture
def secret_env(tmp_path, monkeypatch):
    """Patch SECRET_FILE and CONFIG_FILE to a clean tmp_path; clear init flag."""
    secret = tmp_path / "secret.bin"
    cfg = tmp_path / "config.json"
    monkeypatch.delenv("BOXCUTTER_TESTING", raising=False)
    flask_app._secret_key_initialised = False
    with (
        patch.object(flask_app, "SECRET_FILE", secret),
        patch.object(flask_app, "CONFIG_FILE", cfg),
    ):
        yield secret, cfg
    flask_app._secret_key_initialised = False
    # Restore an ephemeral key so other tests still have a working session signer
    import secrets as _s

    flask_app.app.secret_key = _s.token_bytes(32)


def test_secret_file_used_when_present(secret_env):
    secret_file, cfg_file = secret_env
    key = b"\x42" * 32
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_bytes(key)

    flask_app._init_secret_key()

    assert flask_app.app.secret_key == key


def test_secret_migrated_from_config_to_file(secret_env):
    secret_file, cfg_file = secret_env
    legacy_hex = "ab" * 32
    cfg_file.write_text(json.dumps({"_secret_key": legacy_hex, "db_path": "/x"}))

    flask_app._init_secret_key()

    # Migrated to dedicated file
    assert secret_file.exists()
    assert secret_file.read_bytes() == bytes.fromhex(legacy_hex)
    # Removed from config so future config leaks don't expose it
    with open(cfg_file) as f:
        on_disk = json.load(f)
    assert "_secret_key" not in on_disk
    assert on_disk["db_path"] == "/x"  # other keys preserved


def test_secret_generated_when_no_file_and_no_legacy(secret_env):
    secret_file, _ = secret_env
    flask_app._init_secret_key()
    assert secret_file.exists()
    assert len(secret_file.read_bytes()) == 32


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only permission check")
def test_secret_file_permissions_are_0600(secret_env):
    secret_file, _ = secret_env
    flask_app._init_secret_key()
    mode = secret_file.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0600 perms, got {oct(mode)}"


def test_secret_falls_back_to_ephemeral_when_write_fails(secret_env, monkeypatch):
    """If SECRET_FILE can't be written (read-only home), use ephemeral key."""
    monkeypatch.setattr(flask_app, "_write_secret_file", lambda key: False)
    flask_app._init_secret_key()
    # Key was set even though write failed
    assert isinstance(flask_app.app.secret_key, (bytes, bytearray))
    assert len(flask_app.app.secret_key) == 32


# ---------------------------------------------------------------------------
# R-03 — installer download size cap
# ---------------------------------------------------------------------------


VALID_INSTALLER_URL = flask_app.GITHUB_DOWNLOAD_PREFIX + "v1.1.0/BoxCutter-Setup-1.1.0.exe"
INSTALLER_BASENAME = "BoxCutter-Setup-1.1.0.exe"


def _make_streaming_response(payload_bytes, content_length=None):
    """Build a urlopen-style context-manager mock that yields the given bytes
    in a single read() call, then EOF on subsequent calls."""
    buf = BytesIO(payload_bytes)
    fake = MagicMock()
    fake.headers.get.return_value = (
        str(content_length) if content_length is not None else str(len(payload_bytes))
    )
    fake.read.side_effect = lambda n=-1: buf.read(n)
    fake.__enter__ = MagicMock(return_value=fake)
    fake.__exit__ = MagicMock(return_value=False)
    return fake


def test_download_aborts_at_size_cap(tmp_path):
    """A response stream that exceeds MAX_INSTALLER_BYTES must be aborted."""
    flask_app.app.config["TESTING"] = True

    # Pretend the response is endless: read() returns 1MB chunks forever
    one_mb = b"\x00" * (1024 * 1024)
    fake_resp = MagicMock()
    fake_resp.headers.get.return_value = "0"  # no Content-Length
    fake_resp.read.return_value = one_mb
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    # Pretend SHA verification has a manifest entry — we never reach the
    # final compare because the cap fires first.
    with (
        patch.object(flask_app, "MAX_INSTALLER_BYTES", 5 * 1024 * 1024),
        patch.object(flask_app, "_fetch_expected_sha256", return_value="0" * 64),
        patch("app.urllib.request.urlopen", return_value=fake_resp),
        flask_app.app.test_client() as c,
    ):
        resp = c.get("/api/download_update", query_string={"url": VALID_INSTALLER_URL})
        body = resp.get_data(as_text=True)

    assert "exceeded" in body and "cap" in body, (
        f"Expected oversized abort message in stream, got: {body[:300]}"
    )
    # The state must NOT have been populated with the partial file
    assert flask_app._update_state.get("path") is None


# ---------------------------------------------------------------------------
# R-03 (Phase C) — installer SHA256 verification
# ---------------------------------------------------------------------------


def test_sha_verification_succeeds_on_match():
    """Manifest digest matches streamed payload → download completes, state populated."""
    flask_app.app.config["TESTING"] = True
    flask_app._update_state["path"] = None

    payload = b"\x11" * (256 * 1024)
    expected = hashlib.sha256(payload).hexdigest()

    fake_resp = _make_streaming_response(payload, content_length=len(payload))

    with (
        patch.object(flask_app, "_fetch_expected_sha256", return_value=expected),
        patch("app.urllib.request.urlopen", return_value=fake_resp),
        flask_app.app.test_client() as c,
    ):
        resp = c.get("/api/download_update", query_string={"url": VALID_INSTALLER_URL})
        body = resp.get_data(as_text=True)

    assert "%%DONE%%" in body, f"Expected DONE sentinel, got: {body[-300:]}"
    saved = flask_app._update_state.get("path")
    assert saved is not None and Path(saved).exists()
    Path(saved).unlink(missing_ok=True)
    flask_app._update_state["path"] = None


def test_sha_mismatch_aborts_and_unlinks():
    """Manifest digest does not match streamed payload → unlink, error, no state."""
    flask_app.app.config["TESTING"] = True
    flask_app._update_state["path"] = None

    payload = b"\x22" * (128 * 1024)
    bogus = "f" * 64  # plausibly-shaped but wrong digest

    fake_resp = _make_streaming_response(payload, content_length=len(payload))

    with (
        patch.object(flask_app, "_fetch_expected_sha256", return_value=bogus),
        patch("app.urllib.request.urlopen", return_value=fake_resp),
        flask_app.app.test_client() as c,
    ):
        resp = c.get("/api/download_update", query_string={"url": VALID_INSTALLER_URL})
        body = resp.get_data(as_text=True)

    assert "mismatch" in body.lower(), f"Expected SHA mismatch error, got: {body[-300:]}"
    assert "%%DONE%%" not in body
    assert flask_app._update_state.get("path") is None


def test_missing_manifest_aborts_before_download():
    """If SHA256SUMS can't be fetched / parsed, refuse to download installer at all.
    urlopen must NEVER be called for the installer URL."""
    flask_app.app.config["TESTING"] = True
    flask_app._update_state["path"] = None

    installer_calls = []

    def fake_urlopen(req, **kwargs):
        installer_calls.append(req.full_url if hasattr(req, "full_url") else str(req))
        raise AssertionError("urlopen must not be called when manifest fetch fails")

    with (
        patch.object(flask_app, "_fetch_expected_sha256", return_value=None),
        patch("app.urllib.request.urlopen", side_effect=fake_urlopen),
        flask_app.app.test_client() as c,
    ):
        resp = c.get("/api/download_update", query_string={"url": VALID_INSTALLER_URL})
        body = resp.get_data(as_text=True)

    assert "integrity" in body.lower() or "manifest" in body.lower(), (
        f"Expected integrity/manifest error, got: {body[-300:]}"
    )
    assert "%%DONE%%" not in body
    assert flask_app._update_state.get("path") is None
    assert installer_calls == []


def test_fetch_expected_sha256_parses_standard_format():
    """Parser handles the canonical sha256sum output: '<64hex>  <filename>'."""
    expected = "a" * 64
    manifest = (f"{expected}  BoxCutter-Setup-1.1.0.exe\n{'b' * 64}  boxcutter-mac.dmg\n").encode()

    fake = MagicMock()
    fake.read.return_value = manifest
    fake.__enter__ = MagicMock(return_value=fake)
    fake.__exit__ = MagicMock(return_value=False)

    with patch("app.urllib.request.urlopen", return_value=fake):
        result = flask_app._fetch_expected_sha256(VALID_INSTALLER_URL, INSTALLER_BASENAME)

    assert result == expected


def test_fetch_expected_sha256_rejects_non_github_url():
    """Manifest URL must derive from the locked-down GITHUB_DOWNLOAD_PREFIX."""
    bad_url = "https://evil.example.com/v1.1.0/BoxCutter-Setup-1.1.0.exe"
    result = flask_app._fetch_expected_sha256(bad_url, INSTALLER_BASENAME)
    assert result is None


def test_fetch_expected_sha256_returns_none_when_entry_missing():
    """Manifest fetched OK but our installer's filename isn't listed → None."""
    manifest = (f"{'c' * 64}  some-other-file.exe\n").encode()
    fake = MagicMock()
    fake.read.return_value = manifest
    fake.__enter__ = MagicMock(return_value=fake)
    fake.__exit__ = MagicMock(return_value=False)

    with patch("app.urllib.request.urlopen", return_value=fake):
        result = flask_app._fetch_expected_sha256(VALID_INSTALLER_URL, INSTALLER_BASENAME)

    assert result is None


# ---------------------------------------------------------------------------
# R-06 — crash log filenames don't collide within the same second
# ---------------------------------------------------------------------------


def test_crash_log_filenames_unique_within_same_second(tmp_path, monkeypatch):
    monkeypatch.setattr("crash_logger.LOG_DIR", tmp_path)
    paths = set()
    for _ in range(20):
        p = write_crash_log("test", "body content")
        assert p is not None
        paths.add(str(p))
    # All 20 paths should be unique even though they share the same second timestamp
    assert len(paths) == 20, f"Filename collision: only {len(paths)} unique of 20"


# ---------------------------------------------------------------------------
# B-11 — _is_our_app matches on full path, not bare 'app.py'
# ---------------------------------------------------------------------------


def test_is_our_app_rejects_unrelated_app_py():
    """An unrelated Python project's app.py must not be matched."""
    fake = MagicMock()
    fake.stdout = "/some/other/project/app.py --serve"
    with (
        patch("app.platform.system", return_value="Darwin"),
        patch("app.subprocess.run", return_value=fake),
    ):
        assert flask_app._is_our_app(99999) is False


def test_is_our_app_matches_full_path():
    fake = MagicMock()
    our_path = str(Path(flask_app.__file__).resolve())
    fake.stdout = f"python3 {our_path}"
    with (
        patch("app.platform.system", return_value="Darwin"),
        patch("app.subprocess.run", return_value=fake),
    ):
        assert flask_app._is_our_app(99999) is True


def test_is_our_app_matches_boxcutter_binary():
    """In frozen mode, the process is BoxCutter.exe — match on that."""
    fake = MagicMock()
    fake.stdout = r"C:\Users\Shane\AppData\Local\BoxCutter\BoxCutter.exe"
    with (
        patch("app.platform.system", return_value="Windows"),
        patch("app.subprocess.run", return_value=fake),
    ):
        assert flask_app._is_our_app(99999) is True


# ---------------------------------------------------------------------------
# B-09 — concurrent ID generation does not collide
# ---------------------------------------------------------------------------


def test_id_lock_serialises_max_plus_one():
    """Run 20 threads through a synthetic SELECT MAX → +1 → INSERT block under
    _DB_ID_LOCK and assert no two threads compute the same ID."""
    counter = {"max": 0}
    inserted = []

    def insert_one():
        with flask_app._DB_ID_LOCK:
            current_max = counter["max"]
            time.sleep(0.001)  # widen the race window
            new_id = current_max + 1
            counter["max"] = new_id
            inserted.append(new_id)

    threads = [threading.Thread(target=insert_one) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # No duplicates — lock fully serialises the read-modify-write
    assert sorted(inserted) == list(range(1, 21))
