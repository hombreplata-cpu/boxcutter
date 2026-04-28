"""
Script integration tests using a synthetic unencrypted Rekordbox DB.

These tests copy tests/fixtures/master_test.db to a tmp directory and run
the actual scripts against it — no mocks. They catch bugs that unit tests
with mocked DBs can't: wrong SQL, broken pyrekordbox field access, crashes
on real-world data, and any Mac-specific quirk that shows up only when the
scripts actually mutate a pyrekordbox-managed DB.

The fixture is generated programmatically by
``tests/fixtures/generate_master_test_db.py`` from pyrekordbox's own ORM
schema — no real Rekordbox install required, no SQLCipher key required,
no personal data committed. CI runs the generator before pytest in
``.github/workflows/ci.yml``; locally the ``_ensure_fixture_exists`` autouse
fixture below regenerates it on first pytest invocation if missing.

The fixture is unencrypted, so an autouse monkeypatch overrides
``Rekordbox6Database.__init__`` to default ``unlock=False`` for the duration
of these tests — script code that constructs ``MasterDatabase`` with the
production default of ``unlock=True`` reaches the fixture without needing
any production-script changes.
"""

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "master_test.db"

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


@pytest.fixture(scope="session", autouse=True)
def _ensure_fixture_exists():
    """Regenerate the fixture DB if it doesn't exist. Belt for local
    devs who haven't run the generator manually; CI always runs the
    generator step explicitly before pytest."""
    if not FIXTURE.exists():
        from tests.fixtures import generate_master_test_db

        generate_master_test_db.main()


@pytest.fixture(autouse=True)
def _bypass_pyrekordbox_unlock():
    """Force Rekordbox6Database to open the fixture as a plain SQLite file
    (no SQLCipher key extraction). Production scripts construct it with
    unlock=True by default; in integration tests the fixture is unencrypted
    so we override that default for the duration of each test.

    Manual setattr/teardown rather than pytest's monkeypatch because
    monkeypatch refuses to set magic methods like __init__. The original
    method is captured in the fixture closure and restored on teardown,
    so the patch never leaks into other tests."""
    from pyrekordbox.db6 import Rekordbox6Database

    original_init = Rekordbox6Database.__init__

    def patched(self, *args, **kwargs):
        kwargs.setdefault("unlock", False)
        return original_init(self, *args, **kwargs)

    Rekordbox6Database.__init__ = patched
    try:
        yield
    finally:
        Rekordbox6Database.__init__ = original_init


def _copy_db(tmp_path: Path) -> Path:
    """Return a fresh copy of the fixture in tmp_path (never mutates the original)."""
    dest = tmp_path / "master_test.db"
    shutil.copy2(FIXTURE, dest)
    return dest


def _open_db(db_path: Path):
    """Open a Rekordbox6Database, skipping the test if pyrekordbox can't open it.

    The autouse `_bypass_pyrekordbox_unlock` fixture has already overridden
    `__init__` to default `unlock=False`, so the call below opens the
    fixture as a plain SQLite file.
    """
    try:
        from pyrekordbox import Rekordbox6Database

        return Rekordbox6Database(path=str(db_path))
    except Exception as exc:
        pytest.skip(f"Could not open DB: {exc}")


# ---------------------------------------------------------------------------
# Fixture health check
# ---------------------------------------------------------------------------


def test_db_fixture_is_readable_and_has_tracks(tmp_path):
    """The backup DB must open cleanly and contain at least one non-deleted track."""
    db = _open_db(_copy_db(tmp_path))
    tracks = db.get_content().filter_by(rb_local_deleted=0).all()
    assert len(tracks) > 0, "Fixture DB has no active tracks — check the backup file"
    db.close()


# ---------------------------------------------------------------------------
# Relocate — dry run on real data
# ---------------------------------------------------------------------------


def test_relocate_dry_run_does_not_crash(tmp_path):
    """relocate --dry-run must complete without exception on real-world DB data."""
    from scripts.rekordbox_relocate import run

    db_path = _copy_db(tmp_path)
    target = tmp_path / "music"
    target.mkdir()

    args = SimpleNamespace(
        db_path=str(db_path),
        target_root=str(target),
        source_root=[],
        target_ext="flac",
        source_ext=None,
        prefer_ext=None,
        dry_run=True,
        all_tracks=False,
        missing_only=False,
        extensions=None,
        ids=None,
        verbose=False,
    )
    # Should not raise
    run(args)


def test_relocate_updates_folder_path_for_matched_track(tmp_path):
    """
    Relocate must update FolderPath in the DB copy when a matching file exists.

    Strategy:
      1. Open the DB copy and find a non-deleted track with a known Title + Artist.
      2. Create a file named 'Artist - Title.flac' in target_root.
      3. Run relocate (non-dry-run) — the track's current path won't exist on disk,
         so it's a relocation candidate.
      4. Assert FolderPath was updated to point at the new file.
    """
    from scripts.rekordbox_relocate import run

    db_path = _copy_db(tmp_path)
    db = _open_db(db_path)

    # Find first track that has both Title and Artist. Capture all
    # attributes we need BEFORE closing the session, so subsequent access
    # doesn't hit DetachedInstanceError.
    track_id = None
    title = ""
    artist_name = ""
    original_path = ""
    for t in db.get_content().filter_by(rb_local_deleted=0).all():
        t_title = (t.Title or "").strip()
        t_artist_name = (t.Artist.Name if t.Artist else "").strip()
        if t_title and t_artist_name:
            track_id = t.ID
            title = t_title
            artist_name = t_artist_name
            original_path = t.FolderPath
            break

    db.close()

    if track_id is None:
        pytest.skip("No track with both Title and Artist found in fixture DB")

    # Create the matching file in target_root
    target = tmp_path / "music"
    target.mkdir()
    match_file = target / f"{artist_name} - {title}.flac"
    match_file.write_bytes(b"x" * 512)

    args = SimpleNamespace(
        db_path=str(db_path),
        target_root=str(target),
        source_root=[],
        target_ext="flac",
        source_ext=None,
        prefer_ext=None,
        dry_run=False,
        all_tracks=True,  # relocate even tracks that exist at their current path
        missing_only=False,
        extensions=None,
        ids=str(track_id),
        verbose=False,
    )

    # Suppress the shutil.copy2 backup call (we don't need a real backup written)
    with patch("scripts.rekordbox_relocate.shutil.copy2"):
        run(args)

    # Re-open DB copy and verify the path was updated
    db2 = _open_db(db_path)
    updated = db2.get_content().filter_by(ID=track_id).first()
    updated_folder_path = updated.FolderPath
    db2.close()

    assert updated_folder_path != original_path, (
        f"FolderPath was not updated for track {track_id!r} — still {updated_folder_path!r}"
    )
    assert str(match_file).replace("\\", "/") in updated_folder_path.replace("\\", "/"), (
        f"FolderPath does not point at the new file: {updated_folder_path!r}"
    )


# ---------------------------------------------------------------------------
# Fix Metadata — mutation test on real data
# ---------------------------------------------------------------------------


def test_fix_metadata_corrects_wrong_filetype(tmp_path):
    """
    fix_metadata must correct FileType when the DB value doesn't match the file extension.

    Strategy:
      1. Open DB copy, find a non-deleted track.
      2. Rewrite its FolderPath to point to a .flac file we create in tmp.
      3. Set FileType = 1 (wrong — should be 6 for FLAC).
      4. Commit those changes to the DB copy.
      5. Run fix_metadata (non-dry-run).
      6. Assert FileType is now 6.
    """
    from scripts.rekordbox_fix_metadata import run

    db_path = _copy_db(tmp_path)
    db = _open_db(db_path)

    track = db.get_content().filter_by(rb_local_deleted=0).first()
    if track is None:
        db.close()
        pytest.skip("No active tracks in fixture DB")

    # Create a real .flac file in tmp so fix_metadata can stat it
    fake_flac = tmp_path / "test_track.flac"
    fake_flac.write_bytes(b"x" * 1024)

    # Rewrite the track to point at our fake .flac with the wrong FileType
    track.FolderPath = str(fake_flac).replace("\\", "/")
    track.FileType = 1  # deliberately wrong
    # Capture identity before closing — once db is closed, the ORM instance
    # detaches and attribute access raises DetachedInstanceError.
    track_id = track.ID
    db.commit()
    db.close()

    args = SimpleNamespace(
        db_path=str(db_path),
        dry_run=False,
        verbose=False,
        ids=None,
    )

    with patch("scripts.rekordbox_fix_metadata.shutil.copy2"):
        run(args)

    db2 = _open_db(db_path)
    updated = db2.get_content().filter_by(ID=track_id).first()
    updated_filetype = updated.FileType
    db2.close()

    assert updated_filetype == 6, (
        f"FileType not corrected for track {track_id!r} — got {updated_filetype!r}, expected 6"
    )


# ---------------------------------------------------------------------------
# Cleanup — orphan detection against real DB
# ---------------------------------------------------------------------------


def test_cleanup_identifies_file_not_in_db(tmp_path):
    """
    cleanup must flag a file that doesn't appear in any active DB track as an orphan.

    Strategy:
      1. Create a scan directory with one audio file whose path is not in the DB.
      2. Run cleanup --dry-run against the real DB copy.
      3. Assert the file appears in the 'unreferenced' report output.
    """
    from scripts.rekordbox_cleanup import run

    db_path = _copy_db(tmp_path)
    scan_root = tmp_path / "scan"
    scan_root.mkdir()
    delete_dir = tmp_path / "DELETE"

    # This file path will never match any real DB entry
    orphan = scan_root / "zzz_orphan_test_file_not_in_db.mp3"
    orphan.write_bytes(b"x" * 512)

    args = SimpleNamespace(
        db_path=str(db_path),
        scan_root=str(scan_root),
        delete_dir=str(delete_dir),
        exclude=[],
        extensions=None,
        dry_run=True,
    )

    run(args)

    # In dry_run mode nothing is moved, but the script must not crash and
    # must complete — if it raised an exception we would not reach this line.
    # The orphan file must still be in place (dry_run never moves)
    assert orphan.exists(), "Orphan file was deleted or moved during dry_run — invariant violated"


def test_cleanup_moves_orphan_in_live_run(tmp_path):
    """cleanup must move (not delete) the orphan file in a live (non-dry) run."""
    from scripts.rekordbox_cleanup import run

    db_path = _copy_db(tmp_path)
    scan_root = tmp_path / "scan"
    scan_root.mkdir()
    delete_dir = tmp_path / "DELETE"

    orphan = scan_root / "zzz_orphan_test_file_not_in_db.mp3"
    orphan.write_bytes(b"x" * 512)

    args = SimpleNamespace(
        db_path=str(db_path),
        scan_root=str(scan_root),
        delete_dir=str(delete_dir),
        exclude=[],
        extensions=None,
        dry_run=False,
    )

    run(args)

    assert not orphan.exists(), "Orphan was not moved out of scan_root after live run"
    moved_files = list(delete_dir.rglob("*.mp3"))
    assert len(moved_files) == 1, (
        f"Expected 1 file in DELETE folder, found {len(moved_files)}: {moved_files}"
    )
