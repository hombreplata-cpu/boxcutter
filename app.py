"""
app.py — BoxCutter web server

Start with:
    python app.py

Then open http://localhost:5000 in your browser.
"""

import contextlib
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.request
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.exceptions import HTTPException

from crash_logger import write_crash_log
from version import __version__ as _app_version

app = Flask(__name__)

# Suppress console windows spawned by subprocesses when running as a
# windowed exe (console=False in app.spec). No-op on macOS/Linux.
_POPEN_FLAGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)

CONFIG_FILE = Path(
    os.environ.get("BOXCUTTER_CONFIG_PATH", str(Path.home() / ".boxcutter_config.json"))
)
SCRIPTS_DIR = Path(__file__).parent / "scripts"


def _default_delete_dir() -> str:
    onedrive = Path.home() / "OneDrive" / "Desktop"
    if onedrive.is_dir():
        return str(onedrive / "DELETE")
    return str(Path.home() / "Desktop" / "DELETE")


DEFAULT_CONFIG = {
    "music_root": "",
    "flac_root": "",
    "mp3_root": "",
    "delete_dir": _default_delete_dir(),
    "watch_dir": "",
    "db_path": "",
    "target_playlist_id": "",  # Add New Tracks: last-used playlist
    "cleanup_exclude": "",  # Library Cleanup: last-used exclude folder
    "donation_shown": False,
    "listen_pin": "",  # Remote listener PIN (4 digits; empty = listener not configured)
}

# Keys writable via /api/config or POST /setup. Anything else is silently
# dropped — prevents an attacker from setting _secret_key, db_path on a
# malicious DB, etc. Internal keys (e.g. _secret_key) are written through
# save_config() directly, never via the public endpoints.
ALLOWED_CONFIG_KEYS = frozenset(DEFAULT_CONFIG.keys())

# Listen PIN format: 4–8 digits, or empty to disable the feature.
_LISTEN_PIN_RE = re.compile(r"^\d{4,8}$")


def _validate_listen_pin(raw):
    """Return ('', None) for empty, (pin, None) for valid, ('', error) otherwise."""
    pin = (raw or "").strip()
    if not pin:
        return "", None
    if _LISTEN_PIN_RE.match(pin):
        return pin, None
    return "", "Listener PIN must be 4–8 digits (or empty to disable)."


HISTORY_FILE = Path.home() / ".boxcutter_history.json"

TOOL_LABELS = {
    "relocate": "Repath Tracks",
    "cleanup": "Library Cleanup",
    "strip_comments": "Strip URL Comments",
    "fix_metadata": "Fix Metadata",
    "add_new": "Add New Tracks",
}

GITHUB_RELEASES_URL = "https://api.github.com/repos/hombreplata-cpu/boxcutter/releases/latest"
GITHUB_DOWNLOAD_PREFIX = "https://github.com/hombreplata-cpu/boxcutter/releases/download/"

_update_state: dict = {"path": None}  # stores downloaded installer path until applied


# File-write lock for config and history JSON files. Prevents corruption when
# concurrent requests (or the lazy secret-key writer) race against the user
# pressing Save in the UI. All file writes go through atomic_write_json().
_FILE_WRITE_LOCK = threading.Lock()


def _atomic_write_json(target: Path, data) -> None:
    """Write JSON to *target* atomically: tmp file then os.replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, target)


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(data)
            # Migrate stored delete_dir from the old non-OneDrive default to the
            # correct OneDrive Desktop path on machines where OneDrive Desktop exists.
            # Persist the migration immediately (B-05) so the corrected value
            # survives subsequent partial saves.
            old_default = str(Path.home() / "Desktop" / "DELETE")
            correct = _default_delete_dir()
            if cfg.get("delete_dir") == old_default and correct != old_default:
                cfg["delete_dir"] = correct
                with contextlib.suppress(OSError), _FILE_WRITE_LOCK:
                    _atomic_write_json(CONFIG_FILE, cfg)
            return cfg
        except Exception:  # noqa: S110 — config load failure is expected; fall back to defaults
            pass
    return DEFAULT_CONFIG.copy()


def save_config(data):
    with _FILE_WRITE_LOCK:
        cfg = DEFAULT_CONFIG.copy()
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    cfg.update(json.load(f))
            except Exception:  # noqa: S110 — corrupt; start from defaults
                pass
        cfg.update(data)
        _atomic_write_json(CONFIG_FILE, cfg)
        return cfg


def config_is_complete(cfg):
    return bool(cfg.get("music_root") and cfg.get("flac_root") and cfg.get("db_path"))


# ── Session secret key ────────────────────────────────────────────────────────
# Lazily initialised on first request so test fixtures can patch CONFIG_FILE
# before the key is generated. Persisted in config so sessions survive
# server restarts; falls back to an ephemeral key if the file is read-only.


_secret_key_initialised = False


def _init_secret_key():
    global _secret_key_initialised
    if _secret_key_initialised:
        return
    if os.environ.get("BOXCUTTER_TESTING"):
        # Tests get an ephemeral key — never write to whatever CONFIG_FILE
        # points at, so test runs cannot leak a key into a real config file.
        app.secret_key = secrets.token_bytes(32)
        _secret_key_initialised = True
        return
    cfg = load_config()
    key_hex = cfg.get("_secret_key", "")
    if not key_hex:
        key_hex = secrets.token_hex(32)
        try:
            save_config({"_secret_key": key_hex})
        except OSError as exc:
            # Read-only home / locked-down environment: fall back to ephemeral.
            print(
                f"  WARNING: could not persist session key ({exc}); "
                "sessions will not survive restart"
            )
    app.secret_key = bytes.fromhex(key_hex)
    _secret_key_initialised = True


@app.before_request
def _ensure_secret_key():
    if not _secret_key_initialised:
        _init_secret_key()


# Bootstrap key for test clients that don't go through the request hook.
app.secret_key = secrets.token_bytes(32)


# ── Listen auth ───────────────────────────────────────────────────────────────


def _listen_authed():
    return session.get("listen_ok") is True


def clean_path(raw):
    """Strip surrounding whitespace and quotes that Windows 'Copy as path' adds."""
    if not raw:
        return raw
    return raw.strip().strip('"').strip("'").strip()


def get_rekordbox_backup_dir(db_path=""):
    """Return the directory that contains master.db and its backups.

    If db_path is configured, backups live alongside that file.
    Otherwise fall back to the default Pioneer/rekordbox folder for the current OS.
    """
    if db_path:
        return Path(db_path).parent
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "Pioneer" / "rekordbox"
    return Path.home() / "Library" / "Application Support" / "Pioneer" / "rekordbox"


def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except Exception:  # noqa: S110 — corrupt history file is non-fatal; fall back to empty list
            pass
    return []


def save_history_entry(entry):
    with _FILE_WRITE_LOCK:
        history = load_history()
        history.insert(0, entry)  # newest first
        with contextlib.suppress(Exception):
            _atomic_write_json(HISTORY_FILE, history)


def create_db_backup(db, tool_name: str) -> Path:
    """Create a timestamped backup in boxcutter-backups/ next to master.db."""
    db_path = Path(db.engine.url.database)
    backup_dir = db_path.parent / "boxcutter-backups"
    backup_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"master_backup_{tool_name}_{ts}.db"
    shutil.copy2(db_path, dest)
    return dest


def _open_db(cfg=None):
    """Open the Rekordbox database. Lazy-imports pyrekordbox to avoid breaking startup."""
    from pyrekordbox import Rekordbox6Database as MasterDatabase  # noqa: PLC0415

    if cfg is None:
        cfg = load_config()
    db_path = clean_path(cfg.get("db_path", ""))
    if not db_path:
        raise RuntimeError("Rekordbox database path is not configured. Go to Setup & Paths.")
    return MasterDatabase(path=db_path)


def _next_song_mytag_id(db) -> str:
    """Generate the next available ID for a new DjmdSongMyTag row."""
    try:
        from sqlalchemy import text  # noqa: PLC0415

        with db.engine.connect() as conn:
            result = conn.execute(
                text("SELECT MAX(CAST(ID AS INTEGER)) FROM djmdSongMyTag")
            ).scalar()
        return str((result or 0) + 1)
    except Exception:
        return str(uuid.uuid4())


def rekordbox_is_running():
    """Return True if the Rekordbox process is currently running."""
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq rekordbox.exe", "/NH"],
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                **_POPEN_FLAGS,
            )
            return "rekordbox.exe" in out.lower()
        else:
            result = subprocess.run(
                ["pgrep", "-xi", "rekordbox"],
                capture_output=True,
                **_POPEN_FLAGS,
            )
            return result.returncode == 0
    except Exception:
        return False


# ── Template globals ─────────────────────────────────────────────────────────


@app.context_processor
def inject_globals():
    cfg = load_config()
    return {
        "is_frozen": getattr(sys, "frozen", False),
        "show_donation": not cfg.get("donation_shown", False),
        "app_version": _app_version,
    }


# ── Error handling ───────────────────────────────────────────────────────────


@app.errorhandler(Exception)
def handle_exception(exc):
    # Let Flask render its standard 4xx/5xx for explicit abort(N) calls.
    # Otherwise the global handler turns every abort() into a 500 + crash log,
    # which silently breaks any future authorization gate (B-14).
    if isinstance(exc, HTTPException):
        return exc
    body = traceback.format_exc()
    ctx = {"Request": f"{request.method} {request.path}"}
    log_path = write_crash_log("route", body, context=ctx)
    if request.path.startswith("/api/"):
        return jsonify({"error": str(exc), "log_path": str(log_path) if log_path else None}), 500
    return render_template("error.html", log_path=log_path), 500


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
    pin_error = None
    if request.method == "POST":
        pin, pin_error = _validate_listen_pin(request.form.get("listen_pin", ""))
        if pin_error:
            # Re-render with current form values + error; do not persist anything.
            cfg = {
                **cfg,
                "music_root": clean_path(request.form.get("music_root", "")),
                "flac_root": clean_path(request.form.get("flac_root", "")),
                "mp3_root": clean_path(request.form.get("mp3_root", "")),
                "delete_dir": clean_path(request.form.get("delete_dir", "")),
                "watch_dir": clean_path(request.form.get("watch_dir", "")),
                "db_path": clean_path(request.form.get("db_path", "")),
                "listen_pin": request.form.get("listen_pin", ""),
            }
            return render_template("setup.html", cfg=cfg, saved=False, pin_error=pin_error), 400
        cfg = save_config(
            {
                "music_root": clean_path(request.form.get("music_root", "")),
                "flac_root": clean_path(request.form.get("flac_root", "")),
                "mp3_root": clean_path(request.form.get("mp3_root", "")),
                "delete_dir": clean_path(request.form.get("delete_dir", "")),
                "watch_dir": clean_path(request.form.get("watch_dir", "")),
                "db_path": clean_path(request.form.get("db_path", "")),
                "listen_pin": pin,
            }
        )
        saved = True
        if config_is_complete(cfg):
            return redirect(url_for("index"))
    return render_template("setup.html", cfg=cfg, saved=saved, pin_error=pin_error)


@app.route("/tool/<n>")
def tool(n):
    cfg = load_config()
    tools = {
        "relocate": ("Repath Tracks", "relocate.html"),
        "cleanup": ("Library Cleanup", "cleanup.html"),
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
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Body must be a JSON object"}), 400
    # Allowlist: only known config keys may be written via this endpoint.
    # Internal keys (leading underscore, e.g. _secret_key) and unknown keys
    # are silently dropped — prevents an attacker from setting the session
    # key, swapping db_path to a malicious DB, etc. (S-01)
    filtered = {k: v for k, v in data.items() if k in ALLOWED_CONFIG_KEYS}
    if "listen_pin" in filtered:
        pin, err = _validate_listen_pin(filtered["listen_pin"])
        if err:
            return jsonify({"error": err}), 400
        filtered["listen_pin"] = pin
    cfg = save_config(filtered)
    return jsonify({"ok": True, "config": cfg})


@app.route("/api/rekordbox_status")
def api_rekordbox_status():
    """Check whether rekordbox.exe is currently running."""
    return jsonify({"running": rekordbox_is_running()})


# ── Auto-updater routes ───────────────────────────────────────────────────────


def _version_gt(a: str, b: str) -> bool:
    """Return True if version string a is strictly greater than b."""

    def parse(v):
        try:
            return tuple(int(x) for x in v.strip().split("."))
        except Exception:
            return (0,)

    return parse(a) > parse(b)


@app.route("/api/update_check")
def api_update_check():
    """Check GitHub for a newer release. No-ops in dev mode (not frozen)."""
    if not getattr(sys, "frozen", False):
        return jsonify({"available": False})
    try:
        req = urllib.request.Request(  # noqa: S310 — URL is a hard-coded constant
            GITHUB_RELEASES_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"BoxCutter/{_app_version}",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310  # nosec B310 — hard-coded GitHub API URL
            data = json.loads(resp.read().decode())
        tag = data.get("tag_name", "").lstrip("v")
        is_mac = platform.system() == "Darwin"
        download_url = ""
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if is_mac:
                if name.startswith("boxcutter-mac") and name.endswith(".dmg"):
                    download_url = asset.get("browser_download_url", "")
                    break
            else:
                if name.startswith("BoxCutter-Setup-") and name.endswith(".exe"):
                    download_url = asset.get("browser_download_url", "")
                    break
        if not download_url or not _version_gt(tag, _app_version):
            return jsonify({"available": False})
        return jsonify(
            {
                "available": True,
                "version": tag,
                "download_url": download_url,
                "platform": "mac" if is_mac else "win",
            }
        )
    except Exception:  # noqa: BLE001 — any network/parse failure → no update banner
        return jsonify({"available": False})


@app.route("/api/download_update")
def api_download_update():
    """Stream download of the installer to a temp file, emitting progress as SSE."""
    url = request.args.get("url", "")
    if not url.startswith(GITHUB_DOWNLOAD_PREFIX):
        return jsonify({"error": "Invalid download URL"}), 400

    def stream():
        tmp_path = None
        try:
            req = urllib.request.Request(  # noqa: S310 — URL validated against hard-coded prefix above
                url, headers={"User-Agent": f"BoxCutter/{_app_version}"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  # nosec B310 — URL validated against hard-coded prefix
                total = int(resp.headers.get("Content-Length", 0))
                is_mac = platform.system() == "Darwin"
                suffix = ".dmg" if is_mac else ".exe"
                with tempfile.NamedTemporaryFile(
                    suffix=suffix,
                    prefix="BoxCutter-",
                    delete=False,
                    dir=tempfile.gettempdir(),
                ) as tmp:
                    tmp_path = tmp.name
                    downloaded = 0
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        tmp.write(chunk)
                        downloaded += len(chunk)
                        payload = {"downloaded": downloaded}
                        if total:
                            payload["total"] = total
                        yield f"data: {json.dumps(payload)}\n\n"
                if total and downloaded != total:
                    Path(tmp_path).unlink(missing_ok=True)
                    tmp_path = None
                    yield f"data: {json.dumps({'error': f'Download incomplete: got {downloaded} of {total} bytes'})}\n\n"
                    return
                _update_state["path"] = tmp_path
                yield "data: %%DONE%%\n\n"
        except Exception as exc:  # noqa: BLE001
            if tmp_path:
                with contextlib.suppress(OSError):
                    Path(tmp_path).unlink(missing_ok=True)
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/apply_update", methods=["POST"])
def api_apply_update():
    """Launch the downloaded installer, then exit this process."""
    path = _update_state.get("path")
    if not path or not Path(path).exists():
        return jsonify({"error": "No update ready"}), 400
    _update_state["path"] = None  # clear regardless of outcome
    if platform.system() == "Darwin":
        # Open the DMG in Finder — user drags BoxCutter.app to Applications
        try:
            result = subprocess.run(["open", path], capture_output=True, timeout=5)  # noqa: S603
            if result.returncode != 0:
                err = result.stderr.decode(errors="replace").strip()
                return jsonify({"error": f"Failed to open DMG: {err}"}), 500
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500
        finally:
            with contextlib.suppress(OSError):
                Path(path).unlink(missing_ok=True)
        return jsonify({"ok": True, "manual": True})
    # Windows: Inno Setup loads itself into memory before running, so temp file
    # can be deleted immediately after launch.
    subprocess.Popen([path, "/SILENT"], **_POPEN_FLAGS)  # noqa: S603 — list form, no shell; path is server-controlled
    with contextlib.suppress(OSError):
        Path(path).unlink(missing_ok=True)
    threading.Timer(1.0, lambda: os._exit(0)).start()  # noqa: SLF001 — intentional hard exit so installer can replace files
    return jsonify({"ok": True, "manual": False})


# ── My Tag Manager routes ─────────────────────────────────────────────────────


@app.route("/api/mytags/backup", methods=["POST"])
def api_mytags_backup():
    """Create a DB backup before a My Tag editing session."""
    if rekordbox_is_running():
        return jsonify({"error": "Close Rekordbox before editing tags"}), 409
    try:
        db = _open_db()
        backup_path = create_db_backup(db, "mytag")
        return jsonify({"ok": True, "backup_path": str(backup_path)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/mytags")
def api_mytags():
    """Return all My Tags as a flat list (groups and children)."""
    try:
        db = _open_db()
        try:
            tags = db.get_my_tag().filter_by(rb_local_deleted=0).all()
        except Exception:
            tags = db.get_my_tag().all()
        return jsonify(
            [
                {
                    "id": t.ID,
                    "name": t.Name,
                    "parent_id": t.ParentID,
                    "seq": t.Seq,
                    "attribute": t.Attribute,
                }
                for t in tags
            ]
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/tracks/search")
def api_tracks_search():
    """Search djmdContent by title or artist (case-insensitive, up to limit results)."""
    q = request.args.get("q", "").strip()
    limit = min(50, max(1, int(request.args.get("limit", 20))))
    if not q:
        return jsonify([])
    try:
        from pyrekordbox.db6.tables import DjmdArtist, DjmdContent  # noqa: PLC0415
        from sqlalchemy import or_  # noqa: PLC0415

        db = _open_db()
        tracks = (
            db.session.query(DjmdContent)
            .outerjoin(DjmdArtist, DjmdContent.ArtistID == DjmdArtist.ID)
            .filter(DjmdContent.rb_local_deleted == 0)
            .filter(
                or_(
                    DjmdContent.Title.ilike(f"%{q}%"),
                    DjmdArtist.Name.ilike(f"%{q}%"),
                )
            )
            .limit(limit)
            .all()
        )
        return jsonify(
            [
                {
                    "id": t.ID,
                    "title": t.Title or "",
                    "artist": t.Artist.Name if t.Artist else "",
                }
                for t in tracks
            ]
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/tracks/<content_id>/mytags")
def api_track_mytags_get(content_id):
    """Get all My Tags currently assigned to a track."""
    try:
        db = _open_db()
        assignments = db.get_my_tag_songs(ContentID=content_id).all()
        return jsonify(
            [
                {
                    "assignment_id": a.ID,
                    "tag_id": a.MyTagID,
                    "tag_name": a.MyTagName or "",
                }
                for a in assignments
            ]
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/tracks/<content_id>/mytags", methods=["POST"])
def api_track_mytags_add(content_id):
    """Assign a My Tag to a track."""
    if rekordbox_is_running():
        return jsonify({"error": "Close Rekordbox before editing tags"}), 409
    data = request.get_json() or {}
    mytag_id = str(data.get("mytag_id", "")).strip()
    if not mytag_id:
        return jsonify({"error": "mytag_id required"}), 400
    try:
        from pyrekordbox.db6.tables import DjmdSongMyTag  # noqa: PLC0415

        db = _open_db()
        existing = db.get_my_tag_songs(ContentID=content_id).filter_by(MyTagID=mytag_id).first()
        if existing:
            return jsonify({"error": "Tag already assigned to this track"}), 409
        current = db.get_my_tag_songs(MyTagID=mytag_id).all()
        track_no = max((a.TrackNo or 0 for a in current), default=0) + 1
        new_id = _next_song_mytag_id(db)
        row = DjmdSongMyTag(
            ID=new_id,
            MyTagID=mytag_id,
            ContentID=content_id,
            TrackNo=track_no,
            UUID=str(uuid.uuid4()),
        )
        db.session.add(row)
        db.commit()
        return jsonify({"ok": True, "assignment_id": new_id})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/tracks/<content_id>/mytags/<assignment_id>", methods=["DELETE"])
def api_track_mytags_remove(content_id, assignment_id):
    """Remove a My Tag assignment from a track."""
    if rekordbox_is_running():
        return jsonify({"error": "Close Rekordbox before editing tags"}), 409
    try:
        db = _open_db()
        row = db.get_my_tag_songs(ID=assignment_id)
        if not row or row.ContentID != content_id:
            return jsonify({"error": "Assignment not found"}), 404
        db.session.delete(row)
        db.commit()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Stream session — lazy one-per-session backup ───────────────────────────────

_stream_session: dict = {"backup_path": None, "last_write": None}
_STREAM_SESSION_TTL = 2 * 3600  # seconds


def _ensure_stream_backup(db) -> Path:
    now = datetime.now()
    last = _stream_session["last_write"]
    if last is None or (now - last).total_seconds() > _STREAM_SESSION_TTL:
        path = create_db_backup(db, "stream")
        _stream_session["backup_path"] = str(path)
    _stream_session["last_write"] = now
    return Path(_stream_session["backup_path"])


def _next_song_playlist_id(db) -> str:
    try:
        from sqlalchemy import text  # noqa: PLC0415

        with db.engine.connect() as conn:
            result = conn.execute(
                text("SELECT MAX(CAST(ID AS INTEGER)) FROM djmdSongPlaylist")
            ).scalar()
        return str((result or 0) + 1)
    except Exception:
        return str(uuid.uuid4())


@app.route("/api/tracks/<content_id>/rating", methods=["POST"])
def api_track_rating_set(content_id):
    if not _listen_authed():
        return jsonify({"error": "Unauthorized"}), 401
    if rekordbox_is_running():
        return jsonify({"error": "Close Rekordbox before editing"}), 409
    data = request.get_json() or {}
    raw = data.get("rating")
    try:
        stars = int(raw)
    except (TypeError, ValueError):
        return jsonify({"error": "rating must be 0-5"}), 400
    if stars not in range(6):
        return jsonify({"error": "rating must be 0-5"}), 400
    try:
        from pyrekordbox.db6.tables import DjmdContent  # noqa: PLC0415

        db = _open_db()
        _ensure_stream_backup(db)
        track = db.session.query(DjmdContent).filter_by(ID=content_id, rb_local_deleted=0).first()
        if not track:
            return jsonify({"error": "Track not found"}), 404
        track.Rating = stars
        db.commit()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/tracks/<content_id>/playlists")
def api_track_playlists_get(content_id):
    if not _listen_authed():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        from pyrekordbox.db6.tables import DjmdPlaylist, DjmdSongPlaylist  # noqa: PLC0415

        db = _open_db()
        entries = (
            db.session.query(DjmdSongPlaylist)
            .filter_by(ContentID=content_id, rb_local_deleted=0)
            .all()
        )
        result = []
        for e in entries:
            pl = (
                db.session.query(DjmdPlaylist)
                .filter_by(ID=e.PlaylistID, rb_local_deleted=0)
                .first()
            )
            if pl:
                result.append({"playlist_id": str(e.PlaylistID), "name": pl.Name or ""})
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/tracks/<content_id>/playlists/<playlist_id>", methods=["POST"])
def api_track_playlist_add(content_id, playlist_id):
    if not _listen_authed():
        return jsonify({"error": "Unauthorized"}), 401
    if rekordbox_is_running():
        return jsonify({"error": "Close Rekordbox before editing"}), 409
    try:
        from pyrekordbox.db6.tables import DjmdPlaylist, DjmdSongPlaylist  # noqa: PLC0415

        db = _open_db()
        pl = db.session.query(DjmdPlaylist).filter_by(ID=playlist_id, rb_local_deleted=0).first()
        if not pl:
            return jsonify({"error": "Playlist not found"}), 404
        existing = (
            db.session.query(DjmdSongPlaylist)
            .filter_by(ContentID=content_id, PlaylistID=playlist_id, rb_local_deleted=0)
            .first()
        )
        if existing:
            return jsonify({"ok": True, "already": True})
        current = (
            db.session.query(DjmdSongPlaylist)
            .filter_by(PlaylistID=playlist_id, rb_local_deleted=0)
            .all()
        )
        track_no = max((r.TrackNo or 0 for r in current), default=0) + 1
        new_id = _next_song_playlist_id(db)
        _ensure_stream_backup(db)
        row = DjmdSongPlaylist(
            ID=new_id,
            PlaylistID=playlist_id,
            ContentID=content_id,
            TrackNo=track_no,
            UUID=str(uuid.uuid4()),
        )
        db.session.add(row)
        db.commit()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/tracks/<content_id>/playlists/<playlist_id>", methods=["DELETE"])
def api_track_playlist_remove(content_id, playlist_id):
    if not _listen_authed():
        return jsonify({"error": "Unauthorized"}), 401
    if rekordbox_is_running():
        return jsonify({"error": "Close Rekordbox before editing"}), 409
    try:
        from pyrekordbox.db6.tables import DjmdSongPlaylist  # noqa: PLC0415

        db = _open_db()
        rows = (
            db.session.query(DjmdSongPlaylist)
            .filter_by(ContentID=content_id, PlaylistID=playlist_id, rb_local_deleted=0)
            .all()
        )
        if not rows:
            return jsonify({"error": "Not in that playlist"}), 404
        _ensure_stream_backup(db)
        for row in rows:
            db.session.delete(row)
        db.commit()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/restore")
def restore():
    cfg = load_config()
    db_path = clean_path(cfg.get("db_path", ""))
    backup_dir = str(Path(db_path).parent / "boxcutter-backups") if db_path else None
    return render_template("restore.html", backup_dir=backup_dir)


@app.route("/api/dismiss_donation", methods=["POST"])
def api_dismiss_donation():
    save_config({"donation_shown": True})
    return jsonify({"ok": True})


@app.route("/api/run/<script_name>")
def api_run(script_name):
    """Stream script output as server-sent events."""
    allowed = {
        "relocate": "rekordbox_relocate.py",
        "cleanup": "rekordbox_cleanup.py",
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
        target_ext = clean_path(request.args.get("target_ext", "flac")) or "flac"
        source_ext = clean_path(request.args.get("source_ext", ""))
        prefer_ext = clean_path(request.args.get("prefer_ext", ""))
        args += ["--target-ext", target_ext]
        if source_ext:
            args += ["--source-ext", source_ext]
        if prefer_ext:
            args += ["--prefer-ext", prefer_ext]

    elif script_name == "cleanup":
        scan = clean_path(request.args.get("scan_root") or cfg.get("music_root", ""))
        delete_dir = clean_path(request.args.get("delete_dir") or cfg.get("delete_dir", ""))
        exclude = clean_path(request.args.get("exclude") or cfg.get("cleanup_exclude", ""))
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
        # NOTE: do NOT clobber dry_run here — the history entry must reflect
        # the actual mode the user requested (B-04).

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

    db_path = clean_path(cfg.get("db_path", ""))
    if script_name != "strip_comments" and not db_path:
        return jsonify({"error": "Database path not configured — go to Setup & Paths."}), 400
    if db_path and script_name != "strip_comments":
        args += ["--db-path", db_path]

    # strip_comments uses --write to opt-IN to live mode; --dry-run is the default
    # and the flag isn't accepted by the script. Other scripts use --dry-run.
    if dry_run and script_name != "strip_comments":
        args.append("--dry-run")

    cmd = [sys.executable, str(script_path)] + args

    def generate():
        backup_path = None
        report_data = None

        mode_str = "dry run" if dry_run else "live"
        tool_label = TOOL_LABELS.get(script_name, script_name)
        yield f"data: === {tool_label} ({mode_str}) ===\n\n"
        yield f"data: $ {' '.join(cmd)}\n\n"
        yield "data: \n\n"
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            **_POPEN_FLAGS,
        )
        report_lines = []
        in_report = False

        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()

            # Capture backup path printed by DB scripts
            if line.startswith("[backup] ") and not line.startswith("[backup] WARNING"):
                backup_path = line[len("[backup] ") :]

            # Progress sentinel — intercept and re-emit as named SSE event
            if line.startswith("%%PROGRESS%%"):
                payload = line[len("%%PROGRESS%%") :].strip()
                yield f"event: progress\ndata: {payload}\n\n"
                continue

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

        if proc.returncode != 0:
            script_file = allowed[script_name]
            ctx = {
                "Script:   ": script_file,
                "Exit code:": str(proc.returncode),
                "Command:  ": " ".join(str(a) for a in cmd),
            }
            captured = "".join(f"  {part}\n" for part in cmd) + "\n(see streamed output above)"
            log_path = write_crash_log("script", captured, context=ctx)
            if log_path:
                yield f"event: crash\ndata: {json.dumps({'log_path': str(log_path)})}\n\n"

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
    same Python environment used by all other BoxCutter scripts.
    """
    script_path = SCRIPTS_DIR / "get_playlists.py"
    cfg = load_config()
    db_path = clean_path(cfg.get("db_path", ""))
    if not db_path:
        return jsonify({"error": "Database path not configured — go to Setup & Paths."}), 400
    cmd = [sys.executable, str(script_path)]
    if db_path:
        cmd += ["--db-path", db_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            **_POPEN_FLAGS,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or "Unknown error reading playlists"
            return jsonify({"error": msg}), 500
        return result.stdout, 200, {"Content-Type": "application/json"}
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out reading Rekordbox database"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/stats")
def api_stats():
    """Return library stats (track count, file type breakdown, total size) as JSON.

    Runs get_stats.py as a subprocess so pyrekordbox is imported in the
    same Python environment used by all other BoxCutter scripts.
    """
    script_path = SCRIPTS_DIR / "get_stats.py"
    cfg = load_config()
    db_path = clean_path(cfg.get("db_path", ""))
    if not db_path:
        return jsonify({"error": "Database path not configured — go to Setup & Paths."}), 400
    cmd = [sys.executable, str(script_path)]
    if db_path:
        cmd += ["--db-path", db_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            **_POPEN_FLAGS,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or "Unknown error reading database stats"
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
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(1, min(100, int(request.args.get("per_page", 20))))
    except (TypeError, ValueError):
        return jsonify({"error": "page and per_page must be integers"}), 400
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
    backup_dir = get_rekordbox_backup_dir(db_path) / "boxcutter-backups"
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
    backup_dir = get_rekordbox_backup_dir(db_path) / "boxcutter-backups"
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


@app.route("/shutdown", methods=["POST"])
def shutdown():
    """Terminate the server process — only exposed when running as a frozen binary."""
    os.kill(os.getpid(), signal.SIGTERM)
    return "", 204


# ── Remote Listener ───────────────────────────────────────────────────────────


def _tailscale_ip() -> str:
    """Return the Tailscale IPv4 address, or empty string if not available."""
    import platform

    candidates = ["tailscale"]
    if platform.system() == "Windows":
        candidates.append(r"C:\Program Files\Tailscale\tailscale.exe")
    elif platform.system() == "Darwin":
        candidates.append("/Applications/Tailscale.app/Contents/MacOS/Tailscale")

    for cmd in candidates:
        try:
            result = subprocess.run(
                [cmd, "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=3,
                **_POPEN_FLAGS,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:  # noqa: BLE001, S112
            continue
    return ""


@app.route("/listen/setup")
def listen_setup():
    cfg = load_config()
    ts_ip = _tailscale_ip()
    # Detect the port the server is actually listening on
    server_port = request.host.split(":")[-1] if ":" in request.host else "5000"
    return render_template(
        "listen_setup.html",
        pin_set=bool(cfg.get("listen_pin", "")),
        tailscale_ip=ts_ip,
        port=server_port,
        rb_running=rekordbox_is_running(),
    )


_AUDIO_MIMES = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
    ".m4a": "audio/mp4",
    ".alac": "audio/mp4",
    ".ogg": "audio/ogg",
    ".wma": "audio/x-ms-wma",
    ".mp4": "audio/mp4",
}


@app.route("/listen")
def listen():
    if not _listen_authed():
        return redirect(url_for("listen_login"))
    return render_template("listen.html")


@app.route("/listen/login", methods=["GET", "POST"])
def listen_login():
    cfg = load_config()
    pin = cfg.get("listen_pin", "")
    if not pin:
        return render_template("listen_login.html", no_pin=True)
    if request.method == "POST":
        if request.form.get("pin", "").strip() == pin:
            session["listen_ok"] = True
            return redirect(url_for("listen"))
        return render_template("listen_login.html", error=True)
    return render_template("listen_login.html")


@app.route("/listen/logout")
def listen_logout():
    session.pop("listen_ok", None)
    return redirect(url_for("listen_login"))


@app.route("/api/listen/tree")
def api_listen_tree():
    if not _listen_authed():
        return jsonify({"error": "Unauthorized"}), 401
    script_path = SCRIPTS_DIR / "get_listen_tree.py"
    cfg = load_config()
    cmd = [sys.executable, str(script_path)]
    db_path = clean_path(cfg.get("db_path", ""))
    if db_path:
        cmd += ["--db-path", db_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            **_POPEN_FLAGS,
        )
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip() or "Failed to read playlists"}), 500
        # Inject rekordbox_running flag so mobile can warn the user
        data = json.loads(result.stdout)
        data["rekordbox_running"] = rekordbox_is_running()
        return jsonify(data)
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out reading database"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/listen/all-tracks")
def api_listen_all_tracks():
    if not _listen_authed():
        return jsonify({"error": "Unauthorized"}), 401
    script_path = SCRIPTS_DIR / "get_playlist_tracks.py"
    cfg = load_config()
    cmd = [sys.executable, str(script_path), "--playlist-id", "all"]
    db_path = clean_path(cfg.get("db_path", ""))
    if db_path:
        cmd += ["--db-path", db_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            **_POPEN_FLAGS,
        )
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip() or "Failed to read tracks"}), 500
        return result.stdout, 200, {"Content-Type": "application/json"}
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out reading tracks"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/listen/playlist/<int:pid>/tracks")
def api_listen_tracks(pid):
    if not _listen_authed():
        return jsonify({"error": "Unauthorized"}), 401
    script_path = SCRIPTS_DIR / "get_playlist_tracks.py"
    cfg = load_config()
    cmd = [sys.executable, str(script_path), "--playlist-id", str(pid)]
    db_path = clean_path(cfg.get("db_path", ""))
    if db_path:
        cmd += ["--db-path", db_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            **_POPEN_FLAGS,
        )
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip() or "Failed to read tracks"}), 500
        return result.stdout, 200, {"Content-Type": "application/json"}
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out reading tracks"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/stream/<int:track_id>")
def api_stream(track_id):
    if not _listen_authed():
        return jsonify({"error": "Unauthorized"}), 401
    script_path = SCRIPTS_DIR / "get_track_path.py"
    cfg = load_config()
    cmd = [sys.executable, str(script_path), "--track-id", str(track_id)]
    db_path = clean_path(cfg.get("db_path", ""))
    if db_path:
        cmd += ["--db-path", db_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            **_POPEN_FLAGS,
        )
        if result.returncode != 0:
            return jsonify({"error": "Track not found"}), 404
        data = json.loads(result.stdout)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    file_path = Path(data["path"])
    if not file_path.exists():
        return jsonify({"error": "File not found on disk"}), 404

    mime = _AUDIO_MIMES.get(data["ext"], "application/octet-stream")
    return send_file(file_path, mimetype=mime, conditional=True)


@app.route("/api/tracks/<content_id>/cues")
def api_track_cues(content_id):
    """Return Rekordbox cue points for a track (read-only)."""
    if not _listen_authed():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        from pyrekordbox.db6.tables import DjmdCue  # noqa: PLC0415

        db = _open_db()
        try:
            cues = (
                db.session.query(DjmdCue).filter_by(ContentID=content_id, rb_local_deleted=0).all()
            )
        except Exception:
            cues = db.session.query(DjmdCue).filter_by(ContentID=content_id).all()
        result = [
            {
                "id": str(c.ID),
                "time_ms": int(c.InMsec or 0),
                "kind": int(c.Kind or 0),
                "comment": c.Comment or "",
            }
            for c in cues
        ]
        result.sort(key=lambda x: x["time_ms"])
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/tracks/<content_id>/cues", methods=["POST"])
def api_track_cue_add(content_id):
    """Add a memory cue point to a track and persist it to the Rekordbox DB."""
    if not _listen_authed():
        return jsonify({"error": "Unauthorized"}), 401
    if rekordbox_is_running():
        return jsonify({"error": "Close Rekordbox before editing"}), 409
    data = request.get_json() or {}
    try:
        time_ms = int(data.get("time_ms", -1))
    except (TypeError, ValueError):
        return jsonify({"error": "time_ms must be an integer"}), 400
    if time_ms < 0:
        return jsonify({"error": "time_ms must be >= 0"}), 400
    comment = str(data.get("comment", "")).strip()
    try:
        from pyrekordbox.db6.tables import DjmdCue  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        db = _open_db()
        _ensure_stream_backup(db)

        with db.engine.connect() as conn:
            result = conn.execute(text("SELECT MAX(CAST(ID AS INTEGER)) FROM DjmdCue")).scalar()
        new_id = str((result or 0) + 1)

        row = DjmdCue(
            ID=new_id,
            ContentID=content_id,
            InMsec=time_ms,
            InFrame=0,
            InMpegFrame=0,
            InMpegAbs=0,
            OutMsec=-1,
            OutFrame=-1,
            OutMpegFrame=-1,
            OutMpegAbs=-1,
            Kind=0,  # 0 = memory cue
            Color=0,
            ColorTableIndex=0,
            ActiveLoop=0,
            Comment=comment,
            BeatLoopSize=0,
            CueMicrosec=0,
            InPointSeekInfo="",
            OutPointSeekInfo="",
            ContentUUID="",
            UUID=str(uuid.uuid4()),
            rb_local_deleted=0,
        )
        db.session.add(row)
        db.commit()
        return jsonify({"ok": True, "id": new_id, "time_ms": time_ms})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _port_pid(port: int) -> int | None:
    """Return the PID listening on *port*, or None if the port is free."""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5,
                **_POPEN_FLAGS,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    pid = int(line.split()[-1])
                    return pid if pid != 0 else None
        else:
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
                capture_output=True,
                text=True,
                timeout=5,
                **_POPEN_FLAGS,
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip().splitlines()[0])
    except Exception:  # noqa: S110
        pass
    return None


def _is_our_app(pid: int) -> bool:
    """Return True if *pid*'s command line contains app.py (BoxCutter)."""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "process", "where", f"processid={pid}", "get", "commandline"],
                capture_output=True,
                text=True,
                timeout=5,
                **_POPEN_FLAGS,
            )
        else:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=5,
                **_POPEN_FLAGS,
            )
        return "app.py" in result.stdout
    except Exception:  # noqa: S110
        return False


def _find_free_port(start: int) -> int:
    """Return the first free TCP port at or above *start*."""
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found in range")


def resolve_server_port(preferred: int = 5000) -> int:
    """
    Return the port Flask should bind to:
    - Preferred port is free → use it.
    - Preferred port is our app → kill that instance, reuse it.
    - Preferred port is another app → find the next free port.
    """
    if env_port := os.environ.get("BOXCUTTER_PORT"):
        try:
            return int(env_port)
        except ValueError:
            print(f"  WARNING: BOXCUTTER_PORT={env_port!r} is not an integer — ignoring")
    pid = _port_pid(preferred)
    if pid is None:
        return preferred
    if _is_our_app(pid):
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=5,
                **_POPEN_FLAGS,
            )
        else:
            subprocess.run(
                ["kill", "-9", str(pid)], capture_output=True, timeout=5, **_POPEN_FLAGS
            )
        print(f"  Stopped previous instance (PID {pid})")
        return preferred
    print(f"  Port {preferred} in use by another app — finding a free port")
    return _find_free_port(preferred + 1)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  BoxCutter")
    print("  -------------------------------")
    _port = resolve_server_port()
    print(f"  Starting server at http://localhost:{_port}")
    print(f"  Remote listener: http://<tailscale-ip>:{_port}/listen")
    print("  Press Ctrl+C to stop\n")
    if not os.environ.get("BOXCUTTER_TESTING"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{_port}")).start()
    # Bind to 0.0.0.0 so the /listen endpoint is reachable over Tailscale
    app.run(debug=False, port=_port, host="0.0.0.0")  # noqa: S104  # nosec B104 — intentional; Tailscale is the security layer
