# rekordbox_relocate.py
#
# Bulk-relocate track file paths inside the Rekordbox 7 database (master.db)
# to a target directory containing higher-quality files (e.g. FLAC).
#
# Re-points any track whose current file is:
#   - Missing/broken (file doesn't exist on disk), OR
#   - Located under a --source-root folder (e.g. an MP3 library you're
#     upgrading to FLAC)
#
# USAGE
# -----
#   # Dry run first — nothing is written:
#   python rekordbox_relocate.py --target-root "D:\Music\FLAC" --dry-run
#
#   # Migrate MP3s that have a FLAC equivalent (strict: only FLAC accepted):
#   python rekordbox_relocate.py \
#       --target-root "D:\Music\FLAC" \
#       --source-root "D:\Music\MP3" \
#       --source-ext mp3 \
#       --target-ext flac \
#       --dry-run
#
#   # Live run (remove --dry-run to apply):
#   python rekordbox_relocate.py \
#       --target-root "D:\Music\FLAC" \
#       --source-root "D:\Music\MP3" \
#       --source-ext mp3 \
#       --target-ext flac
#
# MATCHING LOGIC (seven passes per track)
#   1. Exact filename match
#   2. Title - Artist  (common FLAC naming format)
#   3. Artist - Title
#   3b. Strip mix/version suffixes and retry 2+3
#   4. Strip numeric prefix (e.g. "00 - ") then retry 2+3
#   5. Title substring search (title appears anywhere in stem)
#   6. Partial title match (first 25 chars) for truncated filenames
#   7. Fuzzy normalized match (collapses separators/brackets)
#
# EXTENSION MATCHING IS STRICT
#   --target-ext determines the only acceptable file format. If a track's
#   stem is found in the target root but only in a different format, the
#   track is counted as "still missing" — it is NOT relocated to the wrong
#   format. Use --source-ext to limit which tracks are processed.
#
# SAFETY
#   - A timestamped backup of master.db is always created before any writes
#   - Rekordbox must be CLOSED before running this script

import argparse
import json
import os
import platform
import re
import shutil
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from pyrekordbox import Rekordbox6Database as MasterDatabase
from utils import EXT_TO_FILETYPE

DEFAULT_EXTENSIONS = {"mp3", "flac", "wav", "aiff", "aif", "ogg", "m4a", "alac", "wma"}
NUMERIC_PREFIX_RE = re.compile(r"^[\d]+\s*-\s*")


def strip_numeric_prefix(s):
    return NUMERIC_PREFIX_RE.sub("", s).strip()


def sanitize(s):
    """Remove characters illegal in Windows filenames, preserving +, ;, & etc."""
    return re.sub(r'[<>"/\\|?*\x00-\x1f]', "", s or "").strip()


def normalize_stem(s):
    """
    Aggressively normalize a stem for fuzzy comparison:
    - lowercase
    - collapse all separator punctuation (-, ;, ,, /) to a single space
    - collapse whitespace
    """
    s = s.lower()
    s = re.sub(r"[\-;,/]+", " ", s)
    s = re.sub(r"[()[\]]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def artist_variants(raw):
    """
    Generate artist string variants to handle separator differences.
    Rekordbox stores multi-artists with "/" or "," but many file naming
    conventions use "; " or ", ".
    """
    raw_san = sanitize(raw)
    variants = [raw_san]

    for sep in ["/", ","]:
        if sep in raw:
            normalized = sanitize("; ".join(p.strip() for p in raw.split(sep)))
            if normalized not in variants:
                variants.append(normalized)

    if "; " in raw_san:
        comma_ver = raw_san.replace("; ", ", ")
        if comma_ver not in variants:
            variants.append(comma_ver)

    for sep in ["; ", ", ", "/", ","]:
        if sep in raw_san:
            first = raw_san.split(sep)[0].strip()
            if first and first not in variants:
                variants.append(first)
            break

    return variants


def normalize_path(raw):
    """Convert any stored path to a clean OS-native path string.

    On macOS also normalises to NFC so DB strings (often NFC) don't
    false-mismatch HFS+ filenames (often NFD) for accented characters (R-07).
    """
    if not raw:
        return raw
    if platform.system() == "Windows":
        raw = raw.replace("/", "\\")
    elif platform.system() == "Darwin":
        raw = unicodedata.normalize("NFC", raw)
    return raw


def path_is_under(path, root):
    """Return True if path is inside root (case-insensitive)."""
    if not path or not root:
        return False
    return os.path.normcase(path).startswith(os.path.normcase(root))


def build_target_index(target_root, extensions):
    """Recursively index all audio files in target_root."""
    exact_index = defaultdict(list)
    stem_index = defaultdict(list)
    norm_index = defaultdict(list)
    print(f"[scan] Indexing target root: {target_root}")
    count = 0
    for dirpath, _dirs, files in os.walk(target_root):
        for fname in files:
            p = Path(fname)
            if p.suffix.lstrip(".").lower() in extensions:
                full = os.path.join(dirpath, fname)
                exact_index[fname.lower()].append(full)
                stem_index[p.stem.lower()].append(full)
                norm_index[normalize_stem(p.stem)].append(full)
                count += 1
    print(f"[scan] Indexed {count:,} audio files in target root.")
    return dict(exact_index), dict(stem_index), dict(norm_index)


def lookup_stem(stem, ext, exact_index, stem_index, target_ext):
    """Return matching paths for stem. Strict: only target_ext accepted, no fallback."""
    matches = exact_index.get((stem + ext).lower(), [])
    if matches:
        if target_ext:
            return [p for p in matches if Path(p).suffix.lstrip(".").lower() == target_ext]
        return matches
    stem_matches = stem_index.get(stem.lower(), [])
    if stem_matches:
        if target_ext:
            return [p for p in stem_matches if Path(p).suffix.lstrip(".").lower() == target_ext]
        return stem_matches
    return []


def find_match(filename, title, raw_artist, exact_index, stem_index, norm_index, target_ext):
    """Multi-pass match strategy. Returns (matches, match_type).

    Extension matching is strict: only files with target_ext are accepted.
    A stem match with a different extension returns [] (not a fallback hit).
    """
    ext = Path(filename).suffix
    stem = Path(filename).stem
    t = sanitize(title or "")

    # Pass 1: exact filename
    matches = exact_index.get(filename.lower(), [])
    if matches:
        if target_ext:
            matches = [p for p in matches if Path(p).suffix.lstrip(".").lower() == target_ext]
        if matches:
            return matches, "exact"

    # Pass 2: Title - Artist
    if t and raw_artist:
        for av in artist_variants(raw_artist):
            matches = lookup_stem(f"{t} - {av}", ext, exact_index, stem_index, target_ext)
            if matches:
                return matches, "title-artist"

    # Pass 3: Artist - Title
    if t and raw_artist:
        for av in artist_variants(raw_artist):
            matches = lookup_stem(f"{av} - {t}", ext, exact_index, stem_index, target_ext)
            if matches:
                return matches, "artist-title"

    # Pass 3b: Strip mix/version suffixes and retry passes 2+3
    t_stripped = re.sub(
        r"\s*\([^)]*(?:mix|edit|remix|version|dub|vocal|radio|extended|original)[^)]*\)\s*$",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    if t_stripped and t_stripped != t and raw_artist:
        for av in artist_variants(raw_artist):
            matches = lookup_stem(f"{t_stripped} - {av}", ext, exact_index, stem_index, target_ext)
            if matches:
                return matches, "title-artist-stripped"
        for av in artist_variants(raw_artist):
            matches = lookup_stem(f"{av} - {t_stripped}", ext, exact_index, stem_index, target_ext)
            if matches:
                return matches, "artist-title-stripped"

    # Pass 4: Strip numeric prefix and retry
    stripped_stem = strip_numeric_prefix(stem)
    if stripped_stem != stem:
        matches = lookup_stem(stripped_stem, ext, exact_index, stem_index, target_ext)
        if matches:
            return matches, "numeric-prefix-stripped"

    # Pass 5: Title substring search
    if t:
        t_norm = t.lower()
        substring_matches = [
            p for key, paths in stem_index.items() if t_norm in key for p in paths
        ]
        if target_ext:
            substring_matches = [
                p for p in substring_matches if Path(p).suffix.lstrip(".").lower() == target_ext
            ]
        if substring_matches:
            return substring_matches, "title-substring"

    # Pass 6: Partial title match (first 25 chars)
    if t and len(t) > 25:
        partial = t[:25].lower()
        partial_matches = [
            p for key, paths in stem_index.items() if key.startswith(partial) for p in paths
        ]
        if target_ext:
            partial_matches = [
                p for p in partial_matches if Path(p).suffix.lstrip(".").lower() == target_ext
            ]
        if partial_matches:
            return partial_matches, "title-partial"

    # Pass 7: Fuzzy normalized match
    if stem:
        norm_key = normalize_stem(stem)
        fuzzy_matches = norm_index.get(norm_key, [])
        if target_ext:
            fuzzy_matches = [
                p for p in fuzzy_matches if Path(p).suffix.lstrip(".").lower() == target_ext
            ]
        if fuzzy_matches:
            return fuzzy_matches, "fuzzy-norm"

    return [], "no-match"


def run(args):
    target_root = args.target_root
    if not os.path.isdir(target_root):
        raise SystemExit(f"--target-root is not a valid directory: {target_root}")

    source_roots = args.source_root or []
    target_ext = (args.target_ext or "flac").lstrip(".").lower()
    source_ext = (args.source_ext or "").lstrip(".").lower() if args.source_ext else None
    prefer_ext = (args.prefer_ext or "").lstrip(".").lower() or None
    extensions = set(args.extensions.split(",")) if args.extensions else DEFAULT_EXTENSIONS
    extensions = {e.lower().lstrip(".") for e in extensions}

    print("[db] Opening Rekordbox database...")
    try:
        db = MasterDatabase(path=args.db_path if args.db_path else None)
    except Exception as e:
        raise SystemExit(
            f"Failed to open Rekordbox database: {e}\nMake sure Rekordbox is closed."
        ) from e

    try:
        db_path = Path(db.engine.url.database)
    except Exception:
        if platform.system() == "Windows":
            db_path = Path(os.environ.get("APPDATA", "")) / "Pioneer" / "rekordbox" / "master.db"
        else:
            db_path = (
                Path.home()
                / "Library"
                / "Application Support"
                / "Pioneer"
                / "rekordbox"
                / "master.db"
            )

    if not args.dry_run:
        try:
            backup_dir = db_path.parent / "boxcutter-backups"
            backup_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"master_backup_relocate_{ts}.db"
            shutil.copy2(db_path, backup_path)
            print(f"[backup] {backup_path}")
        except Exception as e:
            print(f"[backup] WARNING: could not create backup: {e}")

    exact_index, stem_index, norm_index = build_target_index(target_root, extensions)

    contents = db.get_content().filter_by(rb_local_deleted=0).all()
    total = len(contents)
    print(f"[db] Found {total:,} track rows.")
    _progress_every = max(50, total // 200)
    _console_verbose = total <= 200
    if args.dry_run and not _console_verbose:
        print(
            f"[dry-run] {total:,} tracks — per-track output suppressed. See report panel for full results."
        )

    updated = 0
    updated_exact = 0
    updated_title_art = 0
    updated_art_title = 0
    updated_prefix = 0
    updated_substring = 0
    updated_partial = 0
    updated_fuzzy = 0
    skipped_multi = 0
    still_missing = 0
    already_ok = 0
    already_correct = 0
    multi_match_log = []
    missing_log = []
    updated_log = []

    id_filter = None
    if args.ids:
        id_filter = {i.strip() for i in args.ids.split(",")}

    for _i, content in enumerate(contents, 1):
        if _i % _progress_every == 0 or _i == total:
            print(
                f'%%PROGRESS%% {{"current": {_i}, "total": {total}, "label": "Matching tracks"}}',
                flush=True,
            )
        if id_filter is not None and content.ID not in id_filter:
            already_ok += 1
            continue

        raw_path = content.FolderPath or ""
        plain_path = normalize_path(raw_path)

        # Filter by source extension before any path-existence checks
        if source_ext and plain_path:
            current_ext = Path(plain_path).suffix.lstrip(".").lower()
            if current_ext != source_ext:
                already_ok += 1
                continue

        if args.missing_only:
            path_exists = bool(plain_path and os.path.isfile(plain_path))
            under_source = False
            if path_exists:
                already_ok += 1
                continue
        else:
            path_exists = bool(plain_path and os.path.isfile(plain_path))
            under_source = any(path_is_under(plain_path, sr) for sr in source_roots)

        if path_exists and not under_source and not args.all_tracks:
            already_ok += 1
            continue

        if not plain_path:
            missing_log.append((content.ID, content.Title or "", "", "<empty>", "no path stored"))
            still_missing += 1
            continue

        try:
            raw_artist = content.Artist.Name if content.Artist else ""
        except Exception:
            raw_artist = ""

        filename = os.path.basename(plain_path)
        matches, match_type = find_match(
            filename,
            content.Title or "",
            raw_artist,
            exact_index,
            stem_index,
            norm_index,
            target_ext,
        )

        if len(matches) > 1 and prefer_ext:
            preferred = [m for m in matches if Path(m).suffix.lstrip(".").lower() == prefer_ext]
            if len(preferred) == 1:
                matches = preferred

        if len(matches) == 1:
            new_path = matches[0]
            new_path_stored = new_path.replace("\\", "/")

            # Never touch a row whose path is already correct — avoids
            # invalidating Rekordbox analysis on tracks that don't need updating.
            # Windows is case-insensitive: "D:/X/y.flac" and "d:/x/y.flac"
            # refer to the same file. Trailing slash differences are also
            # treated as equal. (R-09)
            existing_normalised = raw_path.replace("\\", "/").rstrip("/")
            new_normalised = new_path_stored.rstrip("/")
            if platform.system() == "Windows":
                existing_normalised = existing_normalised.lower()
                new_normalised = new_normalised.lower()
            if existing_normalised == new_normalised:
                already_correct += 1
                continue

            old_ext_lower = Path(plain_path).suffix.lower()
            new_ext_lower = Path(new_path).suffix.lower()
            if args.dry_run and _console_verbose:
                print(f"[dry-run] [{match_type}]\n  {plain_path}\n  -> {new_path}")
            else:
                actual_size = os.path.getsize(new_path)
                actual_type = EXT_TO_FILETYPE.get(Path(new_path).suffix.lower())
                content.FolderPath = new_path_stored
                content.OrgFolderPath = new_path_stored
                if actual_type is None:
                    print(f"  [WARN] Unknown extension — FileType not updated: {new_path}")
                else:
                    content.FileType = actual_type
                content.FileSize = actual_size
            old_ext = old_ext_lower.lstrip(".")
            new_ext = new_ext_lower.lstrip(".")
            updated_log.append(
                {
                    "title": content.Title or "",
                    "artist": raw_artist,
                    "old_path": plain_path,
                    "new_path": new_path,
                    "match_type": match_type,
                    "ext_changed": old_ext != new_ext,
                    "old_ext": old_ext,
                    "new_ext": new_ext,
                }
            )
            updated += 1
            if match_type == "exact":
                updated_exact += 1
            elif match_type in ("title-artist", "title-artist-stripped"):
                updated_title_art += 1
            elif match_type in ("artist-title", "artist-title-stripped"):
                updated_art_title += 1
            elif match_type == "numeric-prefix-stripped":
                updated_prefix += 1
            elif match_type in ("title-substring", "title-only", "title-only-stripped"):
                updated_substring += 1
            elif match_type == "title-partial":
                updated_partial += 1
            elif match_type == "fuzzy-norm":
                updated_fuzzy += 1

        elif len(matches) > 1:
            skipped_multi += 1
            multi_match_log.append(
                (content.ID, content.Title or "", raw_artist, plain_path, matches)
            )

        else:
            still_missing += 1
            missing_log.append(
                (
                    content.ID,
                    content.Title or "",
                    raw_artist,
                    plain_path,
                    "not found in target root",
                )
            )

    # Only commit when there are actual changes — skip the no-op write so
    # an empty live run doesn't bump the DB mtime or risk Rekordbox treating
    # the file as freshly modified (B-07).
    if not args.dry_run and updated > 0:
        db.commit()

    dry_tag = "  (dry-run)" if args.dry_run else ""
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Total tracks in DB               : {total:,}")
    print(f"  Skipped — filtered out           : {already_ok:,}")
    print(f"  Skipped — path already correct   : {already_correct:,}")
    print(f"  Updated - exact filename         : {updated_exact:,}{dry_tag}")
    print(f"  Updated - Title-Artist match     : {updated_title_art:,}{dry_tag}")
    print(f"  Updated - Artist-Title match     : {updated_art_title:,}{dry_tag}")
    print(f"  Updated - prefix stripped        : {updated_prefix:,}{dry_tag}")
    print(f"  Updated - title substring        : {updated_substring:,}{dry_tag}")
    print(f"  Updated - title partial match    : {updated_partial:,}{dry_tag}")
    print(f"  Updated - fuzzy normalized       : {updated_fuzzy:,}{dry_tag}")
    print(f"  Updated - TOTAL                  : {updated:,}{dry_tag}")
    print(f"  Skipped (multiple matches found) : {skipped_multi:,}")
    print(f"  Not found in target folder       : {still_missing:,}")

    if multi_match_log:
        print("\n-- MULTIPLE MATCHES (manual action needed) --")
        for tid, t, a, old, matches in multi_match_log:
            print(f"\n  [id={tid}] {a} - {t}")
            print(f"  DB path: {old}")
            for i, m in enumerate(matches, 1):
                print(f"    {i}) {m}")

    if missing_log:
        print("\n-- STILL MISSING (not found in target root) --")
        for tid, t, a, _old, reason in missing_log[:50]:
            print(f"  [id={tid}] {a} - {t}  ({reason})")
        if len(missing_log) > 50:
            print(f"  ... and {len(missing_log) - 50} more.")

    print()
    if not args.dry_run and updated > 0:
        print(f"Done. {updated:,} paths updated in Rekordbox database.")
        print("Open Rekordbox to see the changes.")

    filetype_updated = sum(1 for t in updated_log if t["ext_changed"])
    print("%%REPORT_START%%")
    print(
        json.dumps(
            {
                "tool": "relocate",
                "dry_run": args.dry_run,
                "summary": {
                    "total": total,
                    "already_ok": already_ok,
                    "already_correct": already_correct,
                    "updated": updated,
                    "skipped_multi": skipped_multi,
                    "still_missing": still_missing,
                    "filetype_updated": filetype_updated,
                    "by_match_type": {
                        "exact": updated_exact,
                        "title_artist": updated_title_art,
                        "artist_title": updated_art_title,
                        "prefix": updated_prefix,
                        "substring": updated_substring,
                        "partial": updated_partial,
                        "fuzzy": updated_fuzzy,
                    },
                },
                "updated": updated_log,
                "multi_matches": [
                    {"title": t, "artist": a, "old_path": old, "candidates": list(m)}
                    for _id, t, a, old, m in multi_match_log
                ],
                "missing": [
                    {"title": t, "artist": a, "old_path": old, "reason": reason}
                    for _id, t, a, old, reason in missing_log
                ],
            }
        )
    )
    print("%%REPORT_END%%")


def main():
    parser = argparse.ArgumentParser(
        description="Re-point Rekordbox track paths to a new target root directory."
    )
    parser.add_argument(
        "--target-root",
        metavar="DIR",
        required=True,
        help="The destination folder all paths should point to",
    )
    parser.add_argument(
        "--source-root",
        metavar="DIR",
        action="append",
        help="Folder(s) to migrate away from (repeat for multiple)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying the database",
    )
    parser.add_argument(
        "--all-tracks",
        action="store_true",
        help="Recheck every track regardless of current status",
    )
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Only process tracks whose file does not exist on disk",
    )
    parser.add_argument(
        "--target-ext",
        metavar="EXT",
        default="flac",
        help=(
            "Target file extension to match (default: flac). STRICT: only files with this "
            "exact extension are accepted. If a stem exists in a different format it is "
            "skipped — not relocated to the wrong format."
        ),
    )
    parser.add_argument(
        "--source-ext",
        metavar="EXT",
        default="",
        help="Only process tracks whose current file has this extension (e.g. mp3). "
        "Leave blank to process all applicable tracks.",
    )
    parser.add_argument(
        "--prefer-ext",
        metavar="EXT",
        default="",
        help="When multiple matches exist for a track, prefer this extension (e.g. flac). "
        "If exactly one match has the preferred extension, it is selected automatically "
        "instead of being skipped as ambiguous.",
    )
    parser.add_argument(
        "--extensions", metavar="LIST", help="Comma-separated audio extensions to index"
    )
    parser.add_argument("--ids", metavar="ID_LIST", help="Comma-separated track IDs to process")
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
