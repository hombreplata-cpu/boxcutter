# rekordbox_remove_missing.py
#
# Removes tracks from the Rekordbox collection whose file does not exist on disk.
# Sets rb_local_deleted=1 (soft delete) rather than hard-deleting rows,
# which is how Rekordbox itself marks removed tracks.
#
# USAGE
# -----
#   python rekordbox_remove_missing.py --dry-run
#   python rekordbox_remove_missing.py
#
# SAFETY
#   - Timestamped backup created before any writes
#   - Soft delete only (rb_local_deleted=1), no rows are destroyed
#   - Rekordbox must be CLOSED

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from pyrekordbox import Rekordbox6Database as MasterDatabase


def normalize_path(raw):
    return (raw or "").replace("/", os.sep)


def run(args):
    print("[db] Opening Rekordbox database...")
    db = MasterDatabase(path=args.db_path if args.db_path else None)

    if not args.dry_run:
        try:
            db_path = Path(db.engine.url.database)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = db_path.with_name(f"master_backup_{ts}.db")
            shutil.copy2(db_path, backup)
            print(f"[backup] {backup}")
        except Exception as e:
            print(f"[backup] WARNING: {e}")

    contents = db.get_content().filter_by(rb_local_deleted=0).all()
    print(f"[db] Loaded {len(contents):,} track rows.")
    total = len(contents)
    _progress_every = max(50, total // 200)

    removed = []
    kept = 0

    for _i, content in enumerate(contents, 1):
        if _i % _progress_every == 0 or _i == total:
            print(f'%%PROGRESS%% {{"current": {_i}, "total": {total}}}', flush=True)
        raw_path = content.FolderPath or ""
        os_path = normalize_path(raw_path)

        if not os_path or not os.path.isfile(os_path):
            removed.append((content.ID, content.Title or "", raw_path))
            if args.dry_run:
                print("[dry-run] REMOVE id={} | {}".format(content.ID, content.Title or ""))
            else:
                content.rb_local_deleted = 1
        else:
            kept += 1

    if not args.dry_run:
        db.commit()

    dry_tag = " (dry-run)" if args.dry_run else ""
    print("\n" + "=" * 50)
    print(f"  Kept                  : {kept:,}")
    print(f"  Removed{dry_tag}             : {len(removed):,}")

    if removed and args.dry_run:
        print("\n-- WOULD REMOVE --")
        for tid, title, path in removed:
            print(f"  [id={tid}] {title} -> {path}")

    print("%%REPORT_START%%")
    print(
        json.dumps(
            {
                "tool": "remove_missing",
                "dry_run": args.dry_run,
                "summary": {
                    "total": len(contents),
                    "kept": kept,
                    "removed": len(removed),
                },
                "removed_tracks": [
                    {
                        "title": title,
                        "path": normalize_path(path),
                        "reason": "file not found on disk",
                    }
                    for _id, title, path in removed
                ],
            }
        )
    )
    print("%%REPORT_END%%")


def main():
    parser = argparse.ArgumentParser(
        description="Remove missing tracks from Rekordbox collection (soft delete)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without modifying the database",
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
