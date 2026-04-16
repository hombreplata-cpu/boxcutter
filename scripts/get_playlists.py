"""
get_playlists.py — Print Rekordbox playlists as JSON to stdout.

Called by app.py's /api/playlists endpoint as a subprocess so that
pyrekordbox is imported in the same Python environment that runs all
other rekordbox-tools scripts.

Output: JSON array of {"id": str, "name": str} objects, one per line.
Errors: non-zero exit code + error message on stderr.
"""

import json
import sys

from pyrekordbox import Rekordbox6Database as MasterDatabase


def main():
    db_path = None
    if len(sys.argv) == 3 and sys.argv[1] == "--db-path":
        db_path = sys.argv[2] or None

    try:
        db = MasterDatabase(path=db_path)
        # Attribute 0 = normal playlist; 1 = folder; 4 = smart playlist
        playlists = (
            db.get_playlist().filter_by(Attribute=0, rb_local_deleted=0).order_by("Name").all()
        )
        result = [{"id": str(p.ID), "name": p.Name} for p in playlists]
        print(json.dumps(result))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
