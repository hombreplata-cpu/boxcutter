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
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from pyrekordbox import Rekordbox6Database as MasterDatabase

AUDIO_EXTENSIONS = {
    ".mp3",
    ".m4a",
    ".wav",
    ".flac",
    ".aif",
    ".aiff",
    ".ogg",
    ".wma",
    ".mp4",
    ".alac",
}


def normalize_path(p):
    """Normalise to forward slashes for cross-format comparison."""
    return str(p).replace("\\", "/")


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
    db = MasterDatabase()

    # Backup before any writes
    if not args.dry_run:
        db_path = Path(db.engine.url.database)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.with_name(f"master_backup_{ts}.db")
        shutil.copy2(db_path, backup_path)
        print(f"[backup] Saved to: {backup_path}")

    # Build set of all paths already in the DB (normalised to forward slashes)
    print("[db]   Loading existing track paths…")
    all_content = db.get_content().all()
    existing_paths = {normalize_path(c.FolderPath) for c in all_content if c.FolderPath}
    print(f"[db]   {len(existing_paths):,} tracks already in database")

    # Find the target playlist
    try:
        playlist = db.get_playlist(ID=args.playlist_id).one()
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
        if args.dry_run:
            print(f"[dry-run] Would add: {fp}")
            added.append({"title": fp.stem, "path": normalize_path(fp)})
            continue

        try:
            content = db.add_content(fp, Title=fp.stem)
            db.add_to_playlist(playlist, content)
            print(f"[added]   {label}")
            added.append({"title": fp.stem, "path": normalize_path(fp)})
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
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
