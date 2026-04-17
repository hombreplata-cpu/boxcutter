"""
Tests for scripts/rekordbox_fix_metadata.py

Covers:
- EXT_TO_FILETYPE correctness
- WAV files get FileType=5 (never 6)
- Unknown extensions are skipped (not assigned FLAC type 6)
- ALAC gets FileType=11
- dry_run does not commit
- Already-correct tracks are not modified
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.rekordbox_fix_metadata import EXT_TO_FILETYPE, run  # noqa: E402

# ---------------------------------------------------------------------------
# EXT_TO_FILETYPE map
# ---------------------------------------------------------------------------


def test_wav_maps_to_5():
    assert EXT_TO_FILETYPE[".wav"] == 5


def test_flac_maps_to_6():
    assert EXT_TO_FILETYPE[".flac"] == 6


def test_alac_maps_to_11():
    assert EXT_TO_FILETYPE[".alac"] == 11


def test_mp3_maps_to_1():
    assert EXT_TO_FILETYPE[".mp3"] == 1


def test_unknown_ext_not_in_map():
    """Unknown extensions must NOT be in the map to avoid defaulting to FLAC (6)."""
    assert EXT_TO_FILETYPE.get(".xyz") is None
    assert EXT_TO_FILETYPE.get(".wave") is None
    assert EXT_TO_FILETYPE.get(".alac2") is None


# ---------------------------------------------------------------------------
# run() integration helpers
# ---------------------------------------------------------------------------


def _make_args(dry_run=False, verbose=False, ids=None, db_path=""):
    args = MagicMock()
    args.dry_run = dry_run
    args.verbose = verbose
    args.ids = ids
    args.db_path = db_path
    return args


def _make_row(tmp_path, filename, file_type, file_size=None):
    fpath = tmp_path / filename
    fpath.write_bytes(b"x" * (file_size or 512))
    row = MagicMock()
    row.ID = 1
    row.Title = filename
    row.FolderPath = str(fpath).replace("\\", "/")
    row.FileType = file_type
    row.FileSize = file_size or 512
    row.rb_local_deleted = 0
    return row


# ---------------------------------------------------------------------------
# run() integration — WAV stays WAV
# ---------------------------------------------------------------------------


def test_wav_file_gets_filetype_5_when_db_has_wrong_type(tmp_path):
    """WAV file on disk with wrong FileType in DB → fixed to 5."""
    row = _make_row(tmp_path, "track.wav", file_type=6, file_size=0)
    actual_size = (tmp_path / "track.wav").stat().st_size

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [row]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    with patch("scripts.rekordbox_fix_metadata.MasterDatabase", return_value=mock_db):
        run(_make_args())

    assert row.FileType == 5
    assert row.FileSize == actual_size


def test_wav_file_correct_type_not_modified(tmp_path):
    """WAV with FileType=5 and correct size → not touched, commit not called."""
    (tmp_path / "track.wav").write_bytes(b"x" * 512)
    size = (tmp_path / "track.wav").stat().st_size
    row = _make_row(tmp_path, "track.wav", file_type=5, file_size=size)
    row.FileSize = size

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [row]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    original_type = row.FileType

    with patch("scripts.rekordbox_fix_metadata.MasterDatabase", return_value=mock_db):
        run(_make_args())

    assert row.FileType == original_type
    mock_db.commit.assert_not_called()


def test_wav_never_assigned_flac_type(tmp_path):
    """WAV file must never have FileType set to 6 (FLAC) under any condition."""
    row = _make_row(tmp_path, "track.wav", file_type=99, file_size=0)

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [row]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    with patch("scripts.rekordbox_fix_metadata.MasterDatabase", return_value=mock_db):
        run(_make_args())

    assert row.FileType != 6, "WAV file must not be assigned FLAC type (6)"
    assert row.FileType == 5


# ---------------------------------------------------------------------------
# run() integration — ALAC gets 11
# ---------------------------------------------------------------------------


def test_alac_file_gets_filetype_11(tmp_path):
    """ALAC file on disk with wrong FileType → fixed to 11."""
    row = _make_row(tmp_path, "track.alac", file_type=6, file_size=0)

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [row]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    with patch("scripts.rekordbox_fix_metadata.MasterDatabase", return_value=mock_db):
        run(_make_args())

    assert row.FileType == 11


# ---------------------------------------------------------------------------
# run() integration — unknown extension skipped
# ---------------------------------------------------------------------------


def test_unknown_ext_skipped_not_assigned_flac(tmp_path):
    """File with unknown extension is skipped — FileType must NOT become 6."""
    row = _make_row(tmp_path, "track.xyz", file_type=6, file_size=0)
    original_type = row.FileType

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [row]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    with patch("scripts.rekordbox_fix_metadata.MasterDatabase", return_value=mock_db):
        run(_make_args())

    # row.FileType should not have been set at all (skipped)
    assert row.FileType == original_type


# ---------------------------------------------------------------------------
# run() integration — dry_run behaviour
# ---------------------------------------------------------------------------


def test_dry_run_does_not_commit(tmp_path):
    """dry_run=True → db.commit() never called even when changes detected."""
    row = _make_row(tmp_path, "track.flac", file_type=1, file_size=0)

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [row]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    with patch("scripts.rekordbox_fix_metadata.MasterDatabase", return_value=mock_db):
        run(_make_args(dry_run=True))

    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# run() integration — missing file
# ---------------------------------------------------------------------------


def test_missing_file_counted_not_fixed(tmp_path):
    """Track whose file doesn't exist on disk is counted missing, not fixed."""
    row = MagicMock()
    row.ID = 1
    row.Title = "Ghost Track"
    row.FolderPath = "/nonexistent/path/track.flac"
    row.FileType = 6
    row.FileSize = 1000
    original_type = row.FileType

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [row]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    with patch("scripts.rekordbox_fix_metadata.MasterDatabase", return_value=mock_db):
        run(_make_args())

    assert row.FileType == original_type
    mock_db.commit.assert_not_called()
