"""
app.py — rekordbox-tools web server

Start with:
    python app.py

Then open http://localhost:5000 in your browser.
"""

import json
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)

CONFIG_FILE = Path.home() / ".rekordbox_tools_config.json"
SCRIPTS_DIR = Path(__file__).parent / "scripts"

DEFAULT_CONFIG = {
    "music_root": "",
    "flac_root": "",
    "mp3_root": "",
    "delete_dir": str(Path.home() / "Desktop" / "DELETE"),
    "watch_dir": "",
}

HISTORY_FILE = Path.home() / ".rekordbox_tools_history.json"

TOOL_LABELS = {
    "relocate": "Relocate Tracks",
    "cleanup": "Library Cleanup",
    "remove_missing": "Remove Missing",
    "strip_comments": "Strip URL Comments",
    "fix_metadata": "Fix Metadata",
    "add_new": "Add New Tracks",
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(data)
            return cfg
        except Exception:  # noqa: S110 — config load failure is expected; fall back to defaults
            pass
    return DEFAULT_CONFIG.copy()


def save_config(data):
    cfg = load_config()
    cfg.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def config_is_complete(cfg):
    return bool(cfg.get("music_root") and cfg.get("flac_root"))


def clean_path(raw):
    """Strip surrounding whitespace and quotes that Windows 'Copy as path' adds."""
    if not raw:
        return raw
    return raw.strip().strip('"').strip("'").strip()


def get_rekordbox_backup_dir(db_path=""):
    """Return the directory that contains master.db and its backups.

    If db_path is configured, backups live alongside that file.
    Otherwise fall back to the default Pioneer\\rekordbox folder.
    """
    if db_path:
        return Path(db_path).parent
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Pioneer" / "rekordbox"


def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except Exception:  # noqa: S110 — corrupt history file is non-fatal; fall back to empty list
            pass
    return []


def save_history_entry(entry):
    history = load_history()
    history.insert(0, entry)  # newest first
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception:  # noqa: S110 — history write failure is non-fatal; run continues normally
        pass


def rekordbox_is_running():
    """Return True if rekordbox.exe is in the Windows process list."""
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq rekordbox.exe", "/NH"],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return "rekordbox.exe" in out.lower()
    except Exception:
        return False


# ── Routes ───────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    cfg = load_config()
    if not config_is_complete(cfg):
        return redirect(url_for("setup"))
    return render_template("dashboard.html", cfg=cfg)


@app.route("/setup", methods=["GET", "POST"])
def setup():
    cfg = load_config()
    saved = False
    if request.method == "POST":
        cfg = save_config(
            {
                "music_root": clean_path(request.form.get("music_root", "")),
                "flac_root": clean_path(request.form.get("flac_root", "")),
                "mp3_root": clean_path(request.form.get("mp3_root", "")),
                "delete_dir": clean_path(request.form.get("delete_dir", "")),
                "watch_dir": clean_path(request.form.get("watch_dir", "")),
            }
        )
        saved = True
        if config_is_complete(cfg):
            return redirect(url_for("index"))
    return render_template("setup.html", cfg=cfg, saved=saved)


@app.route("/tool/<n>")
def tool(n):
    cfg = load_config()
    tools = {
        "relocate": ("Relocate Tracks", "relocate.html"),
        "cleanup": ("Library Cleanup", "cleanup.html"),
        "remove_missing": ("Remove Missing Tracks", "remove_missing.html"),
        "strip_comments": ("Strip URL Comments", "strip_comments.html"),
        "fix_metadata": ("Fix Metadata", "fix_metadata.html"),
        "add_new": ("Add New Tracks", "add_new.html"),
    }
    if n not in tools:
        return redirect(url_for("index"))
    title, template = tools[n]
    return render_template(template, cfg=cfg, title=title)


@app.route("/api/config", methods=["POST"])
def api_config():
    data = request.get_json()
    cfg = save_config(data)
    return jsonify({"ok": True, "config": cfg})


@app.route("/api/rekordbox_status")
def api_rekordbox_status():
    """Check whether rekordbox.exe is currently running."""
    return jsonify({"running": rekordbox_is_running()})


@app.route("/api/run/<script_name>")
def api_run(script_name):
    """Stream script output as server-sent events."""
    allowed = {
        "relocate": "rekordbox_relocate.py",
        "cleanup": "rekordbox_cleanup.py",
        "remove_missing": "rekordbox_remove_missing.py",
        "strip_comments": "strip_comment_urls.py",
        "fix_metadata": "rekordbox_fix_metadata.py",
        "add_new": "rekordbox_add_new.py",
    }
    if script_name not in allowed:
        return jsonify({"error": "unknown script"}), 400

    script_path = SCRIPTS_DIR / allowed[script_name]
    cfg = load_config()

    args = []
    dry_run = request.args.get("dry_run") == "1"

    if script_name == "relocate":
        target = clean_path(request.args.get("target_root") or cfg.get("flac_root", ""))
        source = clean_path(request.args.get("source_root") or cfg.get("mp3_root", ""))
        if not target:
            return jsonify({"error": "target_root required"}), 400
        args += ["--target-root", target]
        if source:
            args += ["--source-root", source]
        if request.args.get("missing_only") == "1":
            args.append("--missing-only")
        if request.args.get("all_tracks") == "1":
            args.append("--all-tracks")
        pref = clean_path(request.args.get("prefer_ext", "flac"))
        args += ["--prefer-ext", pref]

    elif script_name == "cleanup":
        scan = clean_path(request.args.get("scan_root") or cfg.get("music_root", ""))
        delete_dir = clean_path(request.args.get("delete_dir") or cfg.get("delete_dir", ""))
        exclude = clean_path(request.args.get("exclude", ""))
        if not scan:
            return jsonify({"error": "scan_root required"}), 400
        args += ["--scan-root", scan]
        if delete_dir:
            args += ["--delete-dir", delete_dir]
        if exclude:
            args += ["--exclude", exclude]

    elif script_name == "strip_comments":
        dirs = [
            clean_path(request.args.get("dir1") or cfg.get("music_root", "")),
            clean_path(request.args.get("dir2", "")),
        ]
        dirs = [d for d in dirs if d]
        if not dirs:
            return jsonify({"error": "at least one directory required"}), 400
        args += dirs
        if not dry_run:
            args.append("--write")
        dry_run = False

    elif script_name == "fix_metadata":
        ids = clean_path(request.args.get("ids", ""))
        if ids:
            args += ["--ids", ids]

    elif script_name == "add_new":
        watch_dir = clean_path(request.args.get("watch_dir") or cfg.get("watch_dir", ""))
        playlist_id = request.args.get("playlist_id", "")
        if not watch_dir:
            return jsonify({"error": "watch_dir required"}), 400
        if not playlist_id:
            return jsonify({"error": "playlist_id required"}), 400
        args += ["--watch-dir", watch_dir, "--playlist-id", playlist_id]

    if dry_run:
        args.append("--dry-run")

    cmd = [sys.executable, str(script_path)] + args

    def generate():
        backup_path = None
        report_data = None

        yield f"data: $ {' '.join(cmd)}\n\n"
        yield "data: \n\n"
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        report_lines = []
        in_report = False

        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()

            # Capture backup path printed by DB scripts
            if line.startswith("[backup] ") and "WARNING" not in line:
                backup_path = line[len("[backup] ") :]

            if line == "%%REPORT_START%%":
                in_report = True
                report_lines = []
                continue
            if line == "%%REPORT_END%%":
                in_report = False
                # Emit as a named SSE event — delivered atomically to the client
                payload = "".join(report_lines)
                try:
                    report_data = json.loads(payload)
                except Exception:
                    report_data = None
                yield f"event: report\ndata: {payload}\n\n"
                continue
            if in_report:
                report_lines.append(line)
                continue

            yield f"data: {line}\n\n"

        proc.stdout.close()
        proc.wait()

        # Persist a history entry for every completed run
        ts = datetime.now()
        save_history_entry(
            {
                "id": f"{ts.strftime('%Y%m%d_%H%M%S')}_{script_name}",
                "tool": script_name,
                "tool_label": TOOL_LABELS.get(script_name, script_name),
                "timestamp": ts.isoformat(),
                "dry_run": dry_run,
                "backup_path": backup_path,
                "summary": report_data.get("summary") if report_data else None,
            }
        )

        yield "data: %%DONE%%\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/playlists")
def api_playlists():
    """Return all normal (non-folder, non-smart) Rekordbox playlists as JSON.

    Runs get_playlists.py as a subprocess so pyrekordbox is imported in the
    same Python environment used by all other rekordbox-tools scripts.
    """
    script_path = SCRIPTS_DIR / "get_playlists.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or "Unknown error reading playlists"
            return jsonify({"error": msg}), 500
        return result.stdout, 200, {"Content-Type": "application/json"}
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out reading Rekordbox database"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/history")
def history_page():
    return render_template("history.html")


@app.route("/backup_cleaner")
def backup_cleaner_page():
    return render_template("backup_cleaner.html")


@app.route("/api/history")
def api_history():
    history = load_history()
    page = max(1, int(request.args.get("page", 1)))
    per_page = max(1, min(100, int(request.args.get("per_page", 20))))
    total = len(history)
    start = (page - 1) * per_page
    entries = history[start : start + per_page]
    for entry in entries:
        bp = entry.get("backup_path")
        entry["backup_exists"] = Path(bp).exists() if bp else None
    return jsonify(
        {
            "entries": entries,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }
    )


@app.route("/api/history", methods=["DELETE"])
def api_history_clear():
    try:
        if HISTORY_FILE.exists():
            HISTORY_FILE.unlink()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/backups")
def api_backups():
    cfg = load_config()
    db_path = clean_path(cfg.get("db_path", ""))
    backup_dir = get_rekordbox_backup_dir(db_path)
    if not backup_dir.exists():
        return jsonify({"error": f"Directory not found: {backup_dir}"}), 404
    now = datetime.now()
    files = []
    for f in backup_dir.glob("master_backup_*.db"):
        try:
            stat = f.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime)
            age_days = (now - mtime).days
            files.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "size": stat.st_size,
                    "modified": mtime.isoformat(),
                    "age_days": age_days,
                }
            )
        except Exception:  # noqa: S110 — unreadable backup file is skipped; rest of list still returned
            pass
    files.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify({"backups": files, "backup_dir": str(backup_dir)})


@app.route("/api/backups/clean", methods=["POST"])
def api_backups_clean():
    data = request.get_json() or {}
    try:
        keep_days = max(1, int(data.get("keep_days", 30)))
    except (TypeError, ValueError):
        return jsonify({"error": "keep_days must be a positive integer"}), 400
    dry_run = bool(data.get("dry_run", False))
    cfg = load_config()
    db_path = clean_path(cfg.get("db_path", ""))
    backup_dir = get_rekordbox_backup_dir(db_path)
    if not backup_dir.exists():
        return jsonify({"error": f"Directory not found: {backup_dir}"}), 404
    now = datetime.now()
    deleted = []
    errors = []
    for f in backup_dir.glob("master_backup_*.db"):
        try:
            stat = f.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime)
            age_days = (now - mtime).days
            if age_days > keep_days:
                if not dry_run:
                    f.unlink()
                deleted.append(
                    {
                        "name": f.name,
                        "path": str(f),
                        "age_days": age_days,
                        "size": stat.st_size,
                    }
                )
        except Exception as exc:
            errors.append({"path": str(f), "error": str(exc)})
    return jsonify(
        {
            "deleted": deleted,
            "errors": errors,
            "dry_run": dry_run,
            "keep_days": keep_days,
        }
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  rekordbox-tools")
    print("  ───────────────────────────────")
    print("  Starting server at http://localhost:5000")
    print("  Press Ctrl+C to stop\n")
    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(debug=False, port=5000)
