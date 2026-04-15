# rekordbox-tools

A locally-hosted web app and set of Python scripts for maintaining Rekordbox 7 libraries on Windows.

> ⚠️ **Always close Rekordbox before running any tool.** All write operations create a timestamped backup of `master.db` automatically.

---

## Quick Start

**1. Install (once)**
```
Double-click install.bat
```
This checks for Python, installs all dependencies, and sets up Rekordbox database access.

**2. Launch (every time)**
```
Double-click start.bat
```
Or from PowerShell:
```powershell
python app.py
```
The app opens automatically at `http://localhost:5000`.

**3. First run**
You'll be taken to a setup screen to configure your folder paths. These are saved locally and pre-filled on every future launch.

---

## Tools

| Tool | What it does |
|------|--------------|
| **Relocate Tracks** | Re-points broken or MP3 track paths to a FLAC target folder. Preserves all cues, beatgrids, and playlists. |
| **Library Cleanup** | Finds audio files on disk not referenced in Rekordbox and moves them to a DELETE folder for review. |
| **Remove Missing** | Soft-deletes tracks from the Rekordbox DB whose files no longer exist on disk. |
| **Strip URL Comments** | Removes URLs injected into MP3/FLAC comment tags by download services, leaving all other content intact. |

---

## Requirements

- Windows 10 or 11
- Python 3.9+ ([python.org](https://www.python.org/downloads/)) — check **Add Python to PATH** during install
- Rekordbox 7 installed and opened at least once

All Python dependencies are installed automatically by `install.bat`.

---

## Safety

- **Backups first** — every script that modifies `master.db` creates a timestamped backup before writing
- **Dry run always available** — preview changes without touching anything
- **Soft deletes only** — tracks are marked deleted, never destroyed
- **Files moved, not deleted** — cleanup moves files to a review folder

---

## Recommended Workflow

### Upgrading MP3s to FLAC
1. Download FLACs into your target folder
2. Close Rekordbox
3. Open rekordbox-tools → **Relocate Tracks** → Dry Run first
4. Review output, then Run
5. Open Rekordbox — everything intact

### Periodic library maintenance
1. Close Rekordbox
2. **Remove Missing** → Dry Run → Run
3. **Library Cleanup** → Dry Run → Run
4. Review `Desktop\DELETE` before emptying

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Open an issue before starting major changes.

## License

MIT
