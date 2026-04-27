"""
get_track_path.py — Return file path and extension for a single track by ID.
"""

import json
import sys
from pathlib import Path

from pyrekordbox import Rekordbox6Database as MasterDatabase
from utils import configure_io


def main():
    configure_io()
    db_path = None
    track_id = None
    args = list(sys.argv[1:])
    while args:
        arg = args.pop(0)
        if arg == "--db-path" and args:
            db_path = args.pop(0) or None
        elif arg == "--track-id" and args:
            track_id = args.pop(0)

    if not track_id:
        print("--track-id required", file=sys.stderr)
        sys.exit(1)

    try:
        track_id = int(track_id)
    except ValueError:
        print("--track-id must be an integer", file=sys.stderr)
        sys.exit(1)

    try:
        db = MasterDatabase(path=db_path)
        content = db.get_content().filter_by(ID=track_id, rb_local_deleted=0).first()
        if not content or not content.FolderPath:
            print(f"Track {track_id} not found", file=sys.stderr)
            sys.exit(1)

        path = content.FolderPath
        ext = Path(path).suffix.lower()
        print(json.dumps({"path": path, "ext": ext}))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
