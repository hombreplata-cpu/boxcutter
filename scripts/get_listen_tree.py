"""
get_listen_tree.py — Print Rekordbox playlist/folder tree as JSON to stdout.
"""

import json
import sys

from pyrekordbox import Rekordbox6Database as MasterDatabase


def build_tree(nodes, parent_id=0):
    children = []
    for node in nodes:
        if (node["parent_id"] or 0) == parent_id:
            if node["type"] == "folder":
                node["children"] = build_tree(nodes, node["id"])
            children.append(node)
    # Folders before playlists; alphabetical within each group
    children.sort(key=lambda x: (0 if x["type"] == "folder" else 1, x["name"].lower()))
    return children


def main():
    db_path = None
    if len(sys.argv) == 3 and sys.argv[1] == "--db-path":
        db_path = sys.argv[2] or None

    try:
        db = MasterDatabase(path=db_path)
        all_items = db.get_playlist().filter_by(rb_local_deleted=0).all()

        nodes = []
        for p in all_items:
            if p.Attribute not in (0, 1):  # skip smart playlists (4) and others
                continue
            nodes.append(
                {
                    "id": p.ID,
                    "name": p.Name,
                    "type": "folder" if p.Attribute == 1 else "playlist",
                    "parent_id": p.ParentID or 0,
                }
            )

        print(json.dumps({"tree": build_tree(nodes)}))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
