"""
strip_comment_urls.py

Crawl directories for music files and remove URLs from comment tags,
leaving all other comment content intact.

Supported formats:
    MP3   — ID3 COMM frames
    FLAC  — Vorbis COMMENT / DESCRIPTION fields
    WAV   — embedded ID3 COMM frames
    AIFF  — embedded ID3 COMM frames
    ALAC/M4A — MP4 \\xa9cmt atom

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
import json
import re
import sys
from pathlib import Path

from utils import MUSIC_EXTENSIONS

try:
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, ID3NoHeaderError
    from mutagen.mp4 import MP4
except ImportError:
    print("ERROR: mutagen is not installed. Run:  pip install mutagen")
    sys.exit(1)


# Matches http://, https://, ftp://, and bare www. URLs
URL_PATTERN = re.compile(r"(https?://|ftp://|www\.)\S+", re.IGNORECASE)

# Known download/streaming service names used in injected boilerplate
_SERVICES = (
    r"(?:bandcamp|beatport|traxsource|juno(?:\s+download)?|bleep"
    r"|soundcloud|spotify|tidal|deezer|youtube|apple\s+music|amazon\s+music)"
)

# Conservative: each pattern is fully anchored so the ENTIRE line must match.
# Lines that mix boilerplate with other content are left alone.
BOILERPLATE_PATTERNS = [
    re.compile(rf"^visit\s+(?:our\s+|us\s+on\s+)?{_SERVICES}\b.*$", re.IGNORECASE),
    re.compile(rf"^download(?:ed)?\s+from\s+{_SERVICES}\b.*$", re.IGNORECASE),
    re.compile(rf"^(?:buy|purchase|get\s+it)\s+(?:on|at|from)\s+{_SERVICES}\b.*$", re.IGNORECASE),
    re.compile(rf"^available\s+(?:on|at)\s+{_SERVICES}\b.*$", re.IGNORECASE),
    re.compile(rf"^stream\s+(?:on|at)\s+{_SERVICES}\b.*$", re.IGNORECASE),
    re.compile(rf"^support\s+.{{0,30}}\s+on\s+{_SERVICES}\b.*$", re.IGNORECASE),
    re.compile(rf"^{_SERVICES}$", re.IGNORECASE),
]


def is_boilerplate_line(line: str) -> bool:
    """Return True if the entire stripped line matches a known boilerplate pattern."""
    stripped = line.strip()
    return any(p.match(stripped) for p in BOILERPLATE_PATTERNS)


def clean_text(text: str) -> str:
    """Strip URLs and drop whole boilerplate lines. Returns cleaned text (may be empty)."""
    cleaned = []
    for line in text.splitlines():
        line = URL_PATTERN.sub("", line).strip()
        if line and is_boilerplate_line(line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def needs_cleaning(text: str) -> bool:
    """Return True if text contains a URL or any whole-line boilerplate."""
    if URL_PATTERN.search(text):
        return True
    return any(is_boilerplate_line(line) for line in text.splitlines())


# Kept for backward compatibility
def strip_urls(text: str) -> str:
    return URL_PATTERN.sub("", text).strip()


def has_url(text: str) -> bool:
    return bool(URL_PATTERN.search(text))


# ---------------------------------------------------------------------------
# ID3 handling (MP3 — and WAV/AIFF which embed ID3 chunks)
# ---------------------------------------------------------------------------


def _process_id3(path: Path, write: bool) -> list:
    """Return list of dicts: {field, from_, to_} for each URL-containing COMM frame."""
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
            if needs_cleaning(text):
                cleaned = clean_text(text)
                new_texts.append(cleaned)
                changes.append({"field": key, "from_": text, "to_": cleaned})
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


def process_mp3(path: Path, write: bool) -> list:
    return _process_id3(path, write)


def process_wav_aiff(path: Path, write: bool) -> list:
    return _process_id3(path, write)


# ---------------------------------------------------------------------------
# FLAC handling (Vorbis comments — COMMENT field)
# ---------------------------------------------------------------------------


def process_flac(path: Path, write: bool) -> list:
    """Return list of dicts: {field, from_, to_} for each URL-containing tag."""
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
            if needs_cleaning(text):
                cleaned = clean_text(text)
                new_values.append(cleaned)
                changes.append({"field": field.upper(), "from_": text, "to_": cleaned})
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
# MP4 handling (ALAC / M4A — \xa9cmt atom)
# ---------------------------------------------------------------------------


def process_mp4(path: Path, write: bool) -> list:
    """Return list of dicts: {field, from_, to_} for each URL-containing comment atom."""
    changes = []
    try:
        audio = MP4(str(path))
    except Exception as e:
        print(f"  [WARN] Could not read MP4 tags: {path}  ({e})")
        return changes

    tags = audio.tags
    if tags is None:
        return changes

    key = "\xa9cmt"
    values = tags.get(key, [])
    new_values = []
    modified = False

    for text in values:
        if isinstance(text, str) and needs_cleaning(text):
            cleaned = clean_text(text)
            new_values.append(cleaned)
            changes.append({"field": "COMMENT", "from_": text, "to_": cleaned})
            modified = True
        else:
            new_values.append(text)

    if modified:
        tags[key] = new_values
        if write:
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
    total_errors = 0
    modified_files = []

    mode_label = "WRITE" if write else "DRY RUN"
    print(f"\n=== strip_comment_urls  [{mode_label}] ===\n")

    for root_str in directories:
        root = Path(root_str)
        if not root.exists():
            print(f"[SKIP] Directory not found: {root}\n")
            continue

        print(f"Scanning: {root}")
        _scan_i = 0

        for path in root.rglob("*"):
            if not path.is_file():
                continue

            suffix = path.suffix.lower()
            if suffix not in MUSIC_EXTENSIONS:
                continue

            _scan_i += 1
            if _scan_i % 100 == 0:
                print(
                    f'%%PROGRESS%% {{"current": {_scan_i}, "label": "Scanning music files"}}',
                    flush=True,
                )

            total_files += 1

            if suffix == ".mp3":
                changes = process_mp3(path, write)
            elif suffix == ".flac":
                changes = process_flac(path, write)
            elif suffix in (".wav", ".aif", ".aiff"):
                changes = process_wav_aiff(path, write)
            elif suffix in (".m4a", ".alac"):
                changes = process_mp4(path, write)
            else:
                continue

            if changes:
                total_changed += 1
                print(f"\n  {path}")
                for c in changes:
                    from_short = c["from_"][:80] + ("..." if len(c["from_"]) > 80 else "")
                    print(f"  [{c['field']}] '{from_short}'\n        -> '{c['to_']}'")
                modified_files.append(
                    {
                        "path": str(path),
                        "changes": [
                            {"field": c["field"], "from": c["from_"][:100], "to": c["to_"]}
                            for c in changes
                        ],
                    }
                )

    print(f"\n{'=' * 50}")
    print(f"Files scanned : {total_files}")
    print(
        f"Files modified: {total_changed}  ({'written' if write else 'dry run -- no changes written'})"
    )
    if not write and total_changed:
        print("\nRe-run with --write to apply changes.")
    print()

    print("%%REPORT_START%%")
    print(
        json.dumps(
            {
                "tool": "strip_comments",
                "dry_run": not write,
                "summary": {
                    "scanned": total_files,
                    "modified": total_changed,
                    "errors": total_errors,
                },
                "modified_files": modified_files,
            }
        )
    )
    print("%%REPORT_END%%")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Remove URLs from music file comment tags (MP3, FLAC, WAV, AIFF, ALAC/M4A)."
    )
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
