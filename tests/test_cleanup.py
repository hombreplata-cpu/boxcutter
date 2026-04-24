"""
Tests for scripts/rekordbox_cleanup.py

Covers the core safety invariants:
- Unreferenced audio files are moved to the DELETE folder
- Active (DB-referenced) files are never touched
- Subfolder structure is preserved inside DELETE
- Non-audio files are ignored regardless
- Dry run reports what would move but moves nothing
- DELETE folder is created if it doesn't exist
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.rekordbox_cleanup import run  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(scan_root, delete_dir, dry_run=False, extensions=None, exclude=None, db_path=""):
    args = MagicMock()
    args.scan_root = str(scan_root)
    args.delete_dir = str(delete_dir)
    args.dry_run = dry_run
    args.extensions = extensions
    args.exclude = exclude or []
    args.db_path = db_path
    return args


def _mock_db_with_paths(paths):
    """Return a mock DB whose active tracks reference exactly `paths`."""
    contents = []
    for p in paths:
        c = MagicMock()
        c.FolderPath = str(p).replace("\\", "/")
        c.rb_local_deleted = 0
        contents.append(c)

    db = MagicMock()
    db.get_content.return_value.filter_by.return_value.all.return_value = contents
    return db


# ---------------------------------------------------------------------------
# Core move behaviour
# ---------------------------------------------------------------------------


def test_unreferenced_file_is_moved(tmp_path):
    scan_root = tmp_path / "music"
    delete_dir = tmp_path / "DELETE"
    scan_root.mkdir()

    orphan = scan_root / "orphan.flac"
    orphan.write_bytes(b"x" * 512)

    db = _mock_db_with_paths([])  # nothing in DB → file is unreferenced

    with patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=db):
        run(_make_args(scan_root, delete_dir))

    assert not orphan.exists(), "Unreferenced file should have been moved"
    assert (delete_dir / "orphan.flac").exists(), "File should appear in DELETE folder"


def test_active_file_is_not_moved(tmp_path):
    scan_root = tmp_path / "music"
    delete_dir = tmp_path / "DELETE"
    scan_root.mkdir()

    active = scan_root / "active_track.flac"
    active.write_bytes(b"x" * 512)

    db = _mock_db_with_paths([active])

    with patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=db):
        run(_make_args(scan_root, delete_dir))

    assert active.exists(), "Active (DB-referenced) file must not be moved"
    assert not delete_dir.exists() or not (delete_dir / "active_track.flac").exists()


def test_subfolder_structure_preserved_in_delete(tmp_path):
    scan_root = tmp_path / "music"
    delete_dir = tmp_path / "DELETE"
    sub = scan_root / "House" / "Deep"
    sub.mkdir(parents=True)

    orphan = sub / "deep_track.mp3"
    orphan.write_bytes(b"x" * 512)

    db = _mock_db_with_paths([])

    with patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=db):
        run(_make_args(scan_root, delete_dir))

    assert (delete_dir / "House" / "Deep" / "deep_track.mp3").exists()


def test_non_audio_files_never_moved(tmp_path):
    scan_root = tmp_path / "music"
    delete_dir = tmp_path / "DELETE"
    scan_root.mkdir()

    jpg = scan_root / "cover.jpg"
    txt = scan_root / "notes.txt"
    jpg.write_bytes(b"img")
    txt.write_bytes(b"text")

    db = _mock_db_with_paths([])

    with patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=db):
        run(_make_args(scan_root, delete_dir))

    assert jpg.exists()
    assert txt.exists()


def test_delete_dir_created_if_missing(tmp_path):
    scan_root = tmp_path / "music"
    delete_dir = tmp_path / "nested" / "DELETE"
    scan_root.mkdir()

    orphan = scan_root / "orphan.wav"
    orphan.write_bytes(b"x")

    db = _mock_db_with_paths([])

    with patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=db):
        run(_make_args(scan_root, delete_dir))

    assert delete_dir.exists()


def test_mixed_files_only_unreferenced_moved(tmp_path):
    scan_root = tmp_path / "music"
    delete_dir = tmp_path / "DELETE"
    scan_root.mkdir()

    active = scan_root / "keep.flac"
    orphan = scan_root / "remove.flac"
    active.write_bytes(b"a" * 512)
    orphan.write_bytes(b"b" * 512)

    db = _mock_db_with_paths([active])

    with patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=db):
        run(_make_args(scan_root, delete_dir))

    assert active.exists()
    assert not orphan.exists()
    assert (delete_dir / "remove.flac").exists()


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_dry_run_moves_nothing(tmp_path):
    scan_root = tmp_path / "music"
    delete_dir = tmp_path / "DELETE"
    scan_root.mkdir()

    orphan = scan_root / "orphan.mp3"
    orphan.write_bytes(b"x" * 512)

    db = _mock_db_with_paths([])

    with patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=db):
        run(_make_args(scan_root, delete_dir, dry_run=True))

    assert orphan.exists(), "Dry run must not move files"
    assert not (delete_dir / "orphan.mp3").exists()


def test_dry_run_with_active_file_touches_nothing(tmp_path):
    scan_root = tmp_path / "music"
    delete_dir = tmp_path / "DELETE"
    scan_root.mkdir()

    active = scan_root / "active.flac"
    active.write_bytes(b"x")

    db = _mock_db_with_paths([active])

    with patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=db):
        run(_make_args(scan_root, delete_dir, dry_run=True))

    assert active.exists()


# ---------------------------------------------------------------------------
# Collision handling — dest file already exists
# ---------------------------------------------------------------------------


def test_collision_renamed_not_overwritten(tmp_path):
    scan_root = tmp_path / "music"
    delete_dir = tmp_path / "DELETE"
    scan_root.mkdir()
    delete_dir.mkdir()

    orphan = scan_root / "track.flac"
    orphan.write_bytes(b"new")

    existing = delete_dir / "track.flac"
    existing.write_bytes(b"old")

    db = _mock_db_with_paths([])

    with patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=db):
        run(_make_args(scan_root, delete_dir))

    assert existing.exists(), "Original DELETE file must not be overwritten"
    # The new file should exist under a suffixed name
    renamed = delete_dir / "track-1.flac"
    assert renamed.exists(), "Colliding file should be moved as track-1.flac"
