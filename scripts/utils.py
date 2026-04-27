"""
Shared constants used across BoxCutter scripts.

Keep this file as the single source of truth for file-type mappings.
When adding a new audio format, update EXT_TO_FILETYPE and FILETYPE_LABELS
here — never duplicate them in individual scripts.
"""

import contextlib
import sys


def configure_io() -> None:
    """Force stdout/stderr to UTF-8 with errors='replace'.

    Windows console default encoding is cp1252, which crashes on
    combining diacritics and most non-Latin glyphs (REG-003: track
    titles with `\\u0302` killed rekordbox_relocate.py mid-run).
    Call this at the top of every script entrypoint so audio metadata
    can be safely echoed regardless of locale.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # Detached/closed streams (some test harnesses) — swallow.
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")


EXT_TO_FILETYPE = {
    ".mp3": 1,
    ".m4a": 4,  # AAC container
    ".wav": 5,
    ".flac": 6,
    ".aif": 7,
    ".aiff": 7,
    ".ogg": 8,
    ".wma": 9,
    ".mp4": 10,
    ".alac": 11,  # ALAC stored as .alac (distinct from .m4a AAC)
}

MUSIC_EXTENSIONS = {".mp3", ".flac", ".wav", ".aif", ".aiff", ".alac", ".m4a"}

FILETYPE_LABELS = {
    1: "MP3",
    4: "AAC/M4A",
    5: "WAV",
    6: "FLAC",
    7: "AIFF",
    8: "OGG",
    9: "WMA",
    10: "MP4",
    11: "ALAC",
}
