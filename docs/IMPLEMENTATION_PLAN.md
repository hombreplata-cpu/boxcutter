# rekordbox-tools — Technical Implementation Plan

This document describes the current architecture, design decisions, and a roadmap for future development. It is intended to drive contribution planning and feature prioritization.

---

## Current Architecture

```
rekordbox-tools/
├── scripts/
│   ├── rekordbox_relocate.py       # Path re-pointing engine
│   ├── rekordbox_cleanup.py        # Orphaned file scanner/mover
│   ├── rekordbox_remove_missing.py # Missing track soft-deleter
│   └── strip_comment_urls.py       # Comment tag URL stripper
├── gui/
│   └── rekordbox_tools_gui.py      # Tkinter GUI launcher
├── docs/
│   └── IMPLEMENTATION_PLAN.md      # This file
├── requirements.txt
└── README.md
```

### Dependencies

| Package | Purpose | Notes |
|---------|---------|-------|
| `pyrekordbox` | SQLAlchemy-based ORM for Rekordbox `master.db` | Handles DB unlock/decryption |
| `mutagen` | Audio tag read/write | Used only by `strip_comment_urls` |
| `tkinter` | GUI framework | Ships with Python stdlib |

### Database access model

All DB scripts open Rekordbox's SQLite database (`master.db`) via `pyrekordbox.Rekordbox6Database`. This provides an ORM layer over the raw SQLite schema. Key tables used:

- `DjmdContent` — track metadata, file paths, file types, sizes
- Accessed via `db.get_content().filter_by(rb_local_deleted=0)`

Path storage format: Rekordbox stores paths as **forward-slash strings** regardless of OS (e.g. `C:/Users/User/Music/track.flac`). Scripts normalize to OS-native paths for filesystem operations, then convert back to forward-slash format when writing to the DB.

---

## Matching Logic (rekordbox_relocate.py)

Seven passes per track, executed in order, returning on first unambiguous match:

```
Pass 1  Exact filename match
Pass 2  "{Title} - {Artist}" stem match
Pass 3  "{Artist} - {Title}" stem match
Pass 3b Repeat 2+3 with mix/version suffix stripped from title
Pass 4  Strip numeric prefix ("00 - ") then retry stem match
Pass 5  Title substring search (title appears anywhere in filename stem)
Pass 6  Partial title match (first 25 chars) for truncated filenames
Pass 7  Fuzzy normalized match (separators/brackets collapsed to spaces)
```

Multiple matches cause a skip and are logged for manual resolution. Single match proceeds. No match is logged to the "still missing" report.

**Artist variant expansion** handles multi-artist separator inconsistencies:
- Rekordbox stores: `Artist A / Artist B`
- Filenames may use: `Artist A; Artist B` or `Artist A, Artist B`
- Variants generated: raw, semicolon-separated, comma-separated, first artist only

---

## Roadmap

### Phase 1 — Stability & Packaging (near-term)

**P1-01: Installer / first-run wizard**
- Detect Rekordbox installation and auto-populate `master.db` path
- Validate `pyrekordbox` decryption key is present
- Walk user through path configuration with filesystem browser
- Write config to `~/.rekordbox_tools_config.json`

**P1-02: Packaged binary (PyInstaller)**
- Single `.exe` (Windows) and `.app` (macOS) bundle
- No Python installation required for end users
- GitHub Actions CI to build and attach to releases on tag push

**P1-03: Test suite**
- Unit tests for `find_match()` matching logic with synthetic filenames
- Unit tests for `artist_variants()` separator expansion
- Unit tests for `strip_urls()` regex coverage
- Integration test fixture: minimal synthetic `master.db` for full pipeline testing

**P1-04: Logging**
- Replace `print()` statements with structured `logging` module output
- Log file written to `~/.rekordbox_tools/logs/` with rotation
- GUI console reads from log stream

---

### Phase 2 — GUI Improvements (mid-term)

**P2-01: Progress bars**
- Indeterminate progress bar during long scans
- Track count / percentage for relocate and cleanup runs

**P2-02: Interactive results tables**
- Post-run table view of relocated/cleaned/removed tracks
- Sortable, filterable columns (title, artist, old path, new path, match type)
- Export results to CSV

**P2-03: Multi-match resolver**
- Tracks skipped due to multiple matches displayed in a resolution UI
- User selects correct file from candidate list per track
- Writes selected mapping to DB on confirm

**P2-04: Conflict / ambiguity highlights**
- Color-code match types in results (exact = green, fuzzy = orange, no match = red)
- Inline diff view for path changes

**P2-05: Settings persistence improvements**
- Per-tool option persistence (dry-run toggle state, prefer-ext, etc.)
- Multiple named "profiles" for different library setups

---

### Phase 3 — New Tools (longer-term)

**P3-01: Duplicate finder**
- Identify duplicate tracks in the Rekordbox DB by title+artist similarity
- Cross-reference file sizes and bitrates to suggest which copy to keep
- Optional: waveform fingerprint comparison via `acoustid`/`chromaprint`

**P3-02: BPM / key batch analyzer**
- Trigger Rekordbox's analysis on unanalyzed tracks via AppleScript (macOS) or COM (Windows)
- Alternatively: run standalone analysis with `librosa` or `essentia`

**P3-03: Playlist export / sync**
- Export Rekordbox playlists to M3U, CSV, or Rekordbox XML
- Import from Lexicon XML or CSV into Rekordbox playlists

**P3-04: Smart cleanup modes**
- `--min-age DAYS` — only move files not modified in N days
- `--min-size MB` — skip files below size threshold
- `--extensions-only` — cleanup only specific formats (e.g. stale MP3s when FLACs exist)

**P3-05: macOS support hardening**
- Rekordbox stores paths differently on macOS (`/Users/...` vs Windows `C:/Users/...`)
- Add explicit macOS path normalization and test coverage
- CI matrix: test on both `windows-latest` and `macos-latest`

---

### Phase 4 — Infrastructure

**P4-01: GitHub Actions workflows**
```
.github/workflows/
├── test.yml       # Run pytest on push/PR (Windows + macOS)
├── release.yml    # Build PyInstaller binary on tag push
└── lint.yml       # ruff / flake8 on push
```

**P4-02: Contribution tooling**
- `pre-commit` config: `ruff`, `black`, `mypy`
- `CONTRIBUTING.md` with dev setup instructions
- Issue and PR templates

**P4-03: pyrekordbox version pinning strategy**
- `pyrekordbox` DB schema can change between Rekordbox releases
- Add version detection and warn if schema mismatch detected
- Maintain compatibility matrix in README

---

## Open Questions

1. **macOS path handling**: Rekordbox on macOS may store paths with `/Volumes/` or `~/` prefixes. The current normalization logic is Windows-focused. Needs a macOS contributor to validate.

2. **Rekordbox 7 vs 6 schema**: `pyrekordbox` targets Rekordbox 6 schema but also works with Rekordbox 7 in practice. Explicit version detection would improve reliability.

3. **pyrekordbox decryption**: The DB key extraction step is handled by `pyrekordbox` setup, but if Pioneer changes the encryption in a Rekordbox update, this pipeline breaks. Monitoring upstream is required.

4. **GUI framework**: `tkinter` is stdlib but limited visually. Candidates for migration if a richer UI is needed: `PyQt6`, `customtkinter`, or a web-based frontend via `Flask` + `Electron`/`Tauri`.

---

## Data Flow Diagrams

### rekordbox_relocate.py

```
Disk: target_root/
    ├── exact_index   {filename.lower() -> [path]}
    ├── stem_index    {stem.lower() -> [path]}
    └── norm_index    {normalize_stem -> [path]}
                            │
                            ▼
Rekordbox DB
    └── DjmdContent (rb_local_deleted=0)
            │
            for each track:
            │   FolderPath → normalize → filename + title + artist
            │
            ▼
        find_match() → 7-pass lookup
            │
    ┌───────┴────────┐
    │                │
  1 match         0 or N+ matches
    │                │
  update DB       log for review
```

### rekordbox_cleanup.py

```
Rekordbox DB → active_paths set (normcase)

Disk scan: scan_root/
    └── all audio files → normcase path

Set difference:
    disk_files - active_paths = unreferenced

unreferenced → move to DELETE/ (preserving subfolder structure)
```
