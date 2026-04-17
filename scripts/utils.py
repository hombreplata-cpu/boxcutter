"""
Shared constants used across rekordbox-tools scripts.

Keep this file as the single source of truth for file-type mappings.
When adding a new audio format, update EXT_TO_FILETYPE and FILETYPE_LABELS
here — never duplicate them in individual scripts.
"""

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
