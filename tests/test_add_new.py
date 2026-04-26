"""
Tests for scripts/rekordbox_add_new.py

Covers:
- scan_directory finds audio files recursively and skips non-audio
- read_audio_tags returns an empty dict gracefully on bad files
- run() dry-run reports new files but writes nothing to DB
- run() skips files already in the DB (no duplicates)
- Backup is created on a live run but not on dry run
- Unknown extension files are never added
- Dry-run never persists Artist/Album/Genre side rows (B-08 invariant)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.rekordbox_add_new import (  # noqa: E402
    normalize_path,
    read_audio_tags,
    run,
    scan_directory,
)

# ---------------------------------------------------------------------------
# scan_directory
# ---------------------------------------------------------------------------


def test_scan_directory_finds_audio_files(tmp_path):
    (tmp_path / "track.flac").write_bytes(b"x")
    (tmp_path / "track.mp3").write_bytes(b"x")
    (tmp_path / "cover.jpg").write_bytes(b"x")

    found = scan_directory(tmp_path)
    stems = {f.name for f in found}
    assert "track.flac" in stems
    assert "track.mp3" in stems
    assert "cover.jpg" not in stems


def test_scan_directory_recurses_into_subfolders(tmp_path):
    sub = tmp_path / "House" / "Deep"
    sub.mkdir(parents=True)
    (sub / "deep.wav").write_bytes(b"x")

    found = scan_directory(tmp_path)
    assert any(f.name == "deep.wav" for f in found)


def test_scan_directory_empty_folder(tmp_path):
    assert scan_directory(tmp_path) == []


def test_scan_directory_skips_non_audio(tmp_path):
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "image.png").write_bytes(b"x")
    (tmp_path / "data.json").write_bytes(b"x")

    assert scan_directory(tmp_path) == []


# ---------------------------------------------------------------------------
# read_audio_tags
# ---------------------------------------------------------------------------


def test_read_audio_tags_returns_dict_on_unreadable_file(tmp_path):
    bad = tmp_path / "stub.flac"
    bad.write_bytes(b"not a real flac file")
    result = read_audio_tags(bad)
    assert isinstance(result, dict)


def test_read_audio_tags_returns_empty_dict_on_missing_file(tmp_path):
    missing = tmp_path / "ghost.flac"
    result = read_audio_tags(missing)
    assert result == {}


# ---------------------------------------------------------------------------
# normalize_path
# ---------------------------------------------------------------------------


def test_normalize_path_converts_backslashes():
    assert "\\" not in normalize_path(Path("C:\\Music\\track.flac"))


def test_normalize_path_is_lowercase():
    result = normalize_path(Path("C:/Music/TRACK.FLAC"))
    assert result == result.lower()


# ---------------------------------------------------------------------------
# run() — dry run
# ---------------------------------------------------------------------------


def _make_args(watch_dir, playlist_id="1", dry_run=False, db_path=""):
    args = MagicMock()
    args.watch_dir = str(watch_dir)
    args.playlist_id = playlist_id
    args.dry_run = dry_run
    args.db_path = db_path
    return args


def _mock_db(existing_paths=None, playlist_name="Test Playlist", playlist_id=1):
    db = MagicMock()

    existing = existing_paths or []
    contents = []
    for p in existing:
        c = MagicMock()
        c.FolderPath = str(p).replace("\\", "/").lower()
        c.rb_local_deleted = 0
        contents.append(c)
    db.get_content.return_value.filter_by.return_value.all.return_value = contents

    playlist = MagicMock()
    playlist.Name = playlist_name
    playlist.ID = playlist_id
    db.get_playlist.return_value = playlist

    return db


def test_dry_run_does_not_call_add_content(tmp_path):
    (tmp_path / "new_track.flac").write_bytes(b"x")
    db = _mock_db()

    with patch("scripts.rekordbox_add_new.MasterDatabase", return_value=db):
        run(_make_args(tmp_path, dry_run=True))

    db.add_content.assert_not_called()
    db.add_to_playlist.assert_not_called()


def test_dry_run_does_not_create_backup(tmp_path):
    (tmp_path / "track.flac").write_bytes(b"x")
    db = _mock_db()

    with (
        patch("scripts.rekordbox_add_new.MasterDatabase", return_value=db),
        patch("scripts.rekordbox_add_new.shutil.copy2") as mock_copy,
    ):
        run(_make_args(tmp_path, dry_run=True))

    mock_copy.assert_not_called()


def test_dry_run_calls_rollback(tmp_path):
    (tmp_path / "track.flac").write_bytes(b"x")
    db = _mock_db()

    with patch("scripts.rekordbox_add_new.MasterDatabase", return_value=db):
        run(_make_args(tmp_path, dry_run=True))

    db.rollback.assert_called_once()


def test_dry_run_does_not_persist_artist_album_genre(tmp_path):
    # B-08: dry-run must not leak Artist/Album/Genre rows into the DB.
    # The script enforces this structurally — the dry-run branch `continue`s
    # before the _get_or_create_* helpers fire, so add_artist / add_album /
    # add_genre are never called even with rich tag data.
    (tmp_path / "rich.flac").write_bytes(b"x")
    db = _mock_db()

    rich_tags = {
        "title": "T",
        "artist": "A",
        "album": "Alb",
        "genre": "G",
        "bpm": 120,
    }

    with (
        patch("scripts.rekordbox_add_new.MasterDatabase", return_value=db),
        patch("scripts.rekordbox_add_new.read_audio_tags", return_value=rich_tags),
    ):
        run(_make_args(tmp_path, dry_run=True))

    db.add_artist.assert_not_called()
    db.add_album.assert_not_called()
    db.add_genre.assert_not_called()
    db.get_artist.assert_not_called()
    db.get_album.assert_not_called()
    db.get_genre.assert_not_called()


# ---------------------------------------------------------------------------
# run() — skip already-in-DB files
# ---------------------------------------------------------------------------


def test_files_already_in_db_are_skipped(tmp_path):
    track = tmp_path / "existing.flac"
    track.write_bytes(b"x")

    db = _mock_db(existing_paths=[track])
    db.engine.url.database = str(tmp_path / "master.db")

    with (
        patch("scripts.rekordbox_add_new.MasterDatabase", return_value=db),
        patch("scripts.rekordbox_add_new.shutil.copy2"),
    ):
        run(_make_args(tmp_path))

    db.add_content.assert_not_called()


# ---------------------------------------------------------------------------
# run() — backup on live run
# ---------------------------------------------------------------------------


def test_live_run_creates_backup(tmp_path):
    (tmp_path / "new.flac").write_bytes(b"x")
    db_file = tmp_path / "master.db"
    db_file.write_bytes(b"db")

    db = _mock_db()
    db.engine.url.database = str(db_file)

    with (
        patch("scripts.rekordbox_add_new.MasterDatabase", return_value=db),
        patch("scripts.rekordbox_add_new.shutil.copy2") as mock_copy,
        patch("scripts.rekordbox_add_new.read_audio_tags", return_value={"title": "New"}),
    ):
        run(_make_args(tmp_path))

    mock_copy.assert_called_once()
    backup_dest = mock_copy.call_args[0][1]
    assert "master_backup_" in str(backup_dest)
