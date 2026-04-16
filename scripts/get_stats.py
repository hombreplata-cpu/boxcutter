"""
get_stats.py — Print Rekordbox library stats as JSON to stdout.

Called by app.py's /api/stats endpoint as a subprocess so that
pyrekordbox is imported in the same Python environment that runs all
other rekordbox-tools scripts.

Output: JSON object with track_count, file_types (name->count), library_size_bytes.
Errors: non-zero exit code + error message on stderr.
"""

import json
import sys

from pyrekordbox import Rekordbox6Database as MasterDatabase

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


def main():
    db_path = None
    if len(sys.argv) == 3 and sys.argv[1] == "--db-path":
        db_path = sys.argv[2] or None

    try:
        db = MasterDatabase(path=db_path)
        contents = db.get_content().filter_by(rb_local_deleted=0).all()

        file_types: dict[str, int] = {}
        library_size_bytes = 0

        for c in contents:
            name = FILETYPE_NAMES.get(c.FileType, f"Type {c.FileType}")
            file_types[name] = file_types.get(name, 0) + 1
            if c.FileSize:
                library_size_bytes += c.FileSize

        result = {
            "track_count": len(contents),
            "file_types": file_types,
            "library_size_bytes": library_size_bytes,
        }
        print(json.dumps(result))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
