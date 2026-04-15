"""
app.py — rekordbox-tools web server

Start with:
    python app.py

Then open http://localhost:5000 in your browser.
"""

import json
import os
import queue
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
            "music_root":  request.form.get("music_root", "").strip(),
            "flac_root":   request.form.get("flac_root", "").strip(),
            "mp3_root":    request.form.get("mp3_root", "").strip(),
            "delete_dir":  request.form.get("delete_dir", "").strip(),
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


@app.route("/api/run/<script_name>")
def api_run(script_name):
    """Stream script output as server-sent events."""
    allowed = {
        "relocate":       "rekordbox_relocate.py",
        "cleanup":        "rekordbox_cleanup.py",
        "remove_missing": "rekordbox_remove_missing.py",
        "strip_comments": "strip_comment_urls.py",
    }
    if script_name not in allowed:
        return jsonify({"error": "unknown script"}), 400

    script_path = SCRIPTS_DIR / allowed[script_name]
    cfg = load_config()

    # Build args from query params
    args = []
    dry_run = request.args.get("dry_run") == "1"

    if script_name == "relocate":
        target = request.args.get("target_root") or cfg.get("flac_root", "")
        source = request.args.get("source_root") or cfg.get("mp3_root", "")
        if not target:
            return jsonify({"error": "target_root required"}), 400
        args += ["--target-root", target]
        if source:
            args += ["--source-root", source]
        if request.args.get("missing_only") == "1":
            args.append("--missing-only")
        if request.args.get("all_tracks") == "1":
            args.append("--all-tracks")
        pref = request.args.get("prefer_ext", "flac")
        args += ["--prefer-ext", pref]

    elif script_name == "cleanup":
        scan = request.args.get("scan_root") or cfg.get("music_root", "")
        delete_dir = request.args.get("delete_dir") or cfg.get("delete_dir", "")
        exclude = request.args.get("exclude", "")
        if not scan:
            return jsonify({"error": "scan_root required"}), 400
        args += ["--scan-root", scan]
        if delete_dir:
            args += ["--delete-dir", delete_dir]
        if exclude:
            args += ["--exclude", exclude]

    elif script_name == "strip_comments":
        dirs = [
            request.args.get("dir1") or cfg.get("music_root", ""),
            request.args.get("dir2", ""),
        ]
        dirs = [d for d in dirs if d]
        if not dirs:
            return jsonify({"error": "at least one directory required"}), 400
        args += dirs
        if not dry_run:
            args.append("--write")
        # strip_comments handles dry-run via absence of --write, so skip below
        dry_run = False

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
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()
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
