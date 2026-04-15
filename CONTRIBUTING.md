# Contributing to rekordbox-tools

Thanks for your interest in contributing. These tools are built by DJs for DJs — practical, safe, and focused on real library management problems.

## Dev setup

```bash
git clone https://github.com/YOUR_USERNAME/rekordbox-tools
cd rekordbox-tools
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

You'll also need a Rekordbox 7 installation and a valid `pyrekordbox` decryption key set up. See the [pyrekordbox setup guide](https://dylanljones.github.io/pyrekordbox/tutorial/setup.html).

## Guidelines

- **Always dry-run first** — any script that touches `master.db` must support `--dry-run` and create a backup before writing.
- **No personal paths in code** — all paths must be arguments or auto-detected at runtime.
- **Soft deletes only** — use `rb_local_deleted=1`, never `DELETE FROM`.
- **Keep it scriptable** — the CLI must always work without the GUI.

## Reporting issues

Please include:
- OS and Python version
- Rekordbox version
- The exact command you ran
- Full terminal output (sanitize any personal paths)

## Pull requests

Open an issue first for significant changes. Small fixes and new matching strategies for `rekordbox_relocate.py` are always welcome.
