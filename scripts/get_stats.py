"""
get_stats.py — Print Rekordbox library stats as JSON to stdout.

Called by app.py's /api/stats endpoint as a subprocess so that
pyrekordbox is imported in the same Python environment that runs all
other BoxCutter scripts.

Output: JSON object with track_count, file_types (name->count), library_size_bytes.
Errors: non-zero exit code + error message on stderr.
"""

import argparse
import json
import sys
from pathlib import Path

from pyrekordbox import Rekordbox6Database as MasterDatabase
from utils import configure_io

# Fallback map used when FolderPath is absent
FILETYPE_NAMES = {
    1: "MP3",
    4: "AAC",
    5: "WAV",
    6: "FLAC",
    7: "AIFF",
    8: "OGG",
    9: "WMA",
    10: "MP4",
    11: "ALAC",
}

# Primary map: derive label from the actual file extension in FolderPath.
# This is more reliable than FileType, which can be stale after a format conversion.
EXT_TO_LABEL = {
    ".mp3": "MP3",
    ".m4a": "AAC",
    ".wav": "WAV",
    ".flac": "FLAC",
    ".aif": "AIFF",
    ".aiff": "AIFF",
    ".ogg": "OGG",
    ".wma": "WMA",
    ".mp4": "MP4",
    ".alac": "ALAC",
}


def main():
    configure_io()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="", help="Path to master.db")
    args = parser.parse_args()
    db_path = args.db_path or None

    try:
        db = MasterDatabase(path=db_path)
        contents = db.get_content().filter_by(rb_local_deleted=0).all()

        file_types: dict[str, int] = {}
        library_size_bytes = 0

        for c in contents:
            if c.FolderPath:
                ext = Path(c.FolderPath).suffix.lower()
                name = EXT_TO_LABEL.get(ext, ext.lstrip(".").upper() or f"Type {c.FileType}")
            else:
                name = FILETYPE_NAMES.get(c.FileType, f"Type {c.FileType}")
            file_types[name] = file_types.get(name, 0) + 1
            if c.FileSize:
                library_size_bytes += c.FileSize

        played = sorted(
            (c for c in contents if c.DJPlayCount),
            key=lambda c: c.DJPlayCount,
            reverse=True,
        )[:20]
        top_played = [
            {
                "title": c.Title or "",
                "artist": c.Artist.Name if c.Artist else "",
                "play_count": c.DJPlayCount,
            }
            for c in played
        ]

        low_bitrate = sorted(
            (c for c in contents if c.BitRate and 0 < c.BitRate < 320),
            key=lambda c: c.BitRate,
        )
        low_bitrate_tracks = [
            {
                "title": c.Title or "",
                "artist": c.Artist.Name if c.Artist else "",
                "bitrate": c.BitRate,
                "path": c.FolderPath or "",
            }
            for c in low_bitrate
        ]

        result = {
            "track_count": len(contents),
            "file_types": file_types,
            "library_size_bytes": library_size_bytes,
            "top_played": top_played,
            "low_bitrate_tracks": low_bitrate_tracks,
        }
        print(json.dumps(result))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
