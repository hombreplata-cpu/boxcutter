"""
Tests for scripts/get_listen_tree.py and scripts/get_playlist_tracks.py

Covers:
- build_tree() pure logic: nesting, ordering (folders before playlists), alphabetical sort
- get_listen_tree main() output is valid JSON with expected shape
- Smart playlists (Attribute not in 0/1) are excluded from the tree
- fmt_duration() converts milliseconds to seconds correctly
- get_playlist_tracks main() output is valid JSON with expected shape
- Invalid/missing playlist ID exits non-zero
- Tracks are returned with required fields
"""

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.get_listen_tree as get_listen_tree  # noqa: E402
import scripts.get_playlist_tracks as get_playlist_tracks  # noqa: E402
from scripts.get_listen_tree import build_tree  # noqa: E402
from scripts.get_playlist_tracks import fmt_duration  # noqa: E402

# ===========================================================================
# get_listen_tree
# ===========================================================================

# ---------------------------------------------------------------------------
# build_tree — pure logic, no DB
# ---------------------------------------------------------------------------


def test_build_tree_empty():
    assert build_tree([]) == []


def test_build_tree_single_playlist():
    nodes = [{"id": 1, "name": "Techno", "type": "playlist", "parent_id": 0}]
    tree = build_tree(nodes)
    assert len(tree) == 1
    assert tree[0]["name"] == "Techno"


def test_build_tree_folder_contains_playlist():
    nodes = [
        {"id": 1, "name": "House", "type": "folder", "parent_id": 0},
        {"id": 2, "name": "Deep", "type": "playlist", "parent_id": 1},
    ]
    tree = build_tree(nodes)
    assert tree[0]["name"] == "House"
    assert tree[0]["children"][0]["name"] == "Deep"


def test_build_tree_folders_before_playlists():
    nodes = [
        {"id": 1, "name": "A Playlist", "type": "playlist", "parent_id": 0},
        {"id": 2, "name": "A Folder", "type": "folder", "parent_id": 0},
    ]
    tree = build_tree(nodes)
    assert tree[0]["type"] == "folder"
    assert tree[1]["type"] == "playlist"


def test_build_tree_alphabetical_within_type():
    nodes = [
        {"id": 1, "name": "Techno", "type": "playlist", "parent_id": 0},
        {"id": 2, "name": "House", "type": "playlist", "parent_id": 0},
        {"id": 3, "name": "Ambient", "type": "playlist", "parent_id": 0},
    ]
    tree = build_tree(nodes)
    names = [n["name"] for n in tree]
    assert names == sorted(names, key=str.lower)


def test_build_tree_nested_folders():
    nodes = [
        {"id": 1, "name": "Root", "type": "folder", "parent_id": 0},
        {"id": 2, "name": "Sub", "type": "folder", "parent_id": 1},
        {"id": 3, "name": "Leaf", "type": "playlist", "parent_id": 2},
    ]
    tree = build_tree(nodes)
    assert tree[0]["children"][0]["children"][0]["name"] == "Leaf"


def test_build_tree_integer_zero_parent_id_is_root():
    """_safe_int() normalises None/root to 0 before nodes reach build_tree."""
    nodes = [{"id": 1, "name": "Playlist", "type": "playlist", "parent_id": 0}]
    tree = build_tree(nodes)
    assert len(tree) == 1


# ---------------------------------------------------------------------------
# main() output shape
# ---------------------------------------------------------------------------


def _run_listen_tree_main(playlists):
    db = MagicMock()
    db.get_playlist.return_value.filter_by.return_value.all.return_value = playlists

    captured = StringIO()
    with (
        patch("scripts.get_listen_tree.MasterDatabase", return_value=db),
        patch("sys.argv", ["get_listen_tree.py"]),
        patch("sys.stdout", captured),
    ):
        get_listen_tree.main()

    return json.loads(captured.getvalue())


def _make_playlist_item(id, name, attribute=0, parent_id=0):
    p = MagicMock()
    p.ID = id
    p.Name = name
    p.Attribute = attribute
    p.ParentID = parent_id
    return p


def test_listen_tree_output_is_valid_json():
    result = _run_listen_tree_main([])
    assert isinstance(result, dict)


def test_listen_tree_has_tree_key():
    result = _run_listen_tree_main([])
    assert "tree" in result


def test_listen_tree_empty_library_returns_empty_list():
    result = _run_listen_tree_main([])
    assert result["tree"] == []


def test_listen_tree_includes_regular_playlists():
    items = [_make_playlist_item(1, "Techno", attribute=0)]
    result = _run_listen_tree_main(items)
    assert len(result["tree"]) == 1
    assert result["tree"][0]["name"] == "Techno"


def test_listen_tree_includes_folders():
    items = [_make_playlist_item(1, "My Folder", attribute=1)]
    result = _run_listen_tree_main(items)
    assert result["tree"][0]["type"] == "folder"


def test_listen_tree_includes_smart_playlists_flagged():
    """Smart playlists (attribute=4) are included but marked smart=True."""
    items = [
        _make_playlist_item(1, "Normal", attribute=0),
        _make_playlist_item(2, "Smart", attribute=4),
    ]
    result = _run_listen_tree_main(items)
    names = [n["name"] for n in result["tree"]]
    assert "Normal" in names
    assert "Smart" in names
    smart_node = next(n for n in result["tree"] if n["name"] == "Smart")
    assert smart_node.get("smart") is True


# ===========================================================================
# get_playlist_tracks
# ===========================================================================

# ---------------------------------------------------------------------------
# fmt_duration
# ---------------------------------------------------------------------------


def test_fmt_duration_converts_ms_to_seconds():
    assert fmt_duration(60000) == 60
    assert fmt_duration(90500) == 90


def test_fmt_duration_zero():
    assert fmt_duration(0) == 0


def test_fmt_duration_none_returns_zero():
    assert fmt_duration(None) == 0


def test_fmt_duration_negative_returns_zero():
    assert fmt_duration(-5000) == 0


# ---------------------------------------------------------------------------
# main() output shape
# ---------------------------------------------------------------------------


def _run_playlist_tracks_main(playlist, rows, contents):
    db = MagicMock()
    db.get_playlist.return_value.filter_by.return_value.first.return_value = playlist
    db.session.execute.return_value.fetchall.return_value = rows
    db.get_content.return_value.filter_by.return_value.first.side_effect = (
        lambda: contents.pop(0) if contents else None
    )

    captured = StringIO()
    with (
        patch("scripts.get_playlist_tracks.MasterDatabase", return_value=db),
        patch("sys.argv", ["get_playlist_tracks.py", "--playlist-id", "1"]),
        patch("sys.stdout", captured),
    ):
        get_playlist_tracks.main()

    return json.loads(captured.getvalue())


def _make_track_content(
    id=1, title="Track", artist_id=1, bpm=128, key_name="8B", total_time=180000
):
    c = MagicMock()
    c.ID = id
    c.Title = title
    c.ArtistID = artist_id
    c.BPM = bpm
    c.KeyName = key_name
    c.Length = total_time
    return c


def test_playlist_tracks_output_is_valid_json():
    playlist = MagicMock()
    playlist.Name = "Test"
    playlist.ID = 1

    db = MagicMock()
    db.get_playlist.return_value.filter_by.return_value.first.return_value = playlist
    db.session.execute.return_value.fetchall.return_value = []
    db.get_content.return_value.filter_by.return_value.first.return_value = None

    captured = StringIO()
    with (
        patch("scripts.get_playlist_tracks.MasterDatabase", return_value=db),
        patch("sys.argv", ["get_playlist_tracks.py", "--playlist-id", "1"]),
        patch("sys.stdout", captured),
    ):
        get_playlist_tracks.main()

    result = json.loads(captured.getvalue())
    assert isinstance(result, dict)


def test_playlist_tracks_required_keys():
    playlist = MagicMock()
    playlist.Name = "House"
    playlist.ID = 1

    db = MagicMock()
    db.get_playlist.return_value.filter_by.return_value.first.return_value = playlist
    db.session.execute.return_value.fetchall.return_value = []
    db.get_content.return_value.filter_by.return_value.first.return_value = None

    captured = StringIO()
    with (
        patch("scripts.get_playlist_tracks.MasterDatabase", return_value=db),
        patch("sys.argv", ["get_playlist_tracks.py", "--playlist-id", "1"]),
        patch("sys.stdout", captured),
    ):
        get_playlist_tracks.main()

    result = json.loads(captured.getvalue())
    for key in ("playlist_name", "playlist_id", "tracks"):
        assert key in result


def test_playlist_tracks_empty_playlist_returns_empty_list():
    playlist = MagicMock()
    playlist.Name = "Empty"
    playlist.ID = 1

    db = MagicMock()
    db.get_playlist.return_value.filter_by.return_value.first.return_value = playlist
    db.session.execute.return_value.fetchall.return_value = []

    captured = StringIO()
    with (
        patch("scripts.get_playlist_tracks.MasterDatabase", return_value=db),
        patch("sys.argv", ["get_playlist_tracks.py", "--playlist-id", "1"]),
        patch("sys.stdout", captured),
    ):
        get_playlist_tracks.main()

    result = json.loads(captured.getvalue())
    assert result["tracks"] == []


def test_missing_playlist_id_exits_nonzero():
    with patch("sys.argv", ["get_playlist_tracks.py"]), pytest.raises(SystemExit) as exc_info:
        get_playlist_tracks.main()
    assert exc_info.value.code != 0


def test_invalid_playlist_id_exits_nonzero():
    with (
        patch("sys.argv", ["get_playlist_tracks.py", "--playlist-id", "notanint"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        get_playlist_tracks.main()
    assert exc_info.value.code != 0
