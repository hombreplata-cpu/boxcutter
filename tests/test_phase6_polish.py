"""
Phase 6 tests — polish.

Resolves v1.1 roadmap items B-08, R-02, R-07.
"""

import sys
import unicodedata
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# B-08 — add_new dry-run does not persist Artist/Album/Genre
# ---------------------------------------------------------------------------


def test_add_new_dry_run_does_not_call_create_helpers(tmp_path):
    """In dry-run, add_new must NOT call db.add_artist/add_album/add_genre.
    The early-return in the dry_run branch is the contract; this test pins it
    so a future refactor can't introduce silent side-effects in preview mode."""
    from scripts import rekordbox_add_new as ran  # noqa: PLC0415

    watch = tmp_path / "watch"
    watch.mkdir()
    track = watch / "Track.mp3"
    track.write_bytes(b"x")

    db = MagicMock()
    db.engine.url.database = str(tmp_path / "fake.db")
    db.get_content().filter_by(rb_local_deleted=0).all.return_value = []
    db.get_playlist.return_value = MagicMock(Name="Test", ID="42")

    args = MagicMock()
    args.watch_dir = str(watch)
    args.playlist_id = "42"
    args.dry_run = True
    args.db_path = str(tmp_path / "fake.db")

    fake_audio = MagicMock()
    fake_audio.get.side_effect = lambda k: {
        "title": ["Track"],
        "artist": ["Some Artist"],
        "album": ["An Album"],
        "genre": ["A Genre"],
    }.get(k)
    fake_audio.info = MagicMock(length=180.0, bitrate=320000, sample_rate=44100)

    with (
        patch("scripts.rekordbox_add_new.MasterDatabase", return_value=db),
        patch("mutagen.File", return_value=fake_audio),
    ):
        ran.run(args)

    # In dry-run mode, none of the create helpers should fire.
    assert not db.add_artist.called, "add_artist called during dry-run"
    assert not db.add_album.called, "add_album called during dry-run"
    assert not db.add_genre.called, "add_genre called during dry-run"
    assert not db.add_content.called, "add_content called during dry-run"
    assert not db.add_to_playlist.called, "add_to_playlist called during dry-run"


# ---------------------------------------------------------------------------
# R-02 — Path.suffix.lower() works regardless of OS-supplied case
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    ["track.FLAC", "track.Flac", "track.flac", "TRACK.AIFF", "Mix.Mp3"],
)
def test_suffix_lower_normalises_case(filename):
    """Path.suffix.lower() must produce a canonical form regardless of how the
    filesystem returns the name (Windows preserves uppercase, macOS varies)."""
    expected = "." + filename.split(".")[-1].lower()
    assert Path(filename).suffix.lower() == expected


# ---------------------------------------------------------------------------
# R-07 — macOS NFD/NFC path normalisation
# ---------------------------------------------------------------------------


def test_normalize_path_nfc_on_darwin():
    """A track filename in NFD (decomposed) on disk must be normalised to NFC
    by normalize_path so it can match an NFC FolderPath stored in the DB."""
    from scripts import rekordbox_cleanup as rc  # noqa: PLC0415

    nfc = "Café.flac"  # composed: 'é' is one codepoint U+00E9
    nfd = unicodedata.normalize("NFD", nfc)  # decomposed: 'e' + U+0301
    assert nfc != nfd, "Test fixture invariant: NFC and NFD strings should differ"

    with patch("scripts.rekordbox_cleanup.platform.system", return_value="Darwin"):
        # An NFD-encoded path comes through as NFC after normalisation
        result = rc.normalize_path(nfd)
    assert result == nfc


def test_normalize_path_unchanged_on_linux():
    """Linux is left as-is (no separator translation, no Unicode normalisation)."""
    from scripts import rekordbox_cleanup as rc  # noqa: PLC0415

    p = "/home/dj/Café.flac"
    with patch("scripts.rekordbox_cleanup.platform.system", return_value="Linux"):
        assert rc.normalize_path(p) == p


def test_relocate_normalize_path_nfc_on_darwin():
    """Same NFC normalisation applies in rekordbox_relocate.normalize_path."""
    from scripts import rekordbox_relocate as rr  # noqa: PLC0415

    nfc = "Café.flac"
    nfd = unicodedata.normalize("NFD", nfc)
    with patch("scripts.rekordbox_relocate.platform.system", return_value="Darwin"):
        assert rr.normalize_path(nfd) == nfc


def test_normalize_path_windows_translates_separators():
    """Windows: forward slashes → backslashes, no Unicode change."""
    from scripts import rekordbox_cleanup as rc  # noqa: PLC0415

    with patch("scripts.rekordbox_cleanup.platform.system", return_value="Windows"):
        assert rc.normalize_path("C:/Music/Track.flac") == "C:\\Music\\Track.flac"
