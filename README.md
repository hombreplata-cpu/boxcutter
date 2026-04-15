# rekordbox-tools

A collection of Python scripts (and a GUI launcher) for maintaining and cleaning Rekordbox 7 libraries. Built for DJs who manage large collections and want programmatic control over their database.

> ⚠️ **Always close Rekordbox before running any script.** All write operations create a timestamped backup of `master.db` automatically.

---

## Tools

| Script | What it does |
|--------|--------------|
| `rekordbox_relocate.py` | Re-points broken or MP3 track paths to a new folder (e.g. an upgraded FLAC library) |
| `rekordbox_cleanup.py` | Finds audio files on disk not referenced in Rekordbox and moves them to a DELETE folder |
| `rekordbox_remove_missing.py` | Soft-deletes tracks from the DB whose files no longer exist on disk |
| `strip_comment_urls.py` | Strips URLs from MP3/FLAC comment tags, preserving all other content |

---

## Requirements

- Python 3.9+
- Rekordbox 7 (Windows or macOS)

```bash
pip install -r requirements.txt
```

Dependencies:
- [`pyrekordbox`](https://github.com/dylanljones/pyrekordbox) — Rekordbox DB access
- [`mutagen`](https://mutagen.readthedocs.io/) — Audio tag reading/writing (for `strip_comment_urls.py` only)

### pyrekordbox setup note

`pyrekordbox` needs to unlock the Rekordbox SQLite database (which is encrypted). Follow the [pyrekordbox setup instructions](https://dylanljones.github.io/pyrekordbox/tutorial/setup.html) to configure the key before first use.

---

## GUI Launcher

A Lexicon-inspired dark-mode GUI is available for users who prefer not to use the command line.

```bash
python gui/rekordbox_tools_gui.py
```

On first launch, go to **Setup & Paths** and configure your library folders. These are saved to `~/.rekordbox_tools_config.json`.

---

## Scripts

### `rekordbox_relocate.py`

Re-points track paths inside `master.db` to files in a new target root. Useful when:
- Upgrading an MP3 library to FLAC
- Files have moved to a new drive or folder
- Track paths are broken after a sync or OS migration

**Six-pass matching strategy** — tries exact filename, Title-Artist, Artist-Title, numeric prefix stripping, substring search, and fuzzy normalized matching in order.

```bash
# Dry run — preview what would change:
python scripts/rekordbox_relocate.py \
    --target-root "D:\Music\FLAC" \
    --dry-run

# Migrate MP3s that now have a FLAC equivalent:
python scripts/rekordbox_relocate.py \
    --target-root "D:\Music\FLAC" \
    --source-root "D:\Music\MP3"

# Only process tracks whose file is missing (broken paths):
python scripts/rekordbox_relocate.py \
    --target-root "D:\Music\FLAC" \
    --missing-only
```

**Options:**

| Flag | Description |
|------|-------------|
| `--target-root DIR` | *(required)* Destination folder to match files in |
| `--source-root DIR` | Migrate tracks from this folder even if the file still exists |
| `--dry-run` | Preview only — nothing is written |
| `--missing-only` | Only process tracks whose file is missing on disk |
| `--all-tracks` | Re-check all tracks, even those that already resolve |
| `--prefer-ext EXT` | Preferred extension when multiple matches exist (default: `flac`) |
| `--extensions LIST` | Comma-separated extensions to index (default: mp3,flac,wav,aiff,...) |
| `--ids ID_LIST` | Comma-separated track IDs to process (for targeted fixes) |

---

### `rekordbox_cleanup.py`

Scans a folder for audio files and moves any that are **not** referenced in the Rekordbox database to a `DELETE` folder. Files are moved (not deleted) so you can review before clearing.

```bash
# Dry run:
python scripts/rekordbox_cleanup.py \
    --scan-root "D:\Music" \
    --dry-run

# Live run:
python scripts/rekordbox_cleanup.py \
    --scan-root "D:\Music"

# Exclude a subfolder:
python scripts/rekordbox_cleanup.py \
    --scan-root "D:\Music" \
    --exclude "D:\Music\FLAC"
```

**Options:**

| Flag | Description |
|------|-------------|
| `--scan-root DIR` | *(required)* Folder to scan |
| `--exclude DIR` | Subfolder to exclude (repeat for multiple) |
| `--delete-dir DIR` | Where to move unreferenced files (default: `Desktop\DELETE`) |
| `--dry-run` | Preview only — nothing is moved |
| `--extensions LIST` | Comma-separated extensions to check |

---

### `rekordbox_remove_missing.py`

Soft-deletes Rekordbox DB entries for tracks whose files no longer exist on disk. Uses `rb_local_deleted=1`, identical to how Rekordbox removes tracks internally — no rows are destroyed.

```bash
# Dry run:
python scripts/rekordbox_remove_missing.py --dry-run

# Live run:
python scripts/rekordbox_remove_missing.py
```

---

### `strip_comment_urls.py`

Crawls MP3 and FLAC files and removes URLs from comment tags. URLs are often injected by download services (Beatport, Bandcamp, etc.) and can clutter Rekordbox's comment display.

- MP3: removes URLs from all `COMM` (ID3) frames
- FLAC: removes URLs from `COMMENT` and `DESCRIPTION` Vorbis fields
- All other comment content is preserved

```bash
# Dry run — preview what would change:
python scripts/strip_comment_urls.py "D:\Music"

# Write changes:
python scripts/strip_comment_urls.py "D:\Music" --write

# Multiple directories:
python scripts/strip_comment_urls.py "D:\Music" "E:\MoreMusic" --write
```

---

## Safety

- **Backups first** — every script that modifies `master.db` creates a timestamped backup (e.g. `master_backup_20250415_143022.db`) in the same directory before writing anything.
- **Dry run always available** — all scripts support `--dry-run` to preview changes without touching anything.
- **Soft deletes only** — `rekordbox_remove_missing.py` sets `rb_local_deleted=1` rather than deleting rows. Your cues, beatgrids, and play counts are preserved.
- **Files moved, not deleted** — `rekordbox_cleanup.py` moves files to a review folder, it never permanently deletes anything.

---

## Recommended Workflow

### Upgrading MP3s to FLAC

1. Download FLACs into your target folder
2. Close Rekordbox
3. Run `rekordbox_relocate.py --target-root <FLAC folder> --source-root <MP3 folder> --dry-run`
4. Review output, then re-run without `--dry-run`
5. Open Rekordbox — cues, beatgrids, and playlists are intact

### Periodic library cleanup

1. Close Rekordbox
2. Run `rekordbox_remove_missing.py --dry-run` to see what's broken
3. Run without `--dry-run` to soft-delete missing entries
4. Run `rekordbox_cleanup.py --scan-root <music folder> --dry-run` to find orphaned files
5. Run without `--dry-run`, then review `Desktop\DELETE` before emptying

---

## Contributing

Pull requests welcome. Please open an issue first to discuss major changes.

---

## License

MIT
