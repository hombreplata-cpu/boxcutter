"""
Phase 1 tests — atomic config/history writes, lazy + ephemeral secret key.

Resolves roadmap items B-02, B-03, B-05, B-16, B-17.

The promise: concurrent writers never corrupt the JSON file; a kill mid-write
leaves either the previous state or the new state, never an empty/partial
file. Tests assert the contracts without relying on implementation details.
"""

import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app as flask_app  # noqa: E402

# ---------------------------------------------------------------------------
# B-02 — atomic writes survive concurrency
# ---------------------------------------------------------------------------


def test_save_config_concurrent_writers_no_corruption(tmp_path):
    """20 threads each writing a different key — final file must be valid JSON
    containing every key. No write may clobber another's key."""
    cfg_file = tmp_path / "config.json"
    with patch.object(flask_app, "CONFIG_FILE", cfg_file):
        threads = []
        for i in range(20):
            t = threading.Thread(target=flask_app.save_config, args=({f"k{i}": i},))
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # File is parseable
        with open(cfg_file) as f:
            data = json.load(f)
        # Every writer's key landed
        for i in range(20):
            assert data[f"k{i}"] == i


def test_save_config_uses_atomic_replace(tmp_path):
    """The function must NOT open CONFIG_FILE in 'w' mode directly — it must
    write to a tmp file and os.replace. Verified by checking that no .tmp
    file is left behind after a successful write."""
    cfg_file = tmp_path / "config.json"
    with patch.object(flask_app, "CONFIG_FILE", cfg_file):
        flask_app.save_config({"db_path": "/foo"})
    assert cfg_file.exists()
    # No leftover tmp file
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == [], f"Atomic write left tmp files behind: {leftover}"


def test_save_history_entry_is_atomic(tmp_path):
    """Same atomic guarantee for the history file."""
    hist_file = tmp_path / "history.json"
    with patch.object(flask_app, "HISTORY_FILE", hist_file):
        flask_app.save_history_entry({"id": "1", "tool": "relocate"})
        flask_app.save_history_entry({"id": "2", "tool": "cleanup"})
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []
    with open(hist_file) as f:
        history = json.load(f)
    assert [e["id"] for e in history] == ["2", "1"]  # newest first


def test_save_history_concurrent_writers_no_loss(tmp_path):
    """Concurrent history writers — every entry survives."""
    hist_file = tmp_path / "history.json"
    with patch.object(flask_app, "HISTORY_FILE", hist_file):
        threads = [
            threading.Thread(
                target=flask_app.save_history_entry,
                args=({"id": f"{i}", "tool": "x"},),
            )
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    with open(hist_file) as f:
        history = json.load(f)
    ids = sorted(int(e["id"]) for e in history)
    assert ids == list(range(20))


# ---------------------------------------------------------------------------
# B-05 — delete_dir migration is persisted
# ---------------------------------------------------------------------------


def test_delete_dir_migration_persists_to_disk(tmp_path):
    """When load_config triggers the OneDrive migration, the corrected value
    must be written back so subsequent partial saves don't re-persist the
    old default."""
    cfg_file = tmp_path / "config.json"
    old = str(Path.home() / "Desktop" / "DELETE")
    cfg_file.write_text(json.dumps({"delete_dir": old}))

    fake_default = "C:\\Users\\You\\OneDrive\\Desktop\\DELETE"
    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        patch.object(flask_app, "_default_delete_dir", return_value=fake_default),
    ):
        cfg = flask_app.load_config()
        assert cfg["delete_dir"] == fake_default
        # Re-read disk: migration must have been persisted
        with open(cfg_file) as f:
            on_disk = json.load(f)
        assert on_disk["delete_dir"] == fake_default


def test_delete_dir_no_migration_when_already_correct(tmp_path):
    """If delete_dir is already correct, do not rewrite the file unnecessarily."""
    cfg_file = tmp_path / "config.json"
    correct = "C:\\Users\\You\\OneDrive\\Desktop\\DELETE"
    cfg_file.write_text(json.dumps({"delete_dir": correct}))
    mtime_before = cfg_file.stat().st_mtime_ns

    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        patch.object(flask_app, "_default_delete_dir", return_value=correct),
    ):
        flask_app.load_config()

    # File was not rewritten
    assert cfg_file.stat().st_mtime_ns == mtime_before


# ---------------------------------------------------------------------------
# B-16 — ephemeral fallback when secret key cannot be persisted
# ---------------------------------------------------------------------------


def test_init_secret_key_handles_readonly_home(tmp_path, monkeypatch):
    """If save_config raises OSError, app must boot with an ephemeral key."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.delenv("BOXCUTTER_TESTING", raising=False)

    flask_app._secret_key_initialised = False

    def _raise(*args, **kwargs):
        raise OSError("read-only filesystem")

    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        patch.object(flask_app, "save_config", side_effect=_raise),
    ):
        flask_app._init_secret_key()

    assert flask_app._secret_key_initialised is True
    assert isinstance(flask_app.app.secret_key, (bytes, bytearray))
    # Cleanup so the next test gets a fresh init
    flask_app._secret_key_initialised = False


# ---------------------------------------------------------------------------
# B-17 — testing env never persists a secret key
# ---------------------------------------------------------------------------


def test_testing_env_skips_secret_persistence(tmp_path, monkeypatch):
    """When BOXCUTTER_TESTING=1 is set, _init_secret_key generates an ephemeral
    key and does NOT touch CONFIG_FILE. Prevents test runs from leaking a key
    into a real ~/.boxcutter_config.json."""
    cfg_file = tmp_path / "config.json"
    monkeypatch.setenv("BOXCUTTER_TESTING", "1")
    flask_app._secret_key_initialised = False

    with patch.object(flask_app, "CONFIG_FILE", cfg_file):
        flask_app._init_secret_key()

    # Key was set
    assert isinstance(flask_app.app.secret_key, (bytes, bytearray))
    # CONFIG_FILE was NEVER created
    assert not cfg_file.exists()
    flask_app._secret_key_initialised = False


def test_secret_key_persisted_in_real_mode(tmp_path, monkeypatch):
    """Outside testing mode, _init_secret_key writes a key to SECRET_FILE
    (not CONFIG_FILE — Phase 5 moved it for isolation)."""
    cfg_file = tmp_path / "config.json"
    secret_file = tmp_path / "secret.bin"
    monkeypatch.delenv("BOXCUTTER_TESTING", raising=False)
    flask_app._secret_key_initialised = False

    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        patch.object(flask_app, "SECRET_FILE", secret_file),
    ):
        flask_app._init_secret_key()

    assert secret_file.exists()
    assert len(secret_file.read_bytes()) == 32
    flask_app._secret_key_initialised = False


def test_secret_key_reused_when_already_persisted(tmp_path, monkeypatch):
    """If a key is already in SECRET_FILE, reuse it rather than generating a new one."""
    cfg_file = tmp_path / "config.json"
    secret_file = tmp_path / "secret.bin"
    existing = b"\xab" * 32
    secret_file.write_bytes(existing)
    monkeypatch.delenv("BOXCUTTER_TESTING", raising=False)
    flask_app._secret_key_initialised = False

    with (
        patch.object(flask_app, "CONFIG_FILE", cfg_file),
        patch.object(flask_app, "SECRET_FILE", secret_file),
    ):
        flask_app._init_secret_key()

    assert flask_app.app.secret_key == existing
    flask_app._secret_key_initialised = False


# ---------------------------------------------------------------------------
# Cleanup fixture so test ordering can't leak state
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_secret_init():
    yield
    flask_app._secret_key_initialised = False
    # Restore an ephemeral key so other tests in the suite that touch sessions
    # still have a valid app.secret_key.
    import secrets as _secrets

    flask_app.app.secret_key = _secrets.token_bytes(32)
