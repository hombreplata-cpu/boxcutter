"""
Shared constants used across BoxCutter scripts.

Keep this file as the single source of truth for file-type mappings.
When adding a new audio format, update EXT_TO_FILETYPE and FILETYPE_LABELS
here — never duplicate them in individual scripts.
"""

import contextlib
import os
import platform
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


def normalize_path_for_compare(path: str) -> str:
    """Normalise a path string for case-insensitive equality / startswith
    comparison on case-insensitive filesystems.

    Windows + Linux: delegates to ``os.path.normcase`` — bit-for-bit
    identical to historical behaviour. On Windows that lowercases AND
    converts forward slashes to backslashes; on Linux it is identity.

    macOS: explicit ``.lower()``. ``os.path.normcase`` is a no-op on all
    Unix platforms (including Darwin) per ``posixpath.normcase``, but
    APFS / HFS+ are case-insensitive by default — so a stored path that
    differs from the on-disk path only by case must be treated as equal.
    Issue #104 has the full diagnosis.
    """
    if platform.system() == "Darwin":
        return path.lower()
    return os.path.normcase(path)


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
