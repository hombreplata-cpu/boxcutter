# rekordbox_cleanup.py
#
# Finds audio files inside --scan-root that are NOT referenced by any active
# track in Rekordbox, and moves them to a DELETE folder for review.
#
# USAGE
# -----
#   # Dry run first - nothing is moved:
#   python rekordbox_cleanup.py --scan-root "D:\Music" --dry-run
#
#   # Live run:
#   python rekordbox_cleanup.py --scan-root "D:\Music"
#
# OPTIONS
#   --scan-root     Folder to scan for unreferenced files (required)
#   --exclude       Subfolder(s) to exclude from scan (repeat for multiple)
#   --delete-dir    Where to move unreferenced files
#                   Default: Desktop\DELETE
#   --dry-run       Print what WOULD be moved without touching anything
#   --extensions    Comma-separated audio extensions to check
#                   Default: mp3,flac,wav,aiff,aif,ogg,m4a,alac,wma
#
# SAFETY
#   - Files are MOVED not deleted — review the DELETE folder before emptying
#   - Original subfolder structure is preserved inside DELETE
#   - Rekordbox must be CLOSED before running this script
#   - Only active tracks (not soft-deleted from Rekordbox) are checked

import argparse
import os
import platform
import shutil
from pathlib import Path

from pyrekordbox import Rekordbox6Database as MasterDatabase

DEFAULT_EXTENSIONS = {"mp3", "flac", "wav", "aiff", "aif", "ogg", "m4a", "alac", "wma"}


def normalize_path(raw):
    if not raw:
        return raw
    if platform.system() == "Windows":
        raw = raw.replace("/", "\\")
    return raw


def run(args):
    scan_root = Path(args.scan_root)
    if not scan_root.is_dir():
        raise SystemExit("--scan-root is not a valid directory: {}".format(scan_root))

    if args.delete_dir:
        delete_dir = Path(args.delete_dir)
    else:
        onedrive_desktop = Path.home() / "OneDrive" / "Desktop" / "DELETE"
        regular_desktop  = Path.home() / "Desktop" / "DELETE"
        delete_dir = onedrive_desktop if (Path.home() / "OneDrive" / "Desktop").is_dir() else regular_desktop

    excludes = []
    for e in (args.exclude or []):
        excludes.append(str(Path(e)))

    extensions = set(args.extensions.split(",")) if args.extensions else DEFAULT_EXTENSIONS
    extensions = {e.lower().lstrip(".") for e in extensions}

    print("[db] Opening Rekordbox master database...")
    try:
        db = MasterDatabase()
    except Exception as e:
        raise SystemExit("Failed to open Rekordbox database: {}\nMake sure Rekordbox is closed.".format(e))

    print("[db] Loading active track paths...")
    contents = db.get_content().filter_by(rb_local_deleted=0).all()
    active_paths = set()
    for content in contents:
        raw = content.FolderPath or ""
        plain = normalize_path(raw)
        if plain:
            active_paths.add(os.path.normcase(plain))
    print("[db] Found {:,} active track paths in Rekordbox.".format(len(active_paths)))

    print("[scan] Scanning: {}".format(scan_root))
    for exc in excludes:
        print("[scan] Excluding: {}".format(exc))

    unreferenced = []
    total_scanned = 0

    for dirpath, dirs, files in os.walk(scan_root):
        dirs[:] = [d for d in dirs
                   if not any(os.path.normcase(os.path.join(dirpath, d)).startswith(
                       os.path.normcase(exc)) for exc in excludes)]

        for fname in files:
            p = Path(fname)
            if p.suffix.lstrip(".").lower() not in extensions:
                continue
            total_scanned += 1
            full_path = os.path.join(dirpath, fname)
            if os.path.normcase(full_path) not in active_paths:
                unreferenced.append(full_path)

    print("[scan] Scanned {:,} audio files.".format(total_scanned))
    print("[scan] Found {:,} unreferenced files.".format(len(unreferenced)))

    if not unreferenced:
        print("\nNothing to move.")
        return

    moved   = 0
    skipped = 0
    errors  = []

    for src in unreferenced:
        try:
            rel = os.path.relpath(src, scan_root)
        except ValueError:
            rel = os.path.basename(src)

        dst = delete_dir / rel

        if args.dry_run:
            print("[dry-run]\n  {}\n  -> {}".format(src, dst))
        else:
            try:
                os.makedirs(dst.parent, exist_ok=True)
                if dst.exists():
                    stem = dst.stem
                    ext  = dst.suffix
                    i    = 1
                    while dst.exists():
                        dst = dst.parent / "{}-{}{}".format(stem, i, ext)
                        i  += 1
                shutil.move(src, dst)
                moved += 1
            except Exception as e:
                errors.append((src, str(e)))
                skipped += 1

    dry_tag = "  (dry-run)" if args.dry_run else ""
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("  Audio files scanned          : {:,}".format(total_scanned))
    print("  Active in Rekordbox          : {:,}".format(total_scanned - len(unreferenced)))
    print("  Unreferenced found           : {:,}".format(len(unreferenced)))
    if args.dry_run:
        print("  Would be moved to DELETE     : {:,}{}".format(len(unreferenced), dry_tag))
    else:
        print("  Moved to DELETE              : {:,}".format(moved))
        print("  Skipped (errors)             : {:,}".format(skipped))
        if errors:
            print("\n-- ERRORS --")
            for src, err in errors:
                print("  {} : {}".format(src, err))
        if moved > 0:
            print("\nFiles moved to: {}".format(delete_dir))
            print("Review and delete manually when ready.")


def main():
    parser = argparse.ArgumentParser(
        description="Move audio files not referenced in Rekordbox to a DELETE folder."
    )
    parser.add_argument("--scan-root", metavar="DIR", required=True,
                        help="Folder to scan for unreferenced files")
    parser.add_argument("--exclude", metavar="DIR", action="append",
                        help="Subfolder(s) to exclude from scan (repeat for multiple)")
    parser.add_argument("--delete-dir", metavar="DIR",
                        help="Destination folder for unreferenced files (default: Desktop/DELETE)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be moved without moving anything")
    parser.add_argument("--extensions", metavar="LIST",
                        help="Comma-separated audio extensions to check")

    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
