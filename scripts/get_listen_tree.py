"""
get_listen_tree.py — Print Rekordbox playlist/folder tree as JSON to stdout.
"""

import argparse
import json
import sys

from pyrekordbox import Rekordbox6Database as MasterDatabase
from utils import configure_io


def _safe_int(val, default=0):
    """Convert val to int; return default for None, 'root', or other non-numeric strings."""
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


def build_tree(nodes, parent_id=0):
    children = []
    for node in nodes:
        if node["parent_id"] == parent_id:
            if node["type"] == "folder":
                node["children"] = build_tree(nodes, node["id"])
            children.append(node)
    # Folders before playlists; alphabetical within each group
    children.sort(key=lambda x: (0 if x["type"] == "folder" else 1, x["name"].lower()))
    return children


def main():
    configure_io()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default="", help="Path to master.db")
    args = parser.parse_args()
    db_path = args.db_path or None

    try:
        db = MasterDatabase(path=db_path)
        all_items = db.get_playlist().filter_by(rb_local_deleted=0).all()

        nodes = []
        for p in all_items:
            if p.Attribute not in (0, 1, 4):  # 0=playlist, 1=folder, 4=intelligent playlist
                continue
            nodes.append(
                {
                    "id": _safe_int(p.ID),
                    "name": p.Name,
                    "type": "folder" if p.Attribute == 1 else "playlist",
                    "parent_id": _safe_int(p.ParentID),
                    "smart": p.Attribute == 4,
                }
            )

        print(json.dumps({"tree": build_tree(nodes)}))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
