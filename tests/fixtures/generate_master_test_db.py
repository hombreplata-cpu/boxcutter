"""Generate a minimal unencrypted master.db for integration tests.

Output: tests/fixtures/master_test.db  (gitignored)

Why this exists
---------------
``tests/test_script_integration.py`` is the only suite that exercises
BoxCutter's scripts against a real ``pyrekordbox.MasterDatabase`` rather
than mocks. Historically it was gated on a personal Rekordbox backup
(SQLCipher-encrypted, key extractable only from an installed Rekordbox)
and skipped silently in CI on every runner — so script-write paths had
zero CI coverage on Mac.

This generator produces an **unencrypted** SQLite file populated with
just enough rows to drive the existing integration tests. Two pyrekordbox
features make this work without needing Rekordbox installed:

1. ``pyrekordbox.db6.tables.Base.metadata.create_all(engine)`` builds
   the full schema (37 tables) from pyrekordbox's own ORM definitions.
2. ``Rekordbox6Database(path=..., unlock=False)`` opens a plain SQLite
   file directly — no SQLCipher key needed.

Test code monkeypatches ``Rekordbox6Database.__init__`` to default
``unlock=False`` for the duration of the integration tests so script
code (which constructs ``MasterDatabase`` with ``unlock=True`` in
production) reaches the unencrypted fixture without modification.

Run
---
    python tests/fixtures/generate_master_test_db.py

Idempotent — re-running overwrites the existing fixture. CI runs this
step before pytest in ``.github/workflows/ci.yml``; locally the
``_ensure_fixture_exists`` autouse fixture in
``tests/test_script_integration.py`` runs it on first pytest invocation
if the file is missing.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pyrekordbox.db6 import tables  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

# pyrekordbox's custom DateTime type — TypeDecorator that stores as TEXT
# but requires datetime input via .astimezone() in process_bind_param.
# Detected at column-fill time so the helper doesn't supply "" for it.
_PyrekDateTime = tables.DateTime

FIXTURE_PATH = Path(__file__).parent / "master_test.db"

# A stable epoch-ish default for date columns. pyrekordbox stores these as
# TEXT but its SQLAlchemy type custom-processes them with .astimezone(),
# so we must supply real datetimes — not empty strings.
_DEFAULT_DT = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _make_with_defaults(cls: type, **values: Any) -> Any:
    """Construct an ORM row, filling every NOT NULL column not given an
    explicit value with a type-appropriate default.

    pyrekordbox's tables have many NOT NULL columns with no SQL/SQLAlchemy
    default — Rekordbox itself fills them when the row is created via the
    real app. For tests we just need the row to satisfy schema constraints;
    the default value's content doesn't matter as long as the type is right
    (int → 0, string-ish → "").

    Caller-supplied values in ``values`` always win.
    """
    filled: dict[str, Any] = dict(values)
    table = cls.__table__  # type: ignore[attr-defined]
    for col in table.columns:
        if col.name in filled:
            continue
        if col.nullable:
            continue
        if col.default is not None or col.server_default is not None:
            # SQLAlchemy will materialise the default at insert time.
            continue
        # pyrekordbox's custom DateTime is a TypeDecorator over TEXT; it
        # requires datetime input (calls .astimezone() in
        # process_bind_param). Detect via the Python class — str(col.type)
        # is just "TEXT" which would mislead us into supplying "".
        if isinstance(col.type, _PyrekDateTime):
            filled[col.name] = _DEFAULT_DT
            continue
        type_str = str(col.type).upper()
        if any(num_t in type_str for num_t in ("INT", "BIGINT", "SMALLINT", "FLOAT", "NUMERIC")):
            filled[col.name] = 0
        else:
            filled[col.name] = ""
    return cls(**filled)


def main() -> int:
    if FIXTURE_PATH.exists():
        FIXTURE_PATH.unlink()

    engine = create_engine(f"sqlite:///{FIXTURE_PATH}")
    tables.Base.metadata.create_all(engine)

    with Session(engine) as session:
        # Three artists. Each track in the seed set links to one of these
        # via ArtistID — required by tests that exercise the
        # ``track.Artist.Name`` relationship (e.g. relocate's match-by-
        # Artist-Title pass).
        artists = [
            _make_with_defaults(tables.DjmdArtist, ID=str(i + 1), Name=f"Test Artist {i + 1}")
            for i in range(3)
        ]

        # Three tracks with non-empty Title + linked Artist + a sentinel
        # FolderPath that won't exist on disk (relocate / cleanup tests
        # build their own real files in tmp_path and rewrite paths there).
        contents = [
            _make_with_defaults(
                tables.DjmdContent,
                ID=str(i + 1),
                Title=f"Test Track {i + 1}",
                ArtistID=str(i + 1),
                FolderPath=f"/nonexistent/test_track_{i + 1}.flac",
                FileType=6,  # FLAC, matches the sentinel suffix above
                rb_local_deleted=0,
            )
            for i in range(3)
        ]

        # AgentRegistry needs a localUpdateCount row — pyrekordbox's
        # commit() reads reg.int_1 from this row to autoincrement the
        # global update sequence number. Without it, db.commit() raises
        # AttributeError. Seed with int_1=0 so increments start clean.
        registry_row = _make_with_defaults(
            tables.AgentRegistry, registry_id="localUpdateCount", int_1=0
        )

        # One regular playlist (Attribute=0). Required by add_new.run which
        # calls db.get_playlist(ID=...) before deciding what to add — without
        # this, integration tests that exercise add_new fail at the playlist
        # lookup, before reaching the code path under test. Issue #109.
        playlist = _make_with_defaults(
            tables.DjmdPlaylist,
            ID="1",
            Name="Test Playlist",
            Attribute=0,
            ParentID="root",
        )

        session.add_all(artists)
        session.add_all(contents)
        session.add(registry_row)
        session.add(playlist)
        session.commit()

    engine.dispose()
    print(f"[generate] wrote {FIXTURE_PATH} ({FIXTURE_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
