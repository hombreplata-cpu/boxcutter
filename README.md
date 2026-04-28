# BoxCutter

A locally-hosted web app for DJs who use **Rekordbox 7 on Windows or macOS**. Six maintenance tools for managing large music libraries — relocate tracks, clean up dead files, fix metadata, strip injected URLs from tags, and more. Runs entirely on your machine. No account, no cloud, no internet required.

> **Always close Rekordbox before running any tool.** Every script that writes to `master.db` creates a timestamped backup automatically before touching anything.

---

## Installation

### Windows

#### Option A — Packaged installer (no Python required)

1. Go to the [Releases page](https://github.com/hombreplata-cpu/boxcutter/releases) and download **`BoxCutter-Setup-<version>.exe`**.
2. Run the installer — it installs to your user folder, no admin rights needed.
3. Launch BoxCutter from the Start Menu or Desktop shortcut. Your browser opens at `http://localhost:5000` automatically.

> **Windows SmartScreen warning:** Because the binary is unsigned, Windows may show a "Windows protected your PC" prompt. Click **More info → Run anyway** to proceed. This is expected for open-source tools distributed outside the Microsoft Store.

#### Option B — Run from source (requires Python)

**Prerequisites:**
- **Windows 10 or 11**
- **Python 3.9 or higher** — [download from python.org](https://www.python.org/downloads/)
  - On the Python installer screen, check **"Add Python to PATH"** before clicking Install.
- **Rekordbox 7** installed and launched at least once (so its database exists on disk)

Download the latest **Source code (zip)** from the [Releases page](https://github.com/hombreplata-cpu/boxcutter/releases), extract it anywhere, then:

```
install.bat   ← run once to install dependencies
start.bat     ← run anytime to launch
```

> **About the SQLCipher step:** Rekordbox encrypts its database. `pyrekordbox` handles decryption automatically, but needs a one-time setup to locate the key. The installer runs this for you.

---

### macOS

#### Option A — Packaged DMG (no Python required)

1. Go to the [Releases page](https://github.com/hombreplata-cpu/boxcutter/releases) and download **`BoxCutter-<version>.dmg`**.
2. Open the `.dmg` and drag **BoxCutter** to your Applications folder.
3. **Required first-launch step** — open Terminal and run:
   ```bash
   xattr -dr com.apple.quarantine /Applications/BoxCutter.app
   ```
   This removes macOS's "downloaded from the internet" tag. Without it the app will bounce in the Dock once and silently fail to open. You only need to do this once per download.
4. Double-click **BoxCutter** in Applications to launch. Your browser will open at `http://localhost:5000` automatically.

> **Why the Terminal step?** BoxCutter is ad-hoc signed but not notarized (notarization requires a paid Apple Developer account). Without notarization, macOS quarantines the bundle on download and blocks it from launching until the quarantine flag is cleared. The `xattr` command removes that flag — it is **not** running BoxCutter or installing anything, just clearing one OS attribute.

#### Option B — Run from source (requires Python)

**Prerequisites:**
- **macOS 11 (Big Sur) or later**
- **Python 3.9 or higher** — [python.org](https://www.python.org/downloads/) or `brew install python`
- **Rekordbox 7** installed and launched at least once

Download the latest **Source code (zip)** from the [Releases page](https://github.com/hombreplata-cpu/boxcutter/releases), extract it, then:

```bash
chmod +x install.sh && ./install.sh
./start.sh
```

> **Apple Silicon SQLCipher fallback:** If `install.sh` fails at the SQLCipher step, run `brew install sqlcipher` first, then re-run `./install.sh`.

---

### First-run setup (both options)

On first launch you'll be taken to a **Setup** screen. Enter the paths to:

- Your **Rekordbox database** (`master.db`) — usually at `%APPDATA%\Pioneer\rekordbox\master.db` (Windows) or `~/Library/Application Support/Pioneer/rekordbox/master.db` (macOS)
- Your **music folder(s)** — wherever your audio files live on disk

These paths are saved locally and pre-filled on every future launch.

---

## Test builds (bleeding edge — not for production)

Every push to `main` automatically builds a Windows installer and a macOS `.dmg` from the latest source. These are **unverified test builds**. They have not been through release-gate testing and may contain bugs that the official releases do not. For day-to-day use, always download from the [Releases page](https://github.com/hombreplata-cpu/boxcutter/releases) instead.

Use a test build only when:

- You want to try a feature or fix that has not yet shipped in a formal release
- A maintainer asks you to test a build before tagging
- You are contributing code and want to verify your change against a real installer

### Where to find them

1. Open the [latest test-build runs on `main`](https://github.com/hombreplata-cpu/boxcutter/actions/workflows/build-test-artifacts.yml?query=branch%3Amain).
2. Click the topmost entry with a **green check** (a successful build).
3. Scroll to the bottom of the run page to the **Artifacts** section.
4. Download the artifact for your platform:
   - Windows: `BoxCutter-Setup-0.0.0-main-<sha>.exe`
   - macOS: `BoxCutter-0.0.0-main-<sha>.dmg`

The version stamp in the filename (`0.0.0-main-<short-sha>`) identifies the commit a build came from — useful when reporting a bug.

### Two limits to know

- **You must be signed into GitHub.** Anonymous users cannot download workflow artifacts, even from public repositories.
- **Artifacts expire after 14 days.** If you need an older build, ask a maintainer to re-run that workflow.

### Installing a test build

Same install steps as the Releases-page version of your platform:

- **Windows** — run the `.exe` installer. The SmartScreen warning is expected for unsigned binaries; click **More info → Run anyway**.
- **macOS** — drag `BoxCutter.app` to `/Applications`, then run the quarantine-clearing command in Terminal before first launch:
  ```bash
  xattr -dr com.apple.quarantine /Applications/BoxCutter.app
  ```
  (See [macOS Option A](#option-a--packaged-dmg-no-python-required) for why.)

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

- **Automatic backups** — every script that writes to `master.db` creates a timestamped backup in `boxcutter-backups/` next to `master.db` before touching anything
- **Dry run mode** — preview exactly what will change before committing
- **Soft deletes only** — tracks are marked deleted (`rb_local_deleted=1`), never destroyed
- **Files moved, not deleted** — Library Cleanup moves files to a review folder on your Desktop

To restore from a backup: close Rekordbox, copy the backup file over `master.db`, and relaunch Rekordbox.

---

## Recommended Workflows

### Upgrading a format (e.g. MP3 → FLAC)
1. Download the new files into your target folder
2. Close Rekordbox
3. Open BoxCutter → **Relocate Tracks** → enter source and target paths → **Dry Run**
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

**"Python not found" during install (Windows)**
Python is not on your system PATH. Uninstall Python, then reinstall from [python.org](https://www.python.org/downloads/) — on the first installer screen, check **"Add Python to PATH"** before clicking Install.

**SQLCipher setup fails (Windows)**
Run this manually in a terminal (Win+R → `cmd`):
```
python -m pyrekordbox install-sqlcipher
```
If it still fails, check that Rekordbox 7 has been launched at least once so its database file exists.

**SQLCipher setup fails on Apple Silicon Mac (M1/M2/M3)**
Pre-built SQLCipher wheels sometimes don't exist for ARM. Install SQLCipher via Homebrew first, then re-run the installer:
```bash
brew install sqlcipher
./install.sh
```

**"Rekordbox is open" warning banner appears**
Close Rekordbox completely before running any tool. The banner disappears automatically once Rekordbox is no longer running.

**App won't start / port already in use**
Another process is using port 5000. BoxCutter will attempt to free it automatically if the conflict is a previous BoxCutter instance. For other apps, close the conflicting process or find a free port manually.

**Track matching misses files**
Use the **Prefer Extension** option in Relocate Tracks to prioritise a specific format when multiple files match the same track name (e.g. prefer `.flac` over `.mp3`).

**Something went wrong with the database**
Each tool has a built-in **Restore Backup** page with step-by-step recovery instructions, or navigate directly to `/restore`.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Open an issue before starting major changes.

---

## License

MIT — see [LICENSE](LICENSE).
