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
#   # Migrate working MP3s that have a FLAC equivalent in target-root:
#   python rekordbox_relocate.py \
#       --target-root "D:\Music\FLAC" \
#       --source-root "D:\Music\MP3" \
#       --dry-run
#
#   # Live run (remove --dry-run to apply):
#   python rekordbox_relocate.py \
#       --target-root "D:\Music\FLAC" \
#       --source-root "D:\Music\MP3"
#
# MATCHING LOGIC (six passes per track)
#   1. Exact filename match
#   2. Title - Artist  (common FLAC naming format)
#   3. Artist - Title
#   4. Strip numeric prefix (e.g. "00 - ") then retry 2+3
#   5. Title substring search (title appears anywhere in stem)
#   6. Partial title match (first 25 chars) for truncated filenames
#   7. Fuzzy normalized match (collapses separators/brackets)
#
# SAFETY
#   - A timestamped backup of master.db is always created before any writes
#   - Rekordbox must be CLOSED before running this script

import argparse
import os
import platform
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from pyrekordbox import Rekordbox6Database as MasterDatabase

DEFAULT_EXTENSIONS = {"mp3", "flac", "wav", "aiff", "aif", "ogg", "m4a", "alac", "wma"}
NUMERIC_PREFIX_RE = re.compile(r"^[\d]+\s*-\s*")

EXT_TO_FILETYPE = {
    ".mp3": 1,
    ".m4a": 4,
    ".wav": 5,
    ".flac": 6,
    ".aif": 7,
    ".aiff": 7,
    ".ogg": 8,
    ".wma": 9,
    ".mp4": 10,
}


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
    """Convert any stored path to a clean OS-native path string."""
    if not raw:
        return raw
    if platform.system() == "Windows":
        raw = raw.replace("/", "\\")
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


def lookup_stem(stem, ext, exact_index, stem_index, prefer_ext):
    matches = exact_index.get((stem + ext).lower(), [])
    if matches:
        return matches
    stem_matches = stem_index.get(stem.lower(), [])
    if stem_matches:
        preferred = [p for p in stem_matches if Path(p).suffix.lstrip(".").lower() == prefer_ext]
        return preferred if preferred else stem_matches
    return []


def find_match(filename, title, raw_artist, exact_index, stem_index, norm_index, prefer_ext):
    """Multi-pass match strategy. Returns (matches, match_type)."""
    ext = Path(filename).suffix
    stem = Path(filename).stem
    t = sanitize(title or "")

    # Pass 1: exact filename
    matches = exact_index.get(filename.lower(), [])
    if matches:
        return matches, "exact"

    # Pass 2: Title - Artist
    if t and raw_artist:
        for av in artist_variants(raw_artist):
            matches = lookup_stem(f"{t} - {av}", ext, exact_index, stem_index, prefer_ext)
            if matches:
                return matches, "title-artist"

    # Pass 3: Artist - Title
    if t and raw_artist:
        for av in artist_variants(raw_artist):
            matches = lookup_stem(f"{av} - {t}", ext, exact_index, stem_index, prefer_ext)
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
            matches = lookup_stem(f"{t_stripped} - {av}", ext, exact_index, stem_index, prefer_ext)
            if matches:
                return matches, "title-artist-stripped"
        for av in artist_variants(raw_artist):
            matches = lookup_stem(f"{av} - {t_stripped}", ext, exact_index, stem_index, prefer_ext)
            if matches:
                return matches, "artist-title-stripped"

    # Pass 4: Strip numeric prefix and retry
    stripped_stem = strip_numeric_prefix(stem)
    if stripped_stem != stem:
        matches = lookup_stem(stripped_stem, ext, exact_index, stem_index, prefer_ext)
        if matches:
            return matches, "numeric-prefix-stripped"

    # Pass 5: Title substring search
    if t:
        t_norm = t.lower()
        substring_matches = [
            p for key, paths in stem_index.items() if t_norm in key for p in paths
        ]
        if substring_matches:
            preferred = [
                p for p in substring_matches if Path(p).suffix.lstrip(".").lower() == prefer_ext
            ]
            return (preferred if preferred else substring_matches), "title-substring"

    # Pass 6: Partial title match (first 25 chars)
    if t and len(t) > 25:
        partial = t[:25].lower()
        partial_matches = [
            p for key, paths in stem_index.items() if key.startswith(partial) for p in paths
        ]
        if partial_matches:
            return partial_matches, "title-partial"

    # Pass 7: Fuzzy normalized match
    if stem:
        norm_key = normalize_stem(stem)
        fuzzy_matches = norm_index.get(norm_key, [])
        if fuzzy_matches:
            preferred = [
                p for p in fuzzy_matches if Path(p).suffix.lstrip(".").lower() == prefer_ext
            ]
            return (preferred if preferred else fuzzy_matches), "fuzzy-norm"

    return [], "no-match"


def run(args):
    target_root = args.target_root
    if not os.path.isdir(target_root):
        raise SystemExit(f"--target-root is not a valid directory: {target_root}")

    source_roots = args.source_root or []
    prefer_ext = (args.prefer_ext or "flac").lstrip(".").lower()
    extensions = set(args.extensions.split(",")) if args.extensions else DEFAULT_EXTENSIONS
    extensions = {e.lower().lstrip(".") for e in extensions}

    print("[db] Opening Rekordbox database...")
    try:
        db = MasterDatabase()
    except Exception as e:
        raise SystemExit(
            f"Failed to open Rekordbox database: {e}\nMake sure Rekordbox is closed."
        ) from e

    try:
        db_path = Path(db.engine.url.database)
    except Exception:
        db_path = Path(os.environ.get("APPDATA", "")) / "Pioneer" / "rekordbox" / "master.db"

    if not args.dry_run:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.with_name(f"master_backup_{ts}.db")
        try:
            shutil.copy2(db_path, backup_path)
            print(f"[backup] Saved to: {backup_path}")
        except Exception as e:
            print(f"[backup] Warning - could not create backup: {e}")

    exact_index, stem_index, norm_index = build_target_index(target_root, extensions)

    contents = db.get_content().filter_by(rb_local_deleted=0).all()
    total = len(contents)
    print(f"[db] Found {total:,} track rows.")

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
    multi_match_log = []
    missing_log = []

    id_filter = None
    if args.ids:
        id_filter = {i.strip() for i in args.ids.split(",")}

    for content in contents:
        if id_filter is not None and content.ID not in id_filter:
            already_ok += 1
            continue

        raw_path = content.FolderPath or ""
        plain_path = normalize_path(raw_path)

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
            prefer_ext,
        )

        if len(matches) == 1:
            new_path = matches[0]
            new_path_stored = new_path.replace("\\", "/")

            if args.dry_run:
                print(f"[dry-run] [{match_type}]\n  {plain_path}\n  -> {new_path}")
            else:
                actual_size = os.path.getsize(new_path)
                actual_type = EXT_TO_FILETYPE.get(Path(new_path).suffix.lower(), 6)
                content.FolderPath = new_path_stored
                content.OrgFolderPath = new_path_stored
                content.FileType = actual_type
                content.FileSize = actual_size
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

    if not args.dry_run:
        db.commit()

    dry_tag = "  (dry-run)" if args.dry_run else ""
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Total tracks in DB               : {total:,}")
    print(f"  Already OK (skipped)             : {already_ok:,}")
    print(f"  Updated - exact filename         : {updated_exact:,}{dry_tag}")
    print(f"  Updated - Title-Artist match     : {updated_title_art:,}{dry_tag}")
    print(f"  Updated - Artist-Title match     : {updated_art_title:,}{dry_tag}")
    print(f"  Updated - prefix stripped        : {updated_prefix:,}{dry_tag}")
    print(f"  Updated - title substring        : {updated_substring:,}{dry_tag}")
    print(f"  Updated - title partial match    : {updated_partial:,}{dry_tag}")
    print(f"  Updated - fuzzy normalized       : {updated_fuzzy:,}{dry_tag}")
    print(f"  Updated - TOTAL                  : {updated:,}{dry_tag}")
    print(f"  Skipped (multiple hits)          : {skipped_multi:,}")
    print(f"  Still missing                    : {still_missing:,}")

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
        "--prefer-ext",
        metavar="EXT",
        default="flac",
        help="Preferred extension for matching (default: flac)",
    )
    parser.add_argument(
        "--extensions", metavar="LIST", help="Comma-separated audio extensions to index"
    )
    parser.add_argument("--ids", metavar="ID_LIST", help="Comma-separated track IDs to process")

    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
