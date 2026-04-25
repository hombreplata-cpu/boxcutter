"""
get_playlist_tracks.py — Print tracks in a Rekordbox playlist as JSON to stdout.
"""

import contextlib
import json
import sys

from pyrekordbox import Rekordbox6Database as MasterDatabase
from sqlalchemy import text


def fmt_duration(val):
    """Return track length in seconds.

    Rekordbox-analyzed tracks store Length in seconds.
    Tracks added by our script stored Length in ms (int(info.length * 1000)).
    Values >= 10000 are unambiguously ms; divide those to get seconds.
    """
    try:
        val = int(val)
        if val <= 0:
            return 0
        return val // 1000 if val >= 10000 else val
    except Exception:
        return 0


def main():
    db_path = None
    playlist_id = None
    args = list(sys.argv[1:])
    while args:
        arg = args.pop(0)
        if arg == "--db-path" and args:
            db_path = args.pop(0) or None
        elif arg == "--playlist-id" and args:
            playlist_id = args.pop(0)

    if not playlist_id:
        print("--playlist-id required", file=sys.stderr)
        sys.exit(1)

    all_tracks_mode = playlist_id == "all"
    if not all_tracks_mode and not playlist_id.lstrip("-").isdigit():
        # Keep as string — Rekordbox stores IDs as strings internally
        print("--playlist-id must be an integer", file=sys.stderr)
        sys.exit(1)

    try:
        db = MasterDatabase(path=db_path)

        def _build_track(content):
            artist_name = ""
            if content.ArtistID:
                artist = db.get_artist().filter_by(ID=content.ArtistID).first()
                if artist:
                    artist_name = artist.Name or ""
            bpm = None
            if content.BPM:
                with contextlib.suppress(Exception):
                    raw = float(content.BPM)
                    # Rekordbox stores BPM × 100 (128 BPM → 12800).
                    # Values > 500 are unambiguously × 100 storage.
                    divided = raw / 100 if raw > 500 else raw
                    bpm = int(divided) if divided == int(divided) else round(divided, 1)
            try:
                raw_rating = content.Rating
                rating = int(raw_rating) if raw_rating is not None else 0
            except (TypeError, ValueError):
                rating = 0
            return {
                "id": content.ID,
                "title": content.Title or "",
                "artist": artist_name,
                "bpm": bpm,
                "key": content.KeyName or "",
                "duration": fmt_duration(content.Length),
                "rating": rating,
            }

        if all_tracks_mode:
            rows = db.session.execute(
                text("SELECT ID FROM DjmdContent WHERE rb_local_deleted = 0 ORDER BY Title")
            ).fetchall()
            tracks = []
            for (content_id,) in rows:
                content = db.get_content().filter_by(ID=content_id).first()
                if content:
                    tracks.append(_build_track(content))
            print(
                json.dumps({"playlist_name": "All Tracks", "playlist_id": "all", "tracks": tracks})
            )
        else:
            playlist = db.get_playlist().filter_by(ID=playlist_id).first()
            if not playlist:
                print(f"Playlist {playlist_id} not found", file=sys.stderr)
                sys.exit(1)

            is_smart = getattr(playlist, "Attribute", None) == 4

            if is_smart:
                smart_xml = getattr(playlist, "SmartList", None)
                if not smart_xml:
                    print(
                        json.dumps(
                            {
                                "playlist_name": playlist.Name,
                                "playlist_id": playlist_id,
                                "tracks": [],
                                "smart_unavailable": True,
                            }
                        )
                    )
                    return
                from pyrekordbox.db6.smartlist import SmartList  # noqa: PLC0415

                sl = SmartList()
                sl.parse(smart_xml)
                contents = (
                    db.get_content().filter_by(rb_local_deleted=0).filter(sl.filter_clause()).all()
                )
                tracks = [_build_track(c) for c in contents]
            else:
                rows = db.session.execute(
                    text(
                        "SELECT ContentID FROM DjmdSongPlaylist "
                        "WHERE PlaylistID = :pid AND rb_local_deleted = 0 ORDER BY TrackNo"
                    ),
                    {"pid": playlist_id},
                ).fetchall()
                tracks = []
                for (content_id,) in rows:
                    content = db.get_content().filter_by(ID=content_id, rb_local_deleted=0).first()
                    if content:
                        tracks.append(_build_track(content))

            print(
                json.dumps(
                    {
                        "playlist_name": playlist.Name,
                        "playlist_id": playlist_id,
                        "tracks": tracks,
                    }
                )
            )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
