"""
get_playlists.py — Print Rekordbox playlists as JSON to stdout.

Called by app.py's /api/playlists endpoint as a subprocess so that
pyrekordbox is imported in the same Python environment that runs all
other BoxCutter scripts.

Output: JSON array of {"id": str, "name": str} objects, one per line.
Errors: non-zero exit code + error message on stderr.
"""

import argparse
import json
import sys

from pyrekordbox import Rekordbox6Database as MasterDatabase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="", help="Path to master.db")
    args = parser.parse_args()
    db_path = args.db_path or None

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
