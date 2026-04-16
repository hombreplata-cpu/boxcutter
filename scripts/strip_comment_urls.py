"""
strip_comment_urls.py

Crawl directories for MP3/FLAC files and remove URLs from comment tags,
leaving all other comment content intact.

Requirements:
    pip install mutagen

Usage:
    # Dry run (preview only, no changes written):
    python strip_comment_urls.py "D:\\Music"

    # Write changes:
    python strip_comment_urls.py "D:\\Music" --write

    # Multiple directories:
    python strip_comment_urls.py "D:\\Music" "E:\\MoreMusic" --write
"""

import argparse
import re
import sys
from pathlib import Path

try:
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, ID3NoHeaderError
except ImportError:
    print("ERROR: mutagen is not installed. Run:  pip install mutagen")
    sys.exit(1)


# Matches http://, https://, ftp://, and bare www. URLs
URL_PATTERN = re.compile(r"(https?://|ftp://|www\.)\S+", re.IGNORECASE)


def strip_urls(text: str) -> str:
    """Remove all URLs from a string. Returns stripped text (may be empty)."""
    return URL_PATTERN.sub("", text).strip()


def has_url(text: str) -> bool:
    return bool(URL_PATTERN.search(text))


# ---------------------------------------------------------------------------
# MP3 handling (ID3 tags — COMM frames)
# ---------------------------------------------------------------------------


def process_mp3(path: Path, write: bool) -> list:
    changes = []
    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        return changes
    except Exception as e:
        print(f"  [WARN] Could not read ID3 tags: {path}  ({e})")
        return changes

    modified = False
    comm_keys = [k for k in tags if k.startswith("COMM")]

    for key in comm_keys:
        frame = tags[key]
        original = frame.text
        new_texts = []
        frame_changed = False

        for text in original:
            if has_url(text):
                cleaned = strip_urls(text)
                new_texts.append(cleaned)
                changes.append(
                    f"  [{key}] '{text[:80]}{'...' if len(text) > 80 else ''}'"
                    f"\n        -> '{cleaned}'"
                )
                frame_changed = True
            else:
                new_texts.append(text)

        if frame_changed:
            frame.text = new_texts
            modified = True

    if modified and write:
        try:
            tags.save(str(path))
        except Exception as e:
            print(f"  [ERROR] Could not save {path}: {e}")

    return changes


# ---------------------------------------------------------------------------
# FLAC handling (Vorbis comments — COMMENT field)
# ---------------------------------------------------------------------------


def process_flac(path: Path, write: bool) -> list:
    changes = []
    try:
        audio = FLAC(str(path))
    except Exception as e:
        print(f"  [WARN] Could not read FLAC tags: {path}  ({e})")
        return changes

    modified = False

    for field in ("comment", "description"):
        values = audio.get(field, [])
        new_values = []
        field_changed = False

        for text in values:
            if has_url(text):
                cleaned = strip_urls(text)
                new_values.append(cleaned)
                changes.append(
                    f"  [{field.upper()}] '{text[:80]}{'...' if len(text) > 80 else ''}'"
                    f"\n             -> '{cleaned}'"
                )
                field_changed = True
            else:
                new_values.append(text)

        if field_changed:
            audio[field] = new_values
            modified = True

    if modified and write:
        try:
            audio.save()
        except Exception as e:
            print(f"  [ERROR] Could not save {path}: {e}")

    return changes


# ---------------------------------------------------------------------------
# Directory crawler
# ---------------------------------------------------------------------------


def crawl(directories, write):
    total_files = 0
    total_changed = 0

    mode_label = "WRITE" if write else "DRY RUN"
    print(f"\n=== strip_comment_urls  [{mode_label}] ===\n")

    for root_str in directories:
        root = Path(root_str)
        if not root.exists():
            print(f"[SKIP] Directory not found: {root}\n")
            continue

        print(f"Scanning: {root}")

        for path in root.rglob("*"):
            if not path.is_file():
                continue

            suffix = path.suffix.lower()
            if suffix not in (".mp3", ".flac"):
                continue

            total_files += 1

            changes = process_mp3(path, write) if suffix == ".mp3" else process_flac(path, write)

            if changes:
                total_changed += 1
                print(f"\n  {path}")
                for c in changes:
                    print(c)

    print(f"\n{'=' * 50}")
    print(f"Files scanned : {total_files}")
    print(
        f"Files modified: {total_changed}  ({'written' if write else 'dry run -- no changes written'})"
    )
    if not write and total_changed:
        print("\nRe-run with --write to apply changes.")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Remove URLs from MP3/FLAC comment tags.")
    parser.add_argument(
        "directories", nargs="+", help="One or more directories to crawl recursively."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually write changes. Without this flag the script is a dry run.",
    )
    args = parser.parse_args()
    crawl(args.directories, args.write)


if __name__ == "__main__":
    main()
