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
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for, Response

app = Flask(__name__)

CONFIG_FILE = Path.home() / ".rekordbox_tools_config.json"
SCRIPTS_DIR = Path(__file__).parent / "scripts"

DEFAULT_CONFIG = {
    "music_root":   "",
    "flac_root":    "",
    "mp3_root":     "",
    "delete_dir":   str(Path.home() / "Desktop" / "DELETE"),
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(data)
            return cfg
        except Exception:
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
        cfg = save_config({
            "music_root":  clean_path(request.form.get("music_root", "")),
            "flac_root":   clean_path(request.form.get("flac_root", "")),
            "mp3_root":    clean_path(request.form.get("mp3_root", "")),
            "delete_dir":  clean_path(request.form.get("delete_dir", "")),
        })
        saved = True
        if config_is_complete(cfg):
            return redirect(url_for("index"))
    return render_template("setup.html", cfg=cfg, saved=saved)


@app.route("/tool/<n>")
def tool(n):
    cfg = load_config()
    tools = {
        "relocate":       ("Relocate Tracks",       "relocate.html"),
        "cleanup":        ("Library Cleanup",        "cleanup.html"),
        "remove_missing": ("Remove Missing Tracks",  "remove_missing.html"),
        "strip_comments": ("Strip URL Comments",     "strip_comments.html"),
        "fix_metadata":   ("Fix Metadata",           "fix_metadata.html"),
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
        "relocate":       "rekordbox_relocate.py",
        "cleanup":        "rekordbox_cleanup.py",
        "remove_missing": "rekordbox_remove_missing.py",
        "strip_comments": "strip_comment_urls.py",
        "fix_metadata":   "rekordbox_fix_metadata.py",
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
        scan       = clean_path(request.args.get("scan_root") or cfg.get("music_root", ""))
        delete_dir = clean_path(request.args.get("delete_dir") or cfg.get("delete_dir", ""))
        exclude    = clean_path(request.args.get("exclude", ""))
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

    if dry_run:
        args.append("--dry-run")

    cmd = [sys.executable, str(script_path)] + args

    def generate():
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
        in_report    = False

        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()

            if line == "%%REPORT_START%%":
                in_report = True
                report_lines = []
                continue
            if line == "%%REPORT_END%%":
                in_report = False
                # Emit as a named SSE event — delivered atomically to the client
                payload = "".join(report_lines)
                yield f"event: report\ndata: {payload}\n\n"
                continue
            if in_report:
                report_lines.append(line)
                continue

            yield f"data: {line}\n\n"

        proc.stdout.close()
        proc.wait()
        yield "data: %%DONE%%\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  rekordbox-tools")
    print("  ───────────────────────────────")
    print("  Starting server at http://localhost:5000")
    print("  Press Ctrl+C to stop\n")
    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(debug=False, port=5000)
