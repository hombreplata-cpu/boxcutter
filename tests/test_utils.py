"""
Tests for scripts/utils.py

Locks down EXT_TO_FILETYPE, FILETYPE_LABELS, and MUSIC_EXTENSIONS so that
any accidental edit or omission fails loudly rather than silently corrupting
FileType values written to the Rekordbox database.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils import EXT_TO_FILETYPE, FILETYPE_LABELS, MUSIC_EXTENSIONS  # noqa: E402

# ---------------------------------------------------------------------------
# EXT_TO_FILETYPE — every supported extension must map to its exact integer
# ---------------------------------------------------------------------------


def test_mp3_maps_to_1():
    assert EXT_TO_FILETYPE[".mp3"] == 1


def test_m4a_maps_to_4():
    assert EXT_TO_FILETYPE[".m4a"] == 4


def test_wav_maps_to_5():
    assert EXT_TO_FILETYPE[".wav"] == 5


def test_flac_maps_to_6():
    assert EXT_TO_FILETYPE[".flac"] == 6


def test_aif_maps_to_7():
    assert EXT_TO_FILETYPE[".aif"] == 7


def test_aiff_maps_to_7():
    assert EXT_TO_FILETYPE[".aiff"] == 7


def test_ogg_maps_to_8():
    assert EXT_TO_FILETYPE[".ogg"] == 8


def test_wma_maps_to_9():
    assert EXT_TO_FILETYPE[".wma"] == 9


def test_mp4_maps_to_10():
    assert EXT_TO_FILETYPE[".mp4"] == 10


def test_alac_maps_to_11():
    """ALAC must be 11 — distinct from .m4a (AAC = 4). This was the ALAC bug."""
    assert EXT_TO_FILETYPE[".alac"] == 11


def test_unknown_extensions_not_in_map():
    """Unknown extensions must return None — no silent fallback to a wrong type."""
    assert EXT_TO_FILETYPE.get(".xyz") is None
    assert EXT_TO_FILETYPE.get(".wave") is None
    assert EXT_TO_FILETYPE.get(".mp4a") is None
    assert EXT_TO_FILETYPE.get("mp3") is None  # missing leading dot


def test_all_keys_have_leading_dot():
    for ext in EXT_TO_FILETYPE:
        assert ext.startswith("."), f"Extension {ext!r} is missing leading dot"


def test_all_values_are_positive_integers():
    for ext, val in EXT_TO_FILETYPE.items():
        assert isinstance(val, int) and val > 0, f"{ext} → {val!r} is not a positive int"


# ---------------------------------------------------------------------------
# FILETYPE_LABELS — every integer used in EXT_TO_FILETYPE must have a label
# ---------------------------------------------------------------------------


def test_all_filetype_integers_have_labels():
    """Every FileType integer written to the DB must be human-readable in the UI."""
    used_types = set(EXT_TO_FILETYPE.values())
    for ft in used_types:
        assert ft in FILETYPE_LABELS, (
            f"FileType {ft} used in EXT_TO_FILETYPE but missing from FILETYPE_LABELS"
        )


def test_filetype_labels_are_nonempty_strings():
    for ft, label in FILETYPE_LABELS.items():
        assert isinstance(label, str) and label.strip(), (
            f"FILETYPE_LABELS[{ft}] is empty or not a string"
        )


# ---------------------------------------------------------------------------
# MUSIC_EXTENSIONS — must include the formats we actually scan
# ---------------------------------------------------------------------------


def test_music_extensions_covers_core_formats():
    for ext in (".mp3", ".flac", ".wav", ".aiff", ".aif", ".alac", ".m4a"):
        assert ext in MUSIC_EXTENSIONS, f"{ext} missing from MUSIC_EXTENSIONS"


def test_music_extensions_are_lowercase_with_dot():
    for ext in MUSIC_EXTENSIONS:
        assert ext.startswith("."), f"{ext!r} missing leading dot"
        assert ext == ext.lower(), f"{ext!r} is not lowercase"
