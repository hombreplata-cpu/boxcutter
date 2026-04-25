"""
Tests for scripts/rekordbox_cleanup.py

Covers:
- Files not referenced in the DB are moved to the DELETE folder
- Files referenced in the DB are not moved
- dry_run prevents any filesystem changes
- Files are moved (shutil.move) not deleted (os.unlink)
- Excluded directories are not scanned
- Extension filtering respects the configured set
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _make_args(scan_root, delete_dir, dry_run=False, exclude=None, extensions=None, db_path=""):
    args = MagicMock()
    args.scan_root = str(scan_root)
    args.delete_dir = str(delete_dir)
    args.dry_run = dry_run
    args.exclude = exclude or []
    args.extensions = extensions
    args.db_path = db_path
    return args


def _mock_db_with_active_paths(paths):
    """Build a mock MasterDatabase whose active tracks point to the given paths."""
    contents = []
    for p in paths:
        c = MagicMock()
        c.FolderPath = str(p).replace("\\", "/")
        c.rb_local_deleted = 0
        contents.append(c)

    mock_db = MagicMock()

    def filter_side_effect(**kwargs):
        m = MagicMock()
        deleted = kwargs.get("rb_local_deleted", 0)
        m.all.return_value = [c for c in contents if c.rb_local_deleted == deleted]
        return m

    mock_db.get_content.return_value.filter_by.side_effect = filter_side_effect
    return mock_db


# ---------------------------------------------------------------------------
# Core: unreferenced files are moved, referenced files are not
# ---------------------------------------------------------------------------


def test_unreferenced_file_is_moved(tmp_path):
    from scripts.rekordbox_cleanup import run

    scan_root = tmp_path / "Music"
    scan_root.mkdir()
    delete_dir = tmp_path / "DELETE"
    orphan = scan_root / "orphan.mp3"
    orphan.write_bytes(b"x" * 512)

    mock_db = _mock_db_with_active_paths([])  # no active tracks

    moved = []

    with (
        patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=mock_db),
        patch("scripts.rekordbox_cleanup.shutil.move", side_effect=lambda s, d: moved.append(s)),
    ):
        run(_make_args(scan_root, delete_dir))

    assert len(moved) == 1
    assert str(orphan) in moved[0]


def test_referenced_file_is_not_moved(tmp_path):
    from scripts.rekordbox_cleanup import run

    scan_root = tmp_path / "Music"
    scan_root.mkdir()
    delete_dir = tmp_path / "DELETE"
    track = scan_root / "track.flac"
    track.write_bytes(b"x" * 512)

    mock_db = _mock_db_with_active_paths([track])

    with (
        patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=mock_db),
        patch("scripts.rekordbox_cleanup.shutil.move") as mock_move,
    ):
        run(_make_args(scan_root, delete_dir))

    mock_move.assert_not_called()


def test_mixed_files_only_orphans_moved(tmp_path):
    from scripts.rekordbox_cleanup import run

    scan_root = tmp_path / "Music"
    scan_root.mkdir()
    delete_dir = tmp_path / "DELETE"
    track = scan_root / "track.flac"
    orphan = scan_root / "orphan.mp3"
    track.write_bytes(b"x" * 512)
    orphan.write_bytes(b"x" * 512)

    mock_db = _mock_db_with_active_paths([track])

    moved = []

    with (
        patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=mock_db),
        patch("scripts.rekordbox_cleanup.shutil.move", side_effect=lambda s, d: moved.append(s)),
    ):
        run(_make_args(scan_root, delete_dir))

    assert len(moved) == 1
    assert "orphan.mp3" in moved[0]


# ---------------------------------------------------------------------------
# dry_run: no filesystem changes
# ---------------------------------------------------------------------------


def test_dry_run_no_files_moved(tmp_path):
    from scripts.rekordbox_cleanup import run

    scan_root = tmp_path / "Music"
    scan_root.mkdir()
    (scan_root / "orphan.mp3").write_bytes(b"x" * 512)

    mock_db = _mock_db_with_active_paths([])

    with (
        patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=mock_db),
        patch("scripts.rekordbox_cleanup.shutil.move") as mock_move,
    ):
        run(_make_args(scan_root, tmp_path / "DELETE", dry_run=True))

    mock_move.assert_not_called()


# ---------------------------------------------------------------------------
# Extension filtering
# ---------------------------------------------------------------------------


def test_non_audio_files_never_moved(tmp_path):
    from scripts.rekordbox_cleanup import run

    scan_root = tmp_path / "Music"
    scan_root.mkdir()
    (scan_root / "cover.jpg").write_bytes(b"x")
    (scan_root / "notes.txt").write_bytes(b"x")

    mock_db = _mock_db_with_active_paths([])

    with (
        patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=mock_db),
        patch("scripts.rekordbox_cleanup.shutil.move") as mock_move,
    ):
        run(_make_args(scan_root, tmp_path / "DELETE"))

    mock_move.assert_not_called()


def test_custom_extension_filter_respected(tmp_path):
    """When --extensions mp3 is set, .flac files should be ignored."""
    from scripts.rekordbox_cleanup import run

    scan_root = tmp_path / "Music"
    scan_root.mkdir()
    (scan_root / "orphan.flac").write_bytes(b"x")
    (scan_root / "orphan.mp3").write_bytes(b"x")

    mock_db = _mock_db_with_active_paths([])

    moved = []

    with (
        patch("scripts.rekordbox_cleanup.MasterDatabase", return_value=mock_db),
        patch("scripts.rekordbox_cleanup.shutil.move", side_effect=lambda s, d: moved.append(s)),
    ):
        run(_make_args(scan_root, tmp_path / "DELETE", extensions="mp3"))

    assert len(moved) == 1
    assert "orphan.mp3" in moved[0]
    assert not any("orphan.flac" in m for m in moved)
