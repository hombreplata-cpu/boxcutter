"""
Tests for scripts/get_stats.py

Covers:
- Output is valid JSON
- Required top-level keys are always present
- file_types dict is populated from track data
- Empty library returns zeros, not an error
- top_played and low_bitrate_tracks are lists
- Low-bitrate threshold: tracks below 320 kbps appear, >= 320 do not
"""

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.get_stats as get_stats  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_content(
    folder_path,
    file_type=6,
    file_size=1024,
    bitrate=None,
    play_count=None,
    title="Track",
    artist_name="Artist",
):
    c = MagicMock()
    c.FolderPath = folder_path
    c.FileType = file_type
    c.FileSize = file_size
    c.BitRate = bitrate
    c.DJPlayCount = play_count
    c.Title = title
    artist = MagicMock()
    artist.Name = artist_name
    c.Artist = artist
    c.ArtistID = 1
    c.TotalTime = 200000
    return c


def _run_main_with_db(contents, db_path=None):
    """Patch MasterDatabase, capture stdout, run main(), return parsed JSON."""
    db = MagicMock()
    db.get_content.return_value.filter_by.return_value.all.return_value = contents

    argv = ["get_stats.py"]
    if db_path:
        argv += ["--db-path", db_path]

    captured = StringIO()
    with (
        patch("scripts.get_stats.MasterDatabase", return_value=db),
        patch("sys.argv", argv),
        patch("sys.stdout", captured),
    ):
        get_stats.main()

    return json.loads(captured.getvalue())


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


def test_output_is_valid_json():
    result = _run_main_with_db([])
    assert isinstance(result, dict)


def test_required_keys_present():
    result = _run_main_with_db([])
    for key in (
        "track_count",
        "file_types",
        "library_size_bytes",
        "top_played",
        "low_bitrate_tracks",
    ):
        assert key in result, f"Missing key: {key}"


def test_empty_library_returns_zeros():
    result = _run_main_with_db([])
    assert result["track_count"] == 0
    assert result["file_types"] == {}
    assert result["library_size_bytes"] == 0
    assert result["top_played"] == []
    assert result["low_bitrate_tracks"] == []


# ---------------------------------------------------------------------------
# track_count and library_size_bytes
# ---------------------------------------------------------------------------


def test_track_count_matches_content_count():
    contents = [
        _make_content("C:/Music/a.flac", file_size=500),
        _make_content("C:/Music/b.mp3", file_size=300),
    ]
    result = _run_main_with_db(contents)
    assert result["track_count"] == 2


def test_library_size_bytes_is_sum_of_filesizes():
    contents = [
        _make_content("C:/Music/a.flac", file_size=1000),
        _make_content("C:/Music/b.flac", file_size=2000),
    ]
    result = _run_main_with_db(contents)
    assert result["library_size_bytes"] == 3000


def test_none_filesize_does_not_crash():
    c = _make_content("C:/Music/a.flac", file_size=None)
    result = _run_main_with_db([c])
    assert result["library_size_bytes"] == 0


# ---------------------------------------------------------------------------
# file_types breakdown
# ---------------------------------------------------------------------------


def test_file_types_groups_by_extension():
    contents = [
        _make_content("C:/Music/a.flac"),
        _make_content("C:/Music/b.flac"),
        _make_content("C:/Music/c.mp3"),
    ]
    result = _run_main_with_db(contents)
    assert result["file_types"].get("FLAC") == 2
    assert result["file_types"].get("MP3") == 1


def test_file_types_uses_folder_path_extension():
    """Extension from FolderPath should take precedence over FileType integer."""
    contents = [_make_content("C:/Music/track.wav", file_type=99)]
    result = _run_main_with_db(contents)
    assert "WAV" in result["file_types"]


# ---------------------------------------------------------------------------
# low_bitrate_tracks
# ---------------------------------------------------------------------------


def test_low_bitrate_track_appears(tmp_path):
    contents = [_make_content("C:/Music/low.mp3", bitrate=128, title="Low Quality")]
    result = _run_main_with_db(contents)
    assert len(result["low_bitrate_tracks"]) == 1
    assert result["low_bitrate_tracks"][0]["bitrate"] == 128


def test_high_bitrate_track_excluded():
    contents = [_make_content("C:/Music/hi.flac", bitrate=320)]
    result = _run_main_with_db(contents)
    assert result["low_bitrate_tracks"] == []


def test_none_bitrate_not_included():
    contents = [_make_content("C:/Music/unknown.flac", bitrate=None)]
    result = _run_main_with_db(contents)
    assert result["low_bitrate_tracks"] == []


def test_low_bitrate_tracks_sorted_ascending():
    contents = [
        _make_content("C:/Music/a.mp3", bitrate=256, title="A"),
        _make_content("C:/Music/b.mp3", bitrate=128, title="B"),
        _make_content("C:/Music/c.mp3", bitrate=192, title="C"),
    ]
    result = _run_main_with_db(contents)
    bitrates = [t["bitrate"] for t in result["low_bitrate_tracks"]]
    assert bitrates == sorted(bitrates)


# ---------------------------------------------------------------------------
# top_played
# ---------------------------------------------------------------------------


def test_top_played_only_includes_played_tracks():
    contents = [
        _make_content("C:/Music/a.mp3", play_count=10, title="Played"),
        _make_content("C:/Music/b.mp3", play_count=None, title="Never"),
    ]
    result = _run_main_with_db(contents)
    titles = [t["title"] for t in result["top_played"]]
    assert "Played" in titles
    assert "Never" not in titles


def test_top_played_capped_at_20():
    contents = [
        _make_content(f"C:/Music/{i}.mp3", play_count=i, title=str(i)) for i in range(1, 30)
    ]
    result = _run_main_with_db(contents)
    assert len(result["top_played"]) <= 20
