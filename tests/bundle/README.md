# Bundle smoke tests

These tests run against the **built artifact** (`BoxCutter.exe` on Windows,
`BoxCutter.app` on macOS) — not against the source tree. They are the only
layer of testing that catches regressions like:

- Missing PyInstaller hidden imports (e.g. mutagen submodules — REG-001)
- Missing data files (templates / static assets not in `app.spec`)
- `_MEIPASS` path miscalculation
- Inno Setup misconfiguration
- DOM form CSRF gaps that bypass `window.fetch` monkey-patching (REG-002)
- Anything that "works in source, breaks in bundle"

Source-tree pytest cannot catch any of the above. The full 487-test source
suite was green when the v1.0.0-rc1 build crashed every tag-touching tool
with `ImportError: No module named 'mutagen.flac'`. Bundle-smoke is the
test gate with teeth.

## Architecture

```
tests/bundle/
├── README.md                   ← you are here
├── generate_fixtures.py        ← regenerates audio fixtures (manual, one-time)
├── fixtures/
│   └── audio/
│       ├── sample.wav   ~6 KB  ← 0.1 s silence + ID3 tags + URL comment
│       ├── sample.mp3   ~2 KB  ← hand-rolled silent MPEG frames + ID3
│       ├── sample.flac  ~8 KB  ← silence + Vorbis tags + URL comment
│       └── sample.aiff  ~6 KB  ← silence + embedded ID3 + URL comment
├── verify_imports.py           ← runs INSIDE the bundle, asserts every
│                                  scripts/*.py import works
└── run_all_scripts.py          ← runs INSIDE the bundle, exercises every
                                   production script against the fixtures
```

## Why fixtures are checked in

The `fixtures/audio/` files are tiny (<25 KB combined), binary-stable,
and need to be available to CI runners that don't have ffmpeg. Generating
them at CI time would add 30s + a system dependency to every smoke run.
Checking them in trades 25 KB of repo size for deterministic, reproducible
tests with no external tooling.

To regenerate (e.g. to add a new format or change the embedded comment):
```bash
python tests/bundle/generate_fixtures.py
```
Requires ffmpeg on PATH for FLAC/AIFF. WAV and MP3 are stdlib-only.

## What the fixtures verify

The `COMMENT` field on every fixture intentionally contains the URL
`beatport.com/abc` so `strip_comment_urls.py` can prove it stripped exactly
the URL and left the surrounding boilerplate-aware text (`bundle-smoke URL
bait`). All other tag fields (Title, Artist, Album, Genre, Year, Track, BPM)
are populated so `relocate.py` / `add_new.py` / `fix_metadata.py` have rich
data to read from.

## Known fixture gaps

- **No `sample.m4a`** — generating M4A requires a full ffmpeg with AAC
  encoder support. The Windows audio-only ffmpeg used to produce the other
  fixtures cannot encode AAC. M4A coverage is provided by the import
  contract test (`verify_imports.py` confirms `mutagen.mp4` is in the
  bundle); a real fixture file can be added later if the script-run test
  needs to exercise M4A tag manipulation directly.

## Test ordering and dependencies

| PR | Adds | Catches |
|----|------|---------|
| 2 (this) | Fixtures only | — |
| 3 | `verify_imports.py` | Mutagen-class hidden-import gaps |
| 4 | `run_all_scripts.py` | Script-run regressions, packaging path bugs |
| 5 | Playwright UI suite | DOM form CSRF gaps, frontend regressions |
| 6 | `bundle-smoke.yml` workflow | Wires it all into CI |
| 7 | `release.yml` integration | Makes bundle-smoke a release-blocker |

This PR is fixtures-only. The tests that consume them land in subsequent PRs.
