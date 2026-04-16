"""
rekordbox_fix_metadata.py
--------------------------
Fixes stale FileType and FileSize in djmdContent for tracks whose
FolderPath is correct but whose cached metadata doesn't match the
actual file on disk — causing Rekordbox to show them as broken.

Uses pyrekordbox so database encryption is handled transparently.

Usage:
    python rekordbox_fix_metadata.py [--dry-run] [--verbose] [--ids 123,456]

Options:
    --dry-run   Show what would change without writing to DB
    --verbose   Print every track checked, not just changed ones
    --ids       Comma-separated list of track IDs to fix (default: all broken)

IMPORTANT: Close Rekordbox completely before running.
"""

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from pyrekordbox import Rekordbox6Database as MasterDatabase

EXT_TO_FILETYPE = {
    ".mp3": 1,
    ".m4a": 4,  # AAC container
    ".wav": 5,
    ".flac": 6,
    ".aif": 7,
    ".aiff": 7,
    ".ogg": 8,
    ".wma": 9,
    ".mp4": 10,
    ".alac": 11,  # ALAC stored as .alac (distinct from .m4a)
}


def main():
    parser = argparse.ArgumentParser(
        description="Fix stale FileType/FileSize in Rekordbox DB for tracks with correct paths."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--verbose", action="store_true", help="Print all tracks checked")
    parser.add_argument("--ids", metavar="ID_LIST", help="Comma-separated track IDs to fix")
    args = parser.parse_args()

    id_filter = None
    if args.ids:
        id_filter = {i.strip() for i in args.ids.split(",")}

    print("[db] Opening Rekordbox database...")
    db = MasterDatabase()

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
    print(f"[db] {len(contents):,} tracks loaded")

    stats = {"fixed": 0, "already_ok": 0, "missing": 0, "skipped": 0}
    fixed_log = []
    missing_log = []

    for r in contents:
        if id_filter and str(r.ID) not in id_filter:
            stats["skipped"] += 1
            continue

        raw_path = r.FolderPath or ""
        if not raw_path:
            stats["skipped"] += 1
            continue

        win_path = raw_path.replace("/", "\\")

        if not os.path.isfile(win_path):
            if args.verbose:
                print(f"  [MISSING] {r.Title} — file not on disk")
            stats["missing"] += 1
            missing_log.append(
                {
                    "id": r.ID,
                    "title": r.Title or "",
                    "path": win_path,
                }
            )
            continue

        actual_size = os.path.getsize(win_path)
        actual_type = EXT_TO_FILETYPE.get(Path(win_path).suffix.lower(), 6)

        db_size = r.FileSize or 0
        db_type = r.FileType or 0

        if db_size == actual_size and db_type == actual_type:
            if args.verbose:
                print(f"  [OK] {r.Title}")
            stats["already_ok"] += 1
            continue

        # Needs fixing
        changes = []
        if db_type != actual_type:
            changes.append(f"FileType {db_type} → {actual_type}")
        if db_size != actual_size:
            changes.append(f"FileSize {db_size:,} → {actual_size:,}")

        dry_tag = "[dry-run] " if args.dry_run else ""
        print("\n{}[FIX] {}".format(dry_tag, r.Title or ""))
        for c in changes:
            print(f"  {c}")

        if not args.dry_run:
            r.FileType = actual_type
            r.FileSize = actual_size

        stats["fixed"] += 1
        fixed_log.append(
            {
                "id": r.ID,
                "title": r.Title or "",
                "path": win_path,
                "db_type": db_type,
                "actual_type": actual_type,
                "db_size": db_size,
                "actual_size": actual_size,
                "type_changed": db_type != actual_type,
                "size_changed": db_size != actual_size,
            }
        )

    if not args.dry_run and stats["fixed"] > 0:
        db.commit()
        print("\n[COMMITTED] Changes written to DB.")
    elif args.dry_run:
        print("\n[DRY-RUN] No changes written.")

    total = len(contents)
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"  Total tracks      : {total:,}")
    print(
        "  Fixed{}           : {:,}".format(
            " (dry-run)" if args.dry_run else "           ", stats["fixed"]
        )
    )
    print("  Already correct   : {:,}".format(stats["already_ok"]))
    print("  File missing      : {:,}".format(stats["missing"]))
    print("  Skipped (filter)  : {:,}".format(stats["skipped"]))

    if missing_log:
        print("\n-- FILE MISSING (path stored but file not found on disk) --")
        for item in missing_log[:50]:
            print("  [id={}] {}".format(item["id"], item["title"]))
            print("         {}".format(item["path"]))
        if len(missing_log) > 50:
            print(f"  ... and {len(missing_log) - 50} more.")

    # ── Structured report block (parsed by the web UI) ──────────────────────
    report = {
        "tool": "fix_metadata",
        "dry_run": args.dry_run,
        "summary": {
            "total": total,
            "fixed": stats["fixed"],
            "already_ok": stats["already_ok"],
            "missing": stats["missing"],
            "skipped": stats["skipped"],
        },
        "fixed_tracks": fixed_log,
        "missing_tracks": missing_log,
    }
    print("%%REPORT_START%%")
    print(json.dumps(report))
    print("%%REPORT_END%%")


if __name__ == "__main__":
    main()
