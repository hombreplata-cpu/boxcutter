"""
rekordbox_add_new.py — Add New Tracks to Playlist

Scans a watch directory for audio files not yet in the Rekordbox database
and inserts them into both the library and a chosen playlist. When Rekordbox
next opens the tracks appear as if dragged in manually; only analysis
(Right-click → Analyze Tracks) is required.

Usage:
    python rekordbox_add_new.py --watch-dir DIR --playlist-id ID [--dry-run]
"""

import argparse
import contextlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import mutagen
from pyrekordbox import Rekordbox6Database as MasterDatabase

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".aiff",
    ".aif",
}


def normalize_path(p):
    """Normalise to forward slashes + lowercase for Windows case-insensitive comparison."""
    return str(p).replace("\\", "/").lower()


def _first(val):
    """Return first element of a list/tuple, or val itself. Returns None if empty."""
    if isinstance(val, (list, tuple)):
        return val[0] if val else None
    return val


def read_audio_tags(fp):
    """
    Read audio tags from an audio file using mutagen.

    Returns a dict with any subset of:
        title, artist, album, genre, bpm, year, track_no, comment,
        length_ms, bitrate, sample_rate

    All tag reads are best-effort — any exception returns {} so the caller
    can still proceed with the filename as a fallback title.
    """
    try:
        audio = mutagen.File(fp, easy=True)
        if audio is None:
            return {}

        tags = {}

        # Text tags — mutagen easy=True normalises all formats to lowercase keys
        raw_title = _first(audio.get("title"))
        if raw_title:
            val = str(raw_title).strip()
            if val:
                tags["title"] = val

        raw_artist = _first(audio.get("artist"))
        if raw_artist:
            val = str(raw_artist).strip()
            if val:
                tags["artist"] = val

        raw_album = _first(audio.get("album"))
        if raw_album:
            val = str(raw_album).strip()
            if val:
                tags["album"] = val

        raw_genre = _first(audio.get("genre"))
        if raw_genre:
            val = str(raw_genre).strip()
            if val:
                tags["genre"] = val

        raw_bpm = _first(audio.get("bpm"))
        if raw_bpm:
            with contextlib.suppress(ValueError, TypeError):
                tags["bpm"] = int(float(str(raw_bpm).strip()))

        # Year — take first 4 chars of the date tag
        raw_date = _first(audio.get("date"))
        if raw_date:
            with contextlib.suppress(ValueError, TypeError):
                tags["year"] = int(str(raw_date).strip()[:4])

        # Track number — handles "1/12" total-track format
        raw_trackno = _first(audio.get("tracknumber"))
        if raw_trackno:
            with contextlib.suppress(ValueError, TypeError):
                tags["track_no"] = int(str(raw_trackno).strip().split("/")[0])

        raw_comment = _first(audio.get("comment"))
        if raw_comment:
            val = str(raw_comment).strip()
            if val:
                tags["comment"] = val

        # Stream info properties (length, bitrate, sample rate)
        info = audio.info
        if hasattr(info, "length") and info.length:
            tags["length_ms"] = int(info.length * 1000)
        if hasattr(info, "bitrate") and info.bitrate:
            tags["bitrate"] = info.bitrate // 1000  # bps → kbps
        if hasattr(info, "sample_rate") and info.sample_rate:
            tags["sample_rate"] = info.sample_rate

        return tags

    except Exception:  # noqa: BLE001
        return {}


def _get_or_create_artist(db, name):
    """Return existing DjmdArtist by name, creating it if absent. Returns None on error."""
    try:
        obj = db.get_artist(Name=name).one_or_none()
        return obj if obj is not None else db.add_artist(name=name)
    except Exception:  # noqa: BLE001
        return None


def _get_or_create_album(db, name, artist=None):
    """Return existing DjmdAlbum by name, creating it if absent. Returns None on error."""
    try:
        obj = db.get_album(Name=name).one_or_none()
        return obj if obj is not None else db.add_album(name=name, artist=artist)
    except Exception:  # noqa: BLE001
        return None


def _get_or_create_genre(db, name):
    """Return existing DjmdGenre by name, creating it if absent. Returns None on error."""
    try:
        obj = db.get_genre(Name=name).one_or_none()
        return obj if obj is not None else db.add_genre(name=name)
    except Exception:  # noqa: BLE001
        return None


def scan_directory(watch_dir):
    """Recursively find audio files under watch_dir."""
    found = []
    for root, _dirs, files in os.walk(watch_dir):
        for name in files:
            fp = Path(root) / name
            if fp.suffix.lower() in AUDIO_EXTENSIONS:
                found.append(fp)
    return found


def run(args):
    watch_dir = Path(args.watch_dir)
    if not watch_dir.is_dir():
        print(f"[error] Watch directory not found: {watch_dir}")
        sys.exit(1)

    print("[db]   Opening Rekordbox database…")
    db = MasterDatabase(path=args.db_path if args.db_path else None)

    # Backup before any writes
    if not args.dry_run:
        db_path = Path(db.engine.url.database)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.with_name(f"master_backup_{ts}.db")
        shutil.copy2(db_path, backup_path)
        print(f"[backup] {backup_path}")

    # Build set of all paths already in the DB (normalised to forward slashes)
    # Filter to active tracks only (rb_local_deleted=0) — soft-deleted tracks are
    # excluded so they can be re-added if still present on disk.
    print("[db]   Loading existing track paths…")
    all_content = db.get_content().filter_by(rb_local_deleted=0).all()
    existing_paths = {normalize_path(c.FolderPath) for c in all_content if c.FolderPath}
    print(f"[db]   {len(all_content):,} active tracks in database")

    # Find the target playlist

    # get_playlist(ID=x) returns the object directly (not a query), so no .one() needed
    try:
        playlist = db.get_playlist(ID=args.playlist_id)
        if playlist is None:
            raise ValueError("no result")
    except Exception:
        print(f"[error] Playlist ID '{args.playlist_id}' not found in database")
        sys.exit(1)

    print(f"[playlist] Target: {playlist.Name!r} (ID: {playlist.ID})")

    # Scan watch directory
    print(f"[scan] Scanning: {watch_dir}")
    disk_files = scan_directory(watch_dir)
    print(f"[scan] {len(disk_files):,} audio files found on disk")

    # Find new files (not already in DB)
    new_files = [f for f in disk_files if normalize_path(f) not in existing_paths]
    already_in_db = len(disk_files) - len(new_files)
    print(f"[scan] {already_in_db:,} already in database — skipped")
    print(f"[scan] {len(new_files):,} new files to add")

    if not new_files:
        print("\n" + "=" * 60)
        print("SUMMARY")
        print(f"  Scanned    : {len(disk_files):,}")
        print(f"  Already in DB : {already_in_db:,}")
        print("  Added      : 0")
        _emit_report(args, playlist.Name, len(disk_files), already_in_db, [], [])
        return

    print()

    added = []
    errors = []

    for fp in new_files:
        label = fp.name
        tags = read_audio_tags(fp)
        title = tags.get("title") or fp.stem

        if args.dry_run:
            print(f"[dry-run] Would add: {fp}")
            added.append({"title": title, "path": normalize_path(fp)})
            continue

        try:
            # Build content kwargs from audio tags
            content_kwargs = {"Title": title}

            # Direct scalar fields — only include if the tag value is present
            for tag_key, db_field in [
                ("bpm", "BPM"),
                ("year", "ReleaseYear"),
                ("track_no", "TrackNo"),
                ("comment", "Commnt"),
                ("length_ms", "Length"),
                ("bitrate", "BitRate"),
                ("sample_rate", "SampleRate"),
            ]:
                val = tags.get(tag_key)
                if val is not None:
                    content_kwargs[db_field] = val

            # FK fields — get-or-create Artist/Album/Genre records
            artist_obj = None
            if tags.get("artist"):
                artist_obj = _get_or_create_artist(db, tags["artist"])
                if artist_obj is not None:
                    content_kwargs["ArtistID"] = artist_obj.ID

            if tags.get("album"):
                album_obj = _get_or_create_album(db, tags["album"], artist=artist_obj)
                if album_obj is not None:
                    content_kwargs["AlbumID"] = album_obj.ID

            if tags.get("genre"):
                genre_obj = _get_or_create_genre(db, tags["genre"])
                if genre_obj is not None:
                    content_kwargs["GenreID"] = genre_obj.ID

            content = db.add_content(fp, **content_kwargs)
            db.add_to_playlist(playlist, content)
            print(f"[added]   {label}")
            added.append({"title": title, "path": normalize_path(fp)})
        except ValueError as exc:
            # add_content raises ValueError for duplicate paths or unknown extensions
            reason = str(exc)
            print(f"[skip]    {label}  — {reason}")
            errors.append({"path": normalize_path(fp), "reason": reason})
        except Exception as exc:  # noqa: BLE001
            reason = str(exc)
            print(f"[error]   {label}  — {reason}")
            errors.append({"path": normalize_path(fp), "reason": reason})

    if args.dry_run:
        print("\n[dry-run] No changes written — rollback")
        db.rollback()
    else:
        db.commit()
        print(f"\n[db]   Committed {len(added):,} new track(s)")

    print()
    print("=" * 60)
    print("SUMMARY")
    print(f"  Scanned      : {len(disk_files):,}")
    print(f"  Already in DB: {already_in_db:,}")
    print(f"  Added        : {len(added):,}")
    if errors:
        print(f"  Errors       : {len(errors):,}")

    _emit_report(args, playlist.Name, len(disk_files), already_in_db, added, errors)


def _emit_report(args, playlist_name, scanned, already_in_db, added, errors):
    report = {
        "tool": "add_new",
        "dry_run": args.dry_run,
        "watch_dir": normalize_path(args.watch_dir),
        "playlist_name": playlist_name,
        "summary": {
            "scanned": scanned,
            "already_in_db": already_in_db,
            "added": len(added),
            "errors": len(errors),
        },
        "added": added,
        "errors": errors,
    }
    print("%%REPORT_START%%")
    print(json.dumps(report))
    print("%%REPORT_END%%")


def main():
    parser = argparse.ArgumentParser(
        description="Add audio files from a watch directory to a Rekordbox playlist."
    )
    parser.add_argument(
        "--watch-dir", metavar="DIR", required=True, help="Directory to scan for new audio files"
    )
    parser.add_argument(
        "--playlist-id", metavar="ID", required=True, help="Rekordbox playlist ID to add tracks to"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing to the database"
    )
    parser.add_argument(
        "--db-path",
        metavar="PATH",
        default="",
        help="Path to master.db (auto-detected if not set)",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
