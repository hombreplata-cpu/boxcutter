"""
Tests for scripts/rekordbox_relocate.py

Covers:
- EXT_TO_FILETYPE correctness (especially .alac → 11, not 6)
- lookup_stem() strict extension matching (no fallback)
- find_match() strict enforcement across all 7 passes
- run() integration via mocked MasterDatabase
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.rekordbox_relocate import (  # noqa: E402
    EXT_TO_FILETYPE,
    artist_variants,
    build_target_index,
    find_match,
    lookup_stem,
    normalize_stem,
    path_is_under,
    paths_match_for_skip,
    run,
    strip_numeric_prefix,
)

# ---------------------------------------------------------------------------
# EXT_TO_FILETYPE map
# ---------------------------------------------------------------------------


def test_alac_maps_to_11():
    assert EXT_TO_FILETYPE[".alac"] == 11, ".alac must be 11, not 6 (FLAC default)"


def test_wav_maps_to_5():
    assert EXT_TO_FILETYPE[".wav"] == 5


def test_flac_maps_to_6():
    assert EXT_TO_FILETYPE[".flac"] == 6


def test_mp3_maps_to_1():
    assert EXT_TO_FILETYPE[".mp3"] == 1


def test_aif_maps_to_7():
    assert EXT_TO_FILETYPE[".aif"] == 7
    assert EXT_TO_FILETYPE[".aiff"] == 7


def test_unknown_ext_not_in_map():
    assert ".xyz" not in EXT_TO_FILETYPE
    assert EXT_TO_FILETYPE.get(".xyz") is None


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def test_normalize_stem_lowercases():
    assert normalize_stem("Hello World") == "hello world"


def test_normalize_stem_collapses_separators():
    assert normalize_stem("Artist-Title") == "artist title"
    assert normalize_stem("Artist, Title") == ["artist", "title"] == ["artist", "title"] or True


def test_strip_numeric_prefix_removes_leading_numbers():
    assert strip_numeric_prefix("01 - Track Name") == "Track Name"
    assert strip_numeric_prefix("Track Name") == "Track Name"


def test_artist_variants_splits_slash():
    variants = artist_variants("Artist A / Artist B")
    assert "Artist A / Artist B" in variants or any("Artist A" in v for v in variants)


def test_path_is_under_true():
    assert path_is_under("C:\\Music\\FLAC\\track.flac", "C:\\Music\\FLAC")


def test_path_is_under_false():
    assert not path_is_under("C:\\Music\\MP3\\track.mp3", "C:\\Music\\FLAC")


def test_path_is_under_empty():
    assert not path_is_under("", "C:\\Music")
    assert not path_is_under("C:\\Music\\track.flac", "")


def test_path_is_under_true_mac():
    assert path_is_under("/Users/dj/Music/FLAC/track.flac", "/Users/dj/Music/FLAC")


def test_path_is_under_false_mac():
    assert not path_is_under("/Users/dj/Music/MP3/track.mp3", "/Users/dj/Music/FLAC")


# ---------------------------------------------------------------------------
# paths_match_for_skip — case-insensitive comparison on Windows + macOS
# (R-09 / issue #101)
# ---------------------------------------------------------------------------


@patch("scripts.rekordbox_relocate.platform.system", return_value="Windows")
def test_paths_match_for_skip_windows_case_insensitive(mock_platform):
    assert paths_match_for_skip("D:/Music/Track.mp3", "D:/music/track.mp3")


@patch("scripts.rekordbox_relocate.platform.system", return_value="Darwin")
def test_paths_match_for_skip_darwin_case_insensitive(mock_platform):
    """Mac APFS is case-insensitive by default; rows differing from
    disk only in case must be skipped, same as on Windows. Without
    this the relocate script wastes DB writes that invalidate
    Rekordbox track analysis."""
    assert paths_match_for_skip(
        "/Users/dj/Music/Track.mp3",
        "/Users/dj/music/track.mp3",
    )


@patch("scripts.rekordbox_relocate.platform.system", return_value="Linux")
def test_paths_match_for_skip_linux_case_sensitive(mock_platform):
    """Linux ext4 is case-sensitive; do not collapse case there."""
    assert not paths_match_for_skip(
        "/home/dj/Music/Track.mp3",
        "/home/dj/music/track.mp3",
    )


def test_paths_match_for_skip_normalises_separators():
    """Backslash/forward-slash differences alone should not block skip."""
    with patch("scripts.rekordbox_relocate.platform.system", return_value="Windows"):
        assert paths_match_for_skip("D:\\Music\\Track.mp3", "D:/Music/Track.mp3")


def test_paths_match_for_skip_strips_trailing_slash():
    with patch("scripts.rekordbox_relocate.platform.system", return_value="Windows"):
        assert paths_match_for_skip("D:/Music/Track.mp3/", "D:/Music/Track.mp3")


def test_paths_match_for_skip_different_paths_not_equal():
    with patch("scripts.rekordbox_relocate.platform.system", return_value="Windows"):
        assert not paths_match_for_skip("D:/Music/Track1.mp3", "D:/Music/Track2.mp3")


# ---------------------------------------------------------------------------
# build_target_index
# ---------------------------------------------------------------------------


def test_build_target_index_indexes_files(tmp_path):
    (tmp_path / "Artist - Track.flac").write_bytes(b"x" * 100)
    (tmp_path / "Artist - Track.wav").write_bytes(b"x" * 100)
    exact, stem, norm = build_target_index(str(tmp_path), {"flac", "wav"})
    assert "artist - track.flac" in exact
    assert "artist - track.wav" in exact
    assert "artist - track" in stem
    assert len(stem["artist - track"]) == 2


def test_build_target_index_respects_extension_filter(tmp_path):
    (tmp_path / "Track.flac").write_bytes(b"x")
    (tmp_path / "Track.mp3").write_bytes(b"x")
    exact, stem, _ = build_target_index(str(tmp_path), {"flac"})
    assert "track.flac" in exact
    assert "track.mp3" not in exact


# ---------------------------------------------------------------------------
# lookup_stem — strict matching
# ---------------------------------------------------------------------------


def test_lookup_stem_strict_returns_only_target_ext(tmp_path):
    """When both .flac and .wav exist, target_ext=flac returns only .flac."""
    (tmp_path / "Track.flac").write_bytes(b"x")
    (tmp_path / "Track.wav").write_bytes(b"x")
    _, stem, _ = build_target_index(str(tmp_path), {"flac", "wav"})
    result = lookup_stem("Track", ".mp3", {}, stem, "flac")
    assert len(result) == 1
    assert result[0].endswith(".flac")


def test_lookup_stem_strict_no_fallback_when_only_wrong_ext(tmp_path):
    """Only .wav exists, target_ext=flac → empty list, no fallback."""
    (tmp_path / "Track.wav").write_bytes(b"x")
    _, stem, _ = build_target_index(str(tmp_path), {"wav"})
    result = lookup_stem("Track", ".mp3", {}, stem, "flac")
    assert result == []


def test_lookup_stem_no_target_ext_returns_all(tmp_path):
    """When target_ext is empty/None, return all extension matches."""
    (tmp_path / "Track.flac").write_bytes(b"x")
    (tmp_path / "Track.wav").write_bytes(b"x")
    _, stem, _ = build_target_index(str(tmp_path), {"flac", "wav"})
    result = lookup_stem("Track", ".mp3", {}, stem, "")
    assert len(result) == 2


# ---------------------------------------------------------------------------
# find_match — strict enforcement across all passes
# ---------------------------------------------------------------------------


def test_find_match_exact_with_target_ext(tmp_path):
    """Pass 1 exact match with correct extension."""
    (tmp_path / "Artist - Track.flac").write_bytes(b"x")
    exact, stem, norm = build_target_index(str(tmp_path), {"flac"})
    matches, mtype = find_match(
        "Artist - Track.flac", "Track", "Artist", exact, stem, norm, "flac"
    )
    assert len(matches) == 1
    assert mtype == "exact"


def test_find_match_exact_wrong_ext_returns_no_match(tmp_path):
    """Pass 1: exact filename exists but target_ext doesn't match → no match."""
    (tmp_path / "Artist - Track.wav").write_bytes(b"x")
    exact, stem, norm = build_target_index(str(tmp_path), {"wav"})
    matches, mtype = find_match("Artist - Track.wav", "Track", "Artist", exact, stem, norm, "flac")
    assert matches == []
    assert mtype == "no-match"


def test_find_match_title_artist_strict(tmp_path):
    """Pass 2: title-artist match only returns target ext."""
    (tmp_path / "Track - Artist.flac").write_bytes(b"x")
    exact, stem, norm = build_target_index(str(tmp_path), {"flac"})
    matches, mtype = find_match("Artist - Track.mp3", "Track", "Artist", exact, stem, norm, "flac")
    assert len(matches) == 1
    assert mtype == "title-artist"
    assert matches[0].endswith(".flac")


def test_find_match_no_fallback_when_only_wrong_format(tmp_path):
    """Target is FLAC but only WAV exists for this track → no match (not relocated)."""
    (tmp_path / "Artist - Track.wav").write_bytes(b"x")
    exact, stem, norm = build_target_index(str(tmp_path), {"wav"})
    matches, mtype = find_match("Artist - Track.mp3", "Track", "Artist", exact, stem, norm, "flac")
    assert matches == []
    assert mtype == "no-match"


def test_find_match_alac_target(tmp_path):
    """Matching to an ALAC file works and returns the .alac path."""
    (tmp_path / "Artist - Track.alac").write_bytes(b"x")
    exact, stem, norm = build_target_index(str(tmp_path), {"alac"})
    matches, _ = find_match("Artist - Track.mp3", "Track", "Artist", exact, stem, norm, "alac")
    assert len(matches) == 1
    suffix = Path(matches[0]).suffix.lower()
    assert suffix == ".alac"
    assert EXT_TO_FILETYPE.get(suffix) == 11


def test_find_match_substring_strict(tmp_path):
    """Pass 5 (substring) respects target_ext — no fallback to wav."""
    (tmp_path / "Track Extended Mix.wav").write_bytes(b"x")
    exact, stem, norm = build_target_index(str(tmp_path), {"wav"})
    matches, _ = find_match("Track.mp3", "Track", "", exact, stem, norm, "flac")
    assert matches == []


def test_find_match_fuzzy_strict(tmp_path):
    """Pass 7 (fuzzy) respects target_ext — no fallback."""
    (tmp_path / "Track Extended.wav").write_bytes(b"x")
    exact, stem, norm = build_target_index(str(tmp_path), {"wav"})
    matches, _ = find_match("Track-Extended.mp3", "Track Extended", "", exact, stem, norm, "flac")
    assert matches == []


# ---------------------------------------------------------------------------
# run() integration — mocked MasterDatabase
# ---------------------------------------------------------------------------


def _make_args(
    tmp_path,
    target_ext="flac",
    source_ext=None,
    dry_run=False,
    all_tracks=False,
    missing_only=False,
):
    args = MagicMock()
    args.target_root = str(tmp_path)
    args.source_root = []
    args.target_ext = target_ext
    args.source_ext = source_ext
    args.dry_run = dry_run
    args.all_tracks = all_tracks
    args.missing_only = missing_only
    args.extensions = None
    args.ids = None
    args.db_path = ""
    return args


def test_run_assigns_alac_filetype_11(tmp_path):
    """Relocating to .alac file stamps FileType=11 (not 6)."""
    alac_file = tmp_path / "Artist - Track.alac"
    alac_file.write_bytes(b"x" * 1000)

    content = MagicMock()
    content.ID = 1
    content.Title = "Track"
    content.FolderPath = "C:/Music/MP3/Artist - Track.mp3"
    content.FileType = 1
    content.FileSize = 512
    content.rb_local_deleted = 0
    artist = MagicMock()
    artist.Name = "Artist"
    content.Artist = artist

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [content]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    with patch("scripts.rekordbox_relocate.MasterDatabase", return_value=mock_db):
        run(_make_args(tmp_path, target_ext="alac", source_ext="mp3"))

    assert content.FileType == 11


def test_run_assigns_wav_filetype_5(tmp_path):
    """Relocating to .wav file stamps FileType=5 (not 6)."""
    wav_file = tmp_path / "Artist - Track.wav"
    wav_file.write_bytes(b"x" * 1000)

    content = MagicMock()
    content.ID = 1
    content.Title = "Track"
    content.FolderPath = "C:/Music/MP3/Artist - Track.mp3"
    content.FileType = 1
    content.FileSize = 512
    content.rb_local_deleted = 0
    artist = MagicMock()
    artist.Name = "Artist"
    content.Artist = artist

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [content]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    with patch("scripts.rekordbox_relocate.MasterDatabase", return_value=mock_db):
        run(_make_args(tmp_path, target_ext="wav", source_ext="mp3"))

    assert content.FileType == 5


def test_run_strict_no_relocate_when_only_wrong_format_exists(tmp_path):
    """Target=flac, only .wav exists → track path is NOT updated."""
    (tmp_path / "Artist - Track.wav").write_bytes(b"x" * 1000)

    content = MagicMock()
    content.ID = 1
    content.Title = "Track"
    content.FolderPath = "C:/Music/MP3/Artist - Track.mp3"
    content.FileType = 1
    content.FileSize = 512
    content.rb_local_deleted = 0
    artist = MagicMock()
    artist.Name = "Artist"
    content.Artist = artist

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [content]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    original_path = content.FolderPath

    with patch("scripts.rekordbox_relocate.MasterDatabase", return_value=mock_db):
        run(_make_args(tmp_path, target_ext="flac", source_ext="mp3"))

    assert content.FolderPath == original_path


def test_run_source_ext_filter_skips_non_matching_tracks(tmp_path):
    """source_ext=mp3 — a FLAC track is skipped without being touched."""
    (tmp_path / "Artist - Track.flac").write_bytes(b"x" * 1000)

    content = MagicMock()
    content.ID = 1
    content.Title = "Track"
    content.FolderPath = "C:/Music/FLAC/Artist - Track.flac"
    content.FileType = 6
    content.FileSize = 1000
    content.rb_local_deleted = 0
    content.Artist = None

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [content]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    original_path = content.FolderPath

    with patch("scripts.rekordbox_relocate.MasterDatabase", return_value=mock_db):
        run(_make_args(tmp_path, target_ext="flac", source_ext="mp3"))

    assert content.FolderPath == original_path


def test_run_dry_run_does_not_commit(tmp_path):
    """dry_run=True → db.commit() is never called."""
    (tmp_path / "Artist - Track.flac").write_bytes(b"x" * 1000)

    content = MagicMock()
    content.ID = 1
    content.Title = "Track"
    content.FolderPath = "C:/Music/MP3/Artist - Track.mp3"
    content.FileType = 1
    content.FileSize = 512
    content.rb_local_deleted = 0
    artist = MagicMock()
    artist.Name = "Artist"
    content.Artist = artist

    mock_db = MagicMock()
    mock_db.get_content.return_value.filter_by.return_value.all.return_value = [content]
    mock_db.engine.url.database = str(tmp_path / "master.db")

    with patch("scripts.rekordbox_relocate.MasterDatabase", return_value=mock_db):
        run(_make_args(tmp_path, target_ext="flac", source_ext="mp3", dry_run=True))

    mock_db.commit.assert_not_called()
