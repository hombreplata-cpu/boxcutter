"""
Generate the silent audio fixtures used by bundle-smoke tests.

These fixtures are checked into the repo (they're small, ~1–4 KB each, binary-
stable) so CI doesn't need ffmpeg to run the smoke tests. This script is here
for traceability and for regenerating the fixtures if we ever need to add a
new format or change the embedded metadata.

Each fixture is ~0.1s of silence at 22050 Hz mono, tagged with:
    Title    : "BoxCutter Test Track"
    Artist   : "Bundle Smoke"
    Album    : "Fixture Album"
    Genre    : "Test"
    Year     : 2026
    Track    : 1
    BPM      : 120
    Comment  : "Visit beatport.com/abc for more — bundle-smoke URL bait"

The comment field intentionally contains a URL so strip_comment_urls can
verify it stripped exactly the URL and left the surrounding text.

Formats generated:
    - sample.wav   PCM via Python stdlib (no ffmpeg required)
    - sample.flac  via ffmpeg
    - sample.aiff  via ffmpeg
    - sample.mp3   raw silent MPEG frame written by hand (no encoder needed)

M4A is NOT generated here — it requires a full ffmpeg build with libfdk-aac
or aac encoder. Add it as a follow-up if MP4 tag handling needs bundle-smoke
coverage. For now scripts that read .m4a files are exercised via the import
contract test (which verifies mutagen.mp4 is in the bundle) without needing
a fixture file.

Requirements:
    Python stdlib (wave, struct)
    mutagen (Python package)
    ffmpeg on PATH (for flac and aiff only — WAV and MP3 are stdlib-only)

Usage:
    python tests/bundle/generate_fixtures.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"
SAMPLE_RATE = 22050
DURATION_SAMPLES = SAMPLE_RATE // 10  # 0.1 s

TITLE = "BoxCutter Test Track"
ARTIST = "Bundle Smoke"
ALBUM = "Fixture Album"
GENRE = "Test"
YEAR = "2026"
TRACK = "1"
BPM = "120"
COMMENT = "Visit beatport.com/abc for more — bundle-smoke URL bait"


def _write_silent_wav(path: Path) -> None:
    """Write a valid 0.1s 22050 Hz mono PCM WAV using stdlib only."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * DURATION_SAMPLES)


def _ffmpeg_convert(in_wav: Path, out_path: Path, codec: str, fmt: str) -> None:
    """Convert WAV to another format via ffmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(in_wav),
        "-c:a",
        codec,
        "-f",
        fmt,
        str(out_path),
    ]
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603


def _write_silent_mp3(path: Path) -> None:
    """Write a minimal-valid silent MP3 by emitting a few short MPEG-1 Layer III
    frames of silence directly. Avoids the dependency on an MP3 encoder.

    Each frame is 26 ms at 22050 Hz / 32 kbps, padded with zero data. mutagen
    is happy to read/write ID3 tags onto this stream even though it's an
    unusual encoder profile.
    """
    # MPEG-1 Layer III, 32 kbps, 22050 Hz, mono, no padding, no CRC. Header bytes
    # carefully constructed; see mp3 spec §2.4.1.3. Frame size = 144 * 32000 /
    # 22050 = ~209 bytes. We emit 4 frames = ~0.1 s.
    # Header: 11111111 11111011 00010000 11000100
    #         FFFB10C4 — sync, MPEG-1, Layer III, no CRC, 32k, 22050, no pad,
    #         private=0, mono, no copy, original, emphasis=none.
    header = bytes.fromhex("FFFB10C4")
    frame_body = b"\x00" * 205  # 209 - 4 header bytes
    one_frame = header + frame_body
    path.write_bytes(one_frame * 4)


def _tag_mp3(path: Path) -> None:
    from mutagen.id3 import COMM, ID3, TALB, TBPM, TCON, TIT2, TPE1, TRCK, TYER, ID3NoHeaderError

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TIT2(encoding=3, text=TITLE))
    tags.add(TPE1(encoding=3, text=ARTIST))
    tags.add(TALB(encoding=3, text=ALBUM))
    tags.add(TCON(encoding=3, text=GENRE))
    tags.add(TYER(encoding=3, text=YEAR))
    tags.add(TRCK(encoding=3, text=TRACK))
    tags.add(TBPM(encoding=3, text=BPM))
    tags.add(COMM(encoding=3, lang="eng", desc="", text=COMMENT))
    tags.save(str(path), v2_version=3)


def _tag_flac(path: Path) -> None:
    from mutagen.flac import FLAC

    f = FLAC(str(path))
    f["TITLE"] = TITLE
    f["ARTIST"] = ARTIST
    f["ALBUM"] = ALBUM
    f["GENRE"] = GENRE
    f["DATE"] = YEAR
    f["TRACKNUMBER"] = TRACK
    f["BPM"] = BPM
    f["COMMENT"] = COMMENT
    f.save()


def _tag_wav_aiff(path: Path) -> None:
    """WAV/AIFF carry ID3 frames the same way MP3 does."""
    from mutagen.id3 import COMM, ID3, TALB, TBPM, TCON, TIT2, TPE1, TRCK, TYER, ID3NoHeaderError

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TIT2(encoding=3, text=TITLE))
    tags.add(TPE1(encoding=3, text=ARTIST))
    tags.add(TALB(encoding=3, text=ALBUM))
    tags.add(TCON(encoding=3, text=GENRE))
    tags.add(TYER(encoding=3, text=YEAR))
    tags.add(TRCK(encoding=3, text=TRACK))
    tags.add(TBPM(encoding=3, text=BPM))
    tags.add(COMM(encoding=3, lang="eng", desc="", text=COMMENT))
    tags.save(str(path), v2_version=3)


def main() -> int:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    have_ffmpeg = shutil.which("ffmpeg") is not None

    if not have_ffmpeg:
        print("WARNING: ffmpeg not on PATH — will skip flac/aiff. WAV and MP3 still produced.")

    print(f"[generate] writing fixtures to {FIXTURES_DIR}")

    # WAV — stdlib only
    wav_path = FIXTURES_DIR / "sample.wav"
    print("[generate] sample.wav (stdlib wave)")
    _write_silent_wav(wav_path)
    _tag_wav_aiff(wav_path)

    # MP3 — hand-rolled silent frames, no encoder needed
    mp3_path = FIXTURES_DIR / "sample.mp3"
    print("[generate] sample.mp3 (hand-rolled silent frames)")
    _write_silent_mp3(mp3_path)
    _tag_mp3(mp3_path)

    # FLAC — needs ffmpeg
    if have_ffmpeg:
        with tempfile.TemporaryDirectory() as td:
            tmp_wav = Path(td) / "src.wav"
            _write_silent_wav(tmp_wav)
            flac_path = FIXTURES_DIR / "sample.flac"
            print("[generate] sample.flac (ffmpeg flac encoder)")
            _ffmpeg_convert(tmp_wav, flac_path, codec="flac", fmt="flac")
            _tag_flac(flac_path)

    # AIFF — needs ffmpeg
    if have_ffmpeg:
        with tempfile.TemporaryDirectory() as td:
            tmp_wav = Path(td) / "src.wav"
            _write_silent_wav(tmp_wav)
            aiff_path = FIXTURES_DIR / "sample.aiff"
            print("[generate] sample.aiff (ffmpeg pcm_s16be in aiff)")
            _ffmpeg_convert(tmp_wav, aiff_path, codec="pcm_s16be", fmt="aiff")
            _tag_wav_aiff(aiff_path)

    print("[generate] done. Sizes:")
    for fn in ("sample.wav", "sample.mp3", "sample.flac", "sample.aiff"):
        path = FIXTURES_DIR / fn
        if path.exists():
            print(f"  {fn}: {path.stat().st_size} bytes")
        else:
            print(f"  {fn}: SKIPPED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
