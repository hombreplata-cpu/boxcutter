import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

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
