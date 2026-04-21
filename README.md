# rekordbox-tools

A locally-hosted web app for DJs who use **Rekordbox 7 on Windows**. Six maintenance tools for managing large music libraries — relocate tracks, clean up dead files, fix metadata, strip injected URLs from tags, and more. Runs entirely on your machine. No account, no cloud, no internet required.

> **Always close Rekordbox before running any tool.** Every script that writes to `master.db` creates a timestamped backup automatically before touching anything.

---

## Installation

### Prerequisites

Before installing, make sure you have:

- **Windows 10 or 11**
- **Python 3.9 or higher** — [download from python.org](https://www.python.org/downloads/)
  - On the Python installer screen, check **"Add Python to PATH"** before clicking Install. This is required. If you skipped it, uninstall Python and reinstall with that box checked.
- **Rekordbox 7** installed and launched at least once (so its database exists on disk)

---

### Step 1 — Download

Go to the [Releases page](https://github.com/hombreplata-cpu/rekordbocks/releases) and download the latest **Source code (zip)**.

Extract the ZIP anywhere on your computer — Desktop or `C:\Tools\` works well.

---

### Step 2 — Run the installer

Inside the extracted folder, double-click **`install.bat`**.

The installer will:
1. Confirm Python is installed and on PATH
2. Install all Python dependencies (`flask`, `pyrekordbox`, `mutagen`)
3. Run the one-time SQLCipher key setup so the app can read your Rekordbox database

> **About the SQLCipher step:** Rekordbox encrypts its database. `pyrekordbox` handles decryption automatically, but it needs a one-time setup to locate the key. The installer runs `python -m pyrekordbox install-sqlcipher` for you. If this step fails, see [Troubleshooting](#troubleshooting) below.

---

### Step 3 — Launch

Double-click **`start.bat`** to launch the app. A browser tab will open at `http://localhost:5000`.

To stop the server, close the terminal window or press `Ctrl+C` inside it.

> You can create a shortcut to `start.bat` on your Desktop for quick access.

---

### Step 4 — First-run setup

On first launch you'll be taken to a **Setup** screen. Enter the paths to:

- Your **Rekordbox database** (`master.db`) — usually at `%APPDATA%\Pioneer\rekordbox\master.db`
- Your **music folder(s)** — wherever your audio files live on disk

These paths are saved locally and pre-filled on every future launch.

---

## Tools

| Tool | What it does |
|------|--------------|
| **Relocate Tracks** | Re-points broken track paths in the Rekordbox database to a new folder. Seven-pass fuzzy matching handles renamed files, format changes (MP3→FLAC), and numeric prefixes. Preserves all cues, beatgrids, and playlists. |
| **Library Cleanup** | Scans your music folder and identifies audio files not referenced in Rekordbox. Moves them to a review folder — never permanently deletes. |
| **Remove Missing** | Soft-deletes Rekordbox DB entries for tracks whose files no longer exist on disk. Uses the same flag Rekordbox itself uses — no rows destroyed. |
| **Strip URL Comments** | Removes URLs injected into MP3/FLAC/WAV/AIFF/ALAC comment tags by download services (Beatport, Bandcamp, Traxsource, etc.). All other comment content is left intact. |
| **Fix Metadata** | Fixes stale FileType and FileSize in the DB for tracks where the path is correct but the cached metadata is wrong. Does not modify audio files. Requires "Analyze Tracks" in Rekordbox afterwards. |
| **Add New Tracks** | Scans a watch folder and adds new audio files to a chosen Rekordbox playlist, with full tag metadata (Title, Artist, Album, Genre, BPM, Year, etc.) populated from the file at insert time. |

---

## Safety

Every tool is designed to be recoverable:

- **Automatic backups** — every script that writes to `master.db` creates a timestamped backup at `%APPDATA%\Pioneer\rekordbox\` before touching anything
- **Dry run mode** — preview exactly what will change before committing
- **Soft deletes only** — tracks are marked deleted (`rb_local_deleted=1`), never destroyed
- **Files moved, not deleted** — Library Cleanup moves files to a review folder on your Desktop

To restore from a backup: close Rekordbox, copy the backup file over `master.db`, and relaunch Rekordbox.

---

## Recommended Workflows

### Upgrading a format (e.g. MP3 → FLAC)
1. Download the new files into your target folder
2. Close Rekordbox
3. Open rekordbox-tools → **Relocate Tracks** → enter source and target paths → **Dry Run**
4. Review the output — confirm matches look correct
5. Click **Run**
6. Open Rekordbox — all cues, beatgrids, and playlists intact

### Periodic library maintenance
1. Close Rekordbox
2. **Remove Missing** → Dry Run → Run (clears broken DB entries)
3. **Library Cleanup** → Dry Run → Run (finds orphaned files on disk)
4. Review the `Desktop\DELETE` folder before emptying it

### Fixing metadata after a file move
1. Close Rekordbox
2. **Fix Metadata** → Run
3. Open Rekordbox → select all affected tracks → right-click → **Analyze Tracks**

---

## Troubleshooting

**"Python not found" during install**
Python is not on your system PATH. Uninstall Python, then reinstall from [python.org](https://www.python.org/downloads/) — on the first installer screen, check **"Add Python to PATH"** before clicking Install.

**SQLCipher setup fails**
Run this manually in a terminal (Win+R → `cmd`):
```
python -m pyrekordbox install-sqlcipher
```
If it still fails, check that Rekordbox 7 has been launched at least once so its database file exists.

**"Rekordbox is open" warning banner appears**
Close Rekordbox completely before running any tool. The banner disappears automatically once Rekordbox is no longer running.

**App won't start / port already in use**
Another process is using port 5000. Run `netstat -ano | findstr :5000` in a terminal to find it, then close that process, or edit `app.py` line 1 to change the port.

**Track matching misses files**
Use the `--prefer-ext` option in Relocate Tracks to prioritise a specific format when multiple files match the same track name (e.g. prefer `.flac` over `.mp3`).

**Something went wrong with the database**
Each tool shows a "Something broke?" restore panel at the bottom of its page with step-by-step recovery instructions.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Open an issue before starting major changes.

---

## License

MIT — see [LICENSE](LICENSE).
