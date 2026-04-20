"""
Tests for scripts/strip_comment_urls.py

Covers:
- URL_PATTERN / strip_urls / has_url pure functions
- MUSIC_EXTENSIONS constant covers expected formats, excludes non-music
- process_flac() strips URLs, preserves non-URL content, respects write=False
- process_mp3() strips URLs from COMM frames, preserves non-URL content
- process_wav_aiff() delegates to the shared ID3 handler
- process_mp4() strips URLs from the \\xa9cmt atom
- crawler dispatches .wav/.aiff/.m4a/.alac to the right handler and skips non-music files
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.strip_comment_urls import URL_PATTERN, has_url, strip_urls  # noqa: E402
from scripts.utils import MUSIC_EXTENSIONS  # noqa: E402

# ---------------------------------------------------------------------------
# URL_PATTERN / strip_urls / has_url — pure function tests
# ---------------------------------------------------------------------------


def test_url_pattern_matches_https():
    assert URL_PATTERN.search("https://beatport.com/track/12345")


def test_url_pattern_matches_http():
    assert URL_PATTERN.search("http://example.com/path?q=1")


def test_url_pattern_matches_ftp():
    assert URL_PATTERN.search("ftp://files.example.com/audio.flac")


def test_url_pattern_matches_www():
    assert URL_PATTERN.search("www.bandcamp.com/album/xyz")


def test_url_pattern_no_match_plain_text():
    assert not URL_PATTERN.search("Great track, love the bassline")


def test_url_pattern_no_match_empty():
    assert not URL_PATTERN.search("")


def test_strip_urls_removes_http_url():
    result = strip_urls("Bought from http://beatport.com/track/123")
    assert "http" not in result
    assert "Bought from" in result


def test_strip_urls_removes_https_url():
    result = strip_urls("https://www.traxsource.com/title/456")
    assert result == ""


def test_strip_urls_removes_www_url():
    result = strip_urls("Check out www.example.com for more")
    assert "www" not in result


def test_strip_urls_preserves_non_url_text():
    text = "Amazing track - best seller of 2024"
    assert strip_urls(text) == text


def test_strip_urls_empty_string():
    assert strip_urls("") == ""


def test_has_url_true_for_http():
    assert has_url("Download at https://beatport.com/track/789")


def test_has_url_false_for_plain_text():
    assert not has_url("Just a regular comment with no links")


# ---------------------------------------------------------------------------
# process_flac — mocked mutagen FLAC
# process_flac uses: audio = FLAC(str(path)); audio.get(field, []); audio[field] = ...; audio.save()
# ---------------------------------------------------------------------------


def _make_flac_mock(comment_values=None, description_values=None):
    """Return a mock FLAC tags object."""
    mock_audio = MagicMock()
    comment_values = comment_values or []
    description_values = description_values or []

    def fake_get(field, default=None):
        if field == "comment":
            return list(comment_values)
        if field == "description":
            return list(description_values)
        return default if default is not None else []

    mock_audio.get = MagicMock(side_effect=fake_get)
    mock_audio.__setitem__ = MagicMock()
    return mock_audio


def test_process_flac_removes_url_from_comment(tmp_path):
    """process_flac returns changes when a URL is found in 'comment' field."""
    from scripts.strip_comment_urls import process_flac

    fpath = tmp_path / "track.flac"
    fpath.write_bytes(b"x")

    mock_audio = _make_flac_mock(comment_values=["Great track. https://beatport.com/track/123"])

    with patch("scripts.strip_comment_urls.FLAC", return_value=mock_audio):
        changes = process_flac(fpath, write=True)

    assert len(changes) == 1
    assert changes[0]["field"] == "COMMENT"
    assert "https" not in changes[0]["to_"]
    assert "Great track" in changes[0]["to_"]


def test_process_flac_preserves_non_url_comment(tmp_path):
    """process_flac returns no changes when comment has no URL."""
    from scripts.strip_comment_urls import process_flac

    fpath = tmp_path / "track.flac"
    fpath.write_bytes(b"x")

    mock_audio = _make_flac_mock(comment_values=["A great track with no URL"])

    with patch("scripts.strip_comment_urls.FLAC", return_value=mock_audio):
        changes = process_flac(fpath, write=True)

    assert changes == []


def test_process_flac_dry_run_does_not_save(tmp_path):
    """process_flac with write=False does not call audio.save()."""
    from scripts.strip_comment_urls import process_flac

    fpath = tmp_path / "track.flac"
    fpath.write_bytes(b"x")

    mock_audio = _make_flac_mock(comment_values=["https://beatport.com/track/123"])

    with patch("scripts.strip_comment_urls.FLAC", return_value=mock_audio):
        process_flac(fpath, write=False)

    mock_audio.save.assert_not_called()


def test_process_flac_removes_url_from_description(tmp_path):
    """process_flac strips URLs from 'description' field too."""
    from scripts.strip_comment_urls import process_flac

    fpath = tmp_path / "track.flac"
    fpath.write_bytes(b"x")

    mock_audio = _make_flac_mock(description_values=["From http://example.com the label"])

    with patch("scripts.strip_comment_urls.FLAC", return_value=mock_audio):
        changes = process_flac(fpath, write=False)

    assert len(changes) == 1
    assert changes[0]["field"] == "DESCRIPTION"


# ---------------------------------------------------------------------------
# process_mp3 — mocked mutagen ID3
# process_mp3 uses: tags = ID3(str(path)); [k for k in tags if k.startswith("COMM")];
#                   frame = tags[key]; frame.text; tags.save(str(path))
# ---------------------------------------------------------------------------


def _make_id3_mock(comm_texts=None):
    """Return a mock ID3 object with a COMM:eng frame."""
    mock_tags = MagicMock()
    comm_key = "COMM:eng"

    mock_frame = MagicMock()
    mock_frame.text = list(comm_texts or [])

    if comm_texts:
        mock_tags.__iter__ = MagicMock(return_value=iter([comm_key]))
        mock_tags.__getitem__ = MagicMock(return_value=mock_frame)
    else:
        mock_tags.__iter__ = MagicMock(return_value=iter([]))
        mock_tags.__getitem__ = MagicMock(return_value=mock_frame)

    return mock_tags, mock_frame


def test_process_mp3_removes_url_from_comm(tmp_path):
    """process_mp3 strips URL from COMM frame text."""
    from scripts.strip_comment_urls import process_mp3

    fpath = tmp_path / "track.mp3"
    fpath.write_bytes(b"x")

    mock_tags, mock_frame = _make_id3_mock(["Download at https://beatport.com/track/999"])

    with patch("scripts.strip_comment_urls.ID3", return_value=mock_tags):
        changes = process_mp3(fpath, write=True)

    assert len(changes) == 1
    assert "https" not in changes[0]["to_"]
    assert "Download at" in changes[0]["to_"]


def test_process_mp3_preserves_non_url_comm(tmp_path):
    """process_mp3 returns no changes when COMM frame has no URL."""
    from scripts.strip_comment_urls import process_mp3

    fpath = tmp_path / "track.mp3"
    fpath.write_bytes(b"x")

    mock_tags, _ = _make_id3_mock(["Purchased from record store"])

    with patch("scripts.strip_comment_urls.ID3", return_value=mock_tags):
        changes = process_mp3(fpath, write=True)

    assert changes == []


def test_process_mp3_dry_run_does_not_save(tmp_path):
    """process_mp3 with write=False does not call tags.save()."""
    from scripts.strip_comment_urls import process_mp3

    fpath = tmp_path / "track.mp3"
    fpath.write_bytes(b"x")

    mock_tags, _ = _make_id3_mock(["https://beatport.com/track/999"])

    with patch("scripts.strip_comment_urls.ID3", return_value=mock_tags):
        process_mp3(fpath, write=False)

    mock_tags.save.assert_not_called()


# ---------------------------------------------------------------------------
# MUSIC_EXTENSIONS constant
# ---------------------------------------------------------------------------


def test_music_extensions_covers_expected_formats():
    for ext in (".mp3", ".flac", ".wav", ".aif", ".aiff", ".alac", ".m4a"):
        assert ext in MUSIC_EXTENSIONS


def test_music_extensions_excludes_non_music():
    for ext in (".jpg", ".png", ".dat", ".xml", ".txt"):
        assert ext not in MUSIC_EXTENSIONS


# ---------------------------------------------------------------------------
# process_mp4 — mocked mutagen MP4
# ---------------------------------------------------------------------------


def _make_mp4_mock(cmt_values=None):
    mock_audio = MagicMock()
    mock_tags = MagicMock()
    values = list(cmt_values or [])

    def fake_get(key, default=None):
        if key == "\xa9cmt":
            return list(values)
        return default if default is not None else []

    mock_tags.get = MagicMock(side_effect=fake_get)
    mock_tags.__setitem__ = MagicMock()
    mock_audio.tags = mock_tags
    mock_audio.save = MagicMock()
    return mock_audio, mock_tags


def test_process_mp4_removes_url_from_cmt_atom(tmp_path):
    from scripts.strip_comment_urls import process_mp4

    fpath = tmp_path / "track.m4a"
    fpath.write_bytes(b"x")

    mock_audio, _ = _make_mp4_mock(cmt_values=["Bought from https://bandcamp.com/album/x"])

    with patch("scripts.strip_comment_urls.MP4", return_value=mock_audio):
        changes = process_mp4(fpath, write=True)

    assert len(changes) == 1
    assert changes[0]["field"] == "COMMENT"
    assert "https" not in changes[0]["to_"]
    assert "Bought from" in changes[0]["to_"]


def test_process_mp4_preserves_non_url_comment(tmp_path):
    from scripts.strip_comment_urls import process_mp4

    fpath = tmp_path / "track.m4a"
    fpath.write_bytes(b"x")

    mock_audio, _ = _make_mp4_mock(cmt_values=["Favourite track of the summer"])

    with patch("scripts.strip_comment_urls.MP4", return_value=mock_audio):
        changes = process_mp4(fpath, write=True)

    assert changes == []
    mock_audio.save.assert_not_called()


def test_process_mp4_dry_run_does_not_save(tmp_path):
    from scripts.strip_comment_urls import process_mp4

    fpath = tmp_path / "track.alac"
    fpath.write_bytes(b"x")

    mock_audio, _ = _make_mp4_mock(cmt_values=["https://beatport.com/t/1"])

    with patch("scripts.strip_comment_urls.MP4", return_value=mock_audio):
        process_mp4(fpath, write=False)

    mock_audio.save.assert_not_called()


# ---------------------------------------------------------------------------
# Crawler dispatch
# ---------------------------------------------------------------------------


def test_wav_file_dispatched_to_id3_handler(tmp_path):
    """WAV files are now processed via the shared ID3 handler."""
    from scripts.strip_comment_urls import crawl

    (tmp_path / "track.wav").write_bytes(b"x")

    with patch("scripts.strip_comment_urls.process_wav_aiff", return_value=[]) as mock_handler:
        crawl([str(tmp_path)], write=True)

    mock_handler.assert_called_once()


def test_aiff_file_dispatched_to_id3_handler(tmp_path):
    from scripts.strip_comment_urls import crawl

    (tmp_path / "track.aiff").write_bytes(b"x")

    with patch("scripts.strip_comment_urls.process_wav_aiff", return_value=[]) as mock_handler:
        crawl([str(tmp_path)], write=True)

    mock_handler.assert_called_once()


def test_m4a_file_dispatched_to_mp4_handler(tmp_path):
    from scripts.strip_comment_urls import crawl

    (tmp_path / "track.m4a").write_bytes(b"x")

    with patch("scripts.strip_comment_urls.process_mp4", return_value=[]) as mock_handler:
        crawl([str(tmp_path)], write=True)

    mock_handler.assert_called_once()


def test_alac_file_dispatched_to_mp4_handler(tmp_path):
    from scripts.strip_comment_urls import crawl

    (tmp_path / "track.alac").write_bytes(b"x")

    with patch("scripts.strip_comment_urls.process_mp4", return_value=[]) as mock_handler:
        crawl([str(tmp_path)], write=True)

    mock_handler.assert_called_once()


def test_non_music_files_never_opened(tmp_path):
    """Crawler must not call ANY handler for .jpg / .dat / .xml etc."""
    from scripts.strip_comment_urls import crawl

    (tmp_path / "cover.jpg").write_bytes(b"x")
    (tmp_path / "analysis.dat").write_bytes(b"x")
    (tmp_path / "playlist.xml").write_bytes(b"x")

    with (
        patch("scripts.strip_comment_urls.process_mp3") as mock_mp3,
        patch("scripts.strip_comment_urls.process_flac") as mock_flac,
        patch("scripts.strip_comment_urls.process_wav_aiff") as mock_wav,
        patch("scripts.strip_comment_urls.process_mp4") as mock_mp4,
    ):
        crawl([str(tmp_path)], write=True)

    mock_mp3.assert_not_called()
    mock_flac.assert_not_called()
    mock_wav.assert_not_called()
    mock_mp4.assert_not_called()


def test_mp3_file_processed_not_skipped(tmp_path):
    """Crawler processes .mp3 files (sanity check — MP3 must not be skipped)."""
    from scripts.strip_comment_urls import crawl

    (tmp_path / "track.mp3").write_bytes(b"x")

    with patch("scripts.strip_comment_urls.process_mp3", return_value=[]) as mock_mp3:
        crawl([str(tmp_path)], write=False)

    mock_mp3.assert_called_once()


def test_flac_file_processed_not_skipped(tmp_path):
    """Crawler processes .flac files (sanity check — FLAC must not be skipped)."""
    from scripts.strip_comment_urls import crawl

    (tmp_path / "track.flac").write_bytes(b"x")

    with patch("scripts.strip_comment_urls.process_flac", return_value=[]) as mock_flac:
        crawl([str(tmp_path)], write=False)

    mock_flac.assert_called_once()
