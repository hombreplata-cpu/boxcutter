"""
inspect_mytag.py — Dumps djmdMyTag and djmdSongMyTag schema + sample rows.

Run this ONCE to understand the My Tag DB structure before implementing
the My Tag editor tool.

Usage:
    python inspect_mytag.py [--db-path /path/to/master.db]
"""

import json
import sys

from pyrekordbox import Rekordbox6Database as MasterDatabase
from sqlalchemy import inspect, text
from utils import configure_io


def dump_table(engine, table_name):
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if table_name not in tables:
        print(f"  [NOT FOUND] '{table_name}' does not exist in this DB.")
        print("  Available tables containing 'tag' (case-insensitive):")
        for t in sorted(tables):
            if "tag" in t.lower():
                print(f"    {t}")
        return

    cols = inspector.get_columns(table_name)
    print("  Columns:")
    for c in cols:
        print(f"    {c['name']:30s} {str(c['type'])}")

    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT * FROM {table_name} LIMIT 10")).fetchall()  # noqa: S608  # nosec B608 — table_name is caller-controlled (hardcoded)
    print(f"\n  Sample rows ({min(len(rows), 10)} of up to 10):")
    if not rows:
        print("    (empty table)")
    for row in rows:
        print(f"    {dict(row._mapping)}")


def main():
    configure_io()
    db_path = None
    if len(sys.argv) == 3 and sys.argv[1] == "--db-path":
        db_path = sys.argv[2] or None

    try:
        db = MasterDatabase(path=db_path)
        engine = db.engine

        for table in ["djmdMyTag", "djmdSongMyTag"]:
            print(f"\n{'=' * 60}")
            print(f"TABLE: {table}")
            print("=" * 60)
            dump_table(engine, table)

        # Also show total counts if tables exist
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"\n{'=' * 60}")
        print("COUNTS")
        print("=" * 60)
        with engine.connect() as conn:
            for table in ["djmdMyTag", "djmdSongMyTag"]:
                if table in tables:
                    count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()  # noqa: S608  # nosec B608 — table is hardcoded in the loop above
                    print(f"  {table}: {count} rows")

    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
