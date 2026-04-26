import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Set before app is imported so the lazy secret-key writer short-circuits.
# Prevents test runs from persisting a session key into a real config file
# and prevents the secret_key from polluting allowlist tests.
os.environ.setdefault("BOXCUTTER_TESTING", "1")

# tests/ dir — makes helpers.py importable from test modules.
sys.path.insert(0, str(Path(__file__).parent))
# Repo root — needed by test_app.py and any test that imports app directly.
sys.path.insert(0, str(Path(__file__).parent.parent))
# Make scripts/ importable as a flat namespace (needed for `from utils import …`
# inside scripts when they are imported as `scripts.rekordbox_xxx` in tests).
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Stub out pyrekordbox before any script imports it.
# pyrekordbox has Windows-specific C extensions (anlz) that are unavailable
# in the CI ubuntu runner used by the Security/Lint jobs. All DB calls in
# tests are mocked anyway, so the real package is never needed at test time.
_pyrekordbox_stub = MagicMock()
sys.modules.setdefault("pyrekordbox", _pyrekordbox_stub)
sys.modules.setdefault("pyrekordbox.db6", _pyrekordbox_stub)
sys.modules.setdefault("pyrekordbox.db6.tables", MagicMock())
sys.modules.setdefault("pyrekordbox.db6.smartlist", MagicMock())
sys.modules.setdefault("pyrekordbox.anlz", _pyrekordbox_stub)


@pytest.fixture
def audio_dir(tmp_path):
    """Temp directory with stub audio files of multiple formats."""
    pairs = [
        ("Artist - Track", "flac"),
        ("Artist - Track", "wav"),
        ("Artist - Track", "alac"),
        ("Artist - Track", "mp3"),
        ("Other Song", "flac"),
        ("Other Song", "wav"),
    ]
    for stem, ext in pairs:
        f = tmp_path / f"{stem}.{ext}"
        f.write_bytes(b"x" * 1024)
    return tmp_path


def make_mock_content(folder_path="C:/Music/MP3/Artist - Track.mp3", file_type=1, file_size=512):
    c = MagicMock()
    c.ID = 1
    c.Title = "Track"
    c.FolderPath = folder_path
    c.FileType = file_type
    c.FileSize = file_size
    c.rb_local_deleted = 0
    artist = MagicMock()
    artist.Name = "Artist"
    c.Artist = artist
    return c


@pytest.fixture
def mock_content():
    return make_mock_content()


@pytest.fixture
def mock_db(tmp_path, mock_content):
    db = MagicMock()
    db.get_content.return_value.filter_by.return_value.all.return_value = [mock_content]
    db.engine.url.database = str(tmp_path / "master.db")
    return db


@pytest.fixture
def flask_client(tmp_path):
    """Flask test client with a fully configured mock config (db_path set)."""
    from unittest.mock import patch

    import app as flask_app

    flask_app.app.config["TESTING"] = True
    cfg = {
        "db_path": "/fake/master.db",
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
        yield c


@pytest.fixture
def flask_client_no_paths(tmp_path):
    """Flask test client: db_path set, but all other path fields empty.

    Use for tests that check the app returns 400 when a required path param
    is absent and there is no config fallback to hide the missing field.
    """
    from unittest.mock import patch

    import app as flask_app

    flask_app.app.config["TESTING"] = True
    cfg = {
        "db_path": "/fake/master.db",
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
def flask_client_no_db(tmp_path):
    """Flask test client where db_path is intentionally absent."""
    from unittest.mock import patch

    import app as flask_app

    flask_app.app.config["TESTING"] = True
    cfg = {
        "db_path": "",
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
        yield c
