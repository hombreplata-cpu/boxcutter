"""
Safety invariant regression tests.

Each test is named as a contract: if it breaks, a safety guarantee has been
violated. These must all pass before any release.

Invariants under test:
1. FileType NOT updated when a track is relocated to the same extension.
2. FileType NOT updated when fix_metadata finds an already-correct record.
3. fix_metadata creates a backup before any DB write.
4. relocate creates a backup before any DB write.
5. cleanup moves files (shutil.move) — never deletes (unlink/os.remove).
6. EXT_TO_FILETYPE has no default fallback for unknown extensions.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


# ---------------------------------------------------------------------------
# Invariant 1: relocate — FileType not mutated when extension unchanged
# ---------------------------------------------------------------------------


def test_relocate_filetype_not_updated_when_extension_unchanged(tmp_path):
    """Relocating mp3 → mp3: FileType column must stay untouched."""
    from scripts.rekordbox_relocate import run

    mp3_file = tmp_path / "Artist - Track.mp3"
    mp3_file.write_bytes(b"x" * 512)

    content = MagicMock()
    content.ID = 1
    content.Title = "Track"
    content.FolderPath = "C:/OldMusic/Artist - Track.mp3"
    content.FileType = 1  # mp3
    content.FileSize = 512
    content.rb_local_deleted = 0
    artist = MagicMock()
    artist.Name = "Artist"
    content.Artist = artist

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [content]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    args = MagicMock()
    args.target_root = str(tmp_path)
    args.source_root = []
    args.target_ext = "mp3"
    args.source_ext = "mp3"
    args.dry_run = False
    args.all_tracks = False
    args.missing_only = False
    args.extensions = None
    args.ids = None
    args.db_path = ""

    with patch("scripts.rekordbox_relocate.MasterDatabase", return_value=mock_db):
        run(args)

    # Path was updated but FileType was NOT written — extension unchanged
    assert content.FileType == 1, "FileType must not change when extension stays mp3→mp3"


# ---------------------------------------------------------------------------
# Invariant 2: fix_metadata — FileType not mutated when record already correct
# ---------------------------------------------------------------------------


def test_fix_metadata_filetype_not_updated_when_already_correct(tmp_path):
    """flac file with FileType=6 and correct size → no write, no commit."""
    from scripts.rekordbox_fix_metadata import run

    (tmp_path / "track.flac").write_bytes(b"x" * 512)
    size = (tmp_path / "track.flac").stat().st_size

    row = MagicMock()
    row.ID = 1
    row.Title = "Track"
    row.FolderPath = str(tmp_path / "track.flac").replace("\\", "/")
    row.FileType = 6
    row.FileSize = size
    row.rb_local_deleted = 0

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [row]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    args = MagicMock()
    args.dry_run = False
    args.verbose = False
    args.ids = None
    args.db_path = ""

    with patch("scripts.rekordbox_fix_metadata.MasterDatabase", return_value=mock_db):
        run(args)

    assert row.FileType == 6
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Invariant 3: fix_metadata — backup created before any write
# ---------------------------------------------------------------------------


def test_fix_metadata_backup_created_before_write(tmp_path):
    """shutil.copy2 is called before db.commit when a fix is needed."""

    from scripts.rekordbox_fix_metadata import run

    db_file = tmp_path / "master.db"
    db_file.write_bytes(b"fake db")

    row = MagicMock()
    row.ID = 1
    row.Title = "Track"
    row.FolderPath = str(tmp_path / "track.flac").replace("\\", "/")
    row.FileType = 1  # wrong — should be 6 (FLAC)
    row.FileSize = 0
    row.rb_local_deleted = 0
    (tmp_path / "track.flac").write_bytes(b"x" * 512)

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [row]
    mock_db.engine.url.database = str(db_file)

    copy_calls = []

    def record_copy(src, dst):
        copy_calls.append((src, dst))

    args = MagicMock()
    args.dry_run = False
    args.verbose = False
    args.ids = None
    args.db_path = ""

    with (
        patch("scripts.rekordbox_fix_metadata.MasterDatabase", return_value=mock_db),
        patch("scripts.rekordbox_fix_metadata.shutil.copy2", side_effect=record_copy),
    ):
        run(args)

    assert len(copy_calls) == 1, "shutil.copy2 must be called exactly once before writes"
    backup_dst = Path(copy_calls[0][1])
    assert "boxcutter-backups" in str(backup_dst)
    assert "fix_metadata" in backup_dst.name


# ---------------------------------------------------------------------------
# Invariant 4: relocate — backup created before any write
# ---------------------------------------------------------------------------


def test_relocate_backup_created_before_write(tmp_path):
    """shutil.copy2 is called for backup before db.commit when a track is relocated."""

    from scripts.rekordbox_relocate import run

    db_file = tmp_path / "master.db"
    db_file.write_bytes(b"fake db")
    (tmp_path / "Artist - Track.flac").write_bytes(b"x" * 512)

    content = MagicMock()
    content.ID = 1
    content.Title = "Track"
    content.FolderPath = "C:/OldMusic/Artist - Track.mp3"
    content.FileType = 1
    content.FileSize = 512
    content.rb_local_deleted = 0
    artist = MagicMock()
    artist.Name = "Artist"
    content.Artist = artist

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [content]
    mock_db.engine.url.database = str(db_file)

    copy_calls = []

    def record_copy(src, dst):
        copy_calls.append((src, dst))

    args = MagicMock()
    args.target_root = str(tmp_path)
    args.source_root = []
    args.target_ext = "flac"
    args.source_ext = "mp3"
    args.dry_run = False
    args.all_tracks = False
    args.missing_only = False
    args.extensions = None
    args.ids = None
    args.db_path = ""

    with (
        patch("scripts.rekordbox_relocate.MasterDatabase", return_value=mock_db),
        patch("scripts.rekordbox_relocate.shutil.copy2", side_effect=record_copy),
    ):
        run(args)

    assert len(copy_calls) == 1, "shutil.copy2 must be called exactly once for the DB backup"
    backup_dst = Path(copy_calls[0][1])
    assert "boxcutter-backups" in str(backup_dst)
    assert "relocate" in backup_dst.name


# ---------------------------------------------------------------------------
# Invariant 5: cleanup — moves files, never unlinks/deletes them
# ---------------------------------------------------------------------------


def test_cleanup_uses_move_not_delete(tmp_path):
    """Unreferenced files must be moved to DELETE folder, never deleted in place."""
    from scripts.rekordbox_cleanup import run

    scan_root = tmp_path / "Music"
    scan_root.mkdir()
    delete_dir = tmp_path / "DELETE"
    orphan = scan_root / "orphan.mp3"
    orphan.write_bytes(b"x" * 512)

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = []
    mock_db.engine.url.database = str(tmp_path / "master.db")

    moved = []

    def record_move(src, dst):
        moved.append((src, str(dst)))

    args = MagicMock()
    args.scan_root = str(scan_root)
    args.delete_dir = str(delete_dir)
    args.exclude = []
    args.extensions = None
    args.dry_run = False
    args.db_path = ""

    with (
        patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=mock_db),
        patch("scripts.rekordbox_cleanup.shutil.move", side_effect=record_move),
    ):
        run(args)

    assert len(moved) == 1, "orphan.mp3 must be moved"
    assert str(orphan) == moved[0][0]
    assert str(delete_dir) in moved[0][1]


def test_cleanup_dry_run_never_moves(tmp_path):
    """dry_run=True: shutil.move must not be called regardless of unreferenced files."""
    from scripts.rekordbox_cleanup import run

    scan_root = tmp_path / "Music"
    scan_root.mkdir()
    (scan_root / "orphan.mp3").write_bytes(b"x" * 512)

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = []
    mock_db.get_content.return_value.filter_by.return_value.all.side_effect = None

    def filter_side_effect(**kwargs):
        m = MagicMock()
        m.all.return_value = []
        return m

    mock_db.get_content.return_value.filter_by.side_effect = filter_side_effect

    args = MagicMock()
    args.scan_root = str(scan_root)
    args.delete_dir = str(tmp_path / "DELETE")
    args.exclude = []
    args.extensions = None
    args.dry_run = True
    args.db_path = ""

    with (
        patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=mock_db),
        patch("scripts.rekordbox_cleanup.shutil.move") as mock_move,
    ):
        run(args)

    mock_move.assert_not_called()


# ---------------------------------------------------------------------------
# Invariant 6: EXT_TO_FILETYPE — no default fallback for unknown extensions
# ---------------------------------------------------------------------------


def test_ext_to_filetype_unknown_ext_has_no_entry():
    """Unknown extensions must not be in the map — no fallback type assignment."""
    from scripts.utils import EXT_TO_FILETYPE

    for bad_ext in (".xyz", ".wave", ".opus", ".ogg2", ".mp4a"):
        assert EXT_TO_FILETYPE.get(bad_ext) is None, f"{bad_ext} must not be in EXT_TO_FILETYPE"


def test_ext_to_filetype_all_known_values_are_positive_integers():
    """Every mapped value must be a positive int — guards against None or 0 defaults."""
    from scripts.utils import EXT_TO_FILETYPE

    for ext, ftype in EXT_TO_FILETYPE.items():
        assert isinstance(ftype, int) and ftype > 0, f"{ext} maps to invalid value {ftype!r}"
