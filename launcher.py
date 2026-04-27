"""
launcher.py — PyInstaller entry point for BoxCutter

Starts Flask in a background thread, waits until the server is ready,
then opens the app in a native pywebview window (frozen binary only).
The main thread blocks inside webview.start() until the window is closed.
"""

import contextlib
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path as _DiagPath

# Permanent CI diagnostic — bundle-smoke's probe step dumps this file on every
# run so any future failure immediately surfaces (a) whether the launcher
# executed at all and (b) what env vars it actually saw on startup. Cheap to
# leave in: ~10 lines, runs once on launch, errors swallowed. Placed before
# any project imports so it fires even if downstream import chain breaks.
_diag_path = (
    _DiagPath(os.environ.get("TEMP", "C:\\Temp")) / "boxcutter-launcher-trace.txt"
    if sys.platform == "win32"
    else _DiagPath("/tmp/boxcutter-launcher-trace.txt")  # noqa: S108  # nosec B108 — intentional CI diagnostic path read by bundle-smoke probe
)
with contextlib.suppress(Exception):
    _diag_path.write_text(
        f"launcher started\n"
        f"BOXCUTTER_TESTING={os.environ.get('BOXCUTTER_TESTING', '<unset>')!r}\n"
        f"BOXCUTTER_PORT={os.environ.get('BOXCUTTER_PORT', '<unset>')!r}\n"
        f"frozen={getattr(sys, 'frozen', False)}\n"
        f"argv={sys.argv}\n"
        f"sys.executable={sys.executable}\n"
    )

from crash_logger import write_crash_log  # noqa: E402


def _excepthook(exc_type, exc_value, exc_tb):
    body = "".join(__import__("traceback").format_exception(exc_type, exc_value, exc_tb))
    log_path = write_crash_log("startup", body)
    if log_path:
        print(f"\n[crash] Log saved to: {log_path}", file=sys.stderr)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _excepthook

# Must set cwd before importing app so Flask resolves templates/static correctly
if getattr(sys, "frozen", False):
    os.chdir(sys._MEIPASS)
    # Script dispatch: app.py calls [sys.executable, script.py, ...] for every tool run.
    # In the frozen binary sys.executable is BoxCutter.exe, not Python. Detect this case
    # and execute the target script via runpy so the bundle's interpreter is used instead
    # of starting a second GUI instance (which would exit silently via the single-instance
    # guard, producing no output and making every tool appear to silently do nothing).
    if len(sys.argv) > 1 and sys.argv[1].endswith(".py"):
        import runpy  # stdlib — always available in the bundle

        script_path = sys.argv[1]
        sys.path.insert(0, os.path.dirname(script_path))  # so `from utils import …` resolves
        sys.argv = sys.argv[1:]  # shift: script path becomes argv[0] for argparse
        runpy.run_path(script_path, run_name="__main__")
        sys.exit(0)

from app import app  # noqa: E402


def _resolve_port() -> int:
    """Resolve the port the bundle should listen on.

    Honours BOXCUTTER_PORT env var (used by tests, multi-instance setups,
    and the bundle-smoke workflow). Defaults to 5000 for normal launches.
    Falls back to 5000 if the env var is set but unparseable.
    """
    raw = os.environ.get("BOXCUTTER_PORT", "").strip()
    if not raw:
        return 5000
    try:
        return int(raw)
    except ValueError:
        print(f"  WARNING: BOXCUTTER_PORT={raw!r} is not an integer — using default 5000")
        return 5000


PORT = _resolve_port()


def _already_running(port: int) -> bool:
    """Return True if something is already accepting connections on port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


# Daemon-thread exceptions don't trigger sys.excepthook, so a Flask startup
# failure inside _start_flask() would silently kill the thread and leave the
# main thread waiting forever — user sees a blank pywebview window with no log.
# Capture any exception here and write a crash log so it's diagnosable.
_flask_error: dict = {"exc": None}


def _start_flask():
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)  # noqa: S104  # nosec B104 — intentional: Tailscale requires binding to all interfaces
    except Exception as exc:
        body = "".join(__import__("traceback").format_exception(type(exc), exc, exc.__traceback__))
        write_crash_log("startup", body, context={"phase": "flask_thread"})
        _flask_error["exc"] = exc


def _wait_for_server():
    url = f"http://localhost:{PORT}"
    for _ in range(30):
        if _flask_error["exc"] is not None:
            # Flask thread already died — no point continuing to poll.
            raise RuntimeError(
                f"Flask failed to start: {_flask_error['exc']}. "
                f"See crash log in ~/.boxcutter_logs/."
            )
        try:
            urllib.request.urlopen(url, timeout=1)  # noqa: S310  # nosec B310 — always http://localhost, no user input
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    # Polling exhausted without a connection. Surface this rather than opening
    # a pywebview window pointing at a server that never came up.
    raise RuntimeError(
        f"Flask did not start within 15s on port {PORT}. See crash log in ~/.boxcutter_logs/."
    )


if __name__ == "__main__":
    # Single-instance guard: if BoxCutter is already running, exit silently.
    # The existing window is already open — no need to open anything new.
    if _already_running(PORT):
        sys.exit(0)

    # Test/headless mode: BOXCUTTER_TESTING=1 means no pywebview, no native
    # window, just Flask on the main thread. Required for bundle-smoke
    # (CI runners have no display) and useful for any non-GUI launch
    # (Tailscale-only listener mode, etc.).
    if os.environ.get("BOXCUTTER_TESTING") == "1":
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)  # noqa: S104
        sys.exit(0)

    import webview

    flask_thread = threading.Thread(target=_start_flask, daemon=True)
    flask_thread.start()
    _wait_for_server()

    window = webview.create_window(
        "BoxCutter",
        f"http://localhost:{PORT}",
        width=1280,
        height=820,
        min_size=(900, 600),
    )
    webview.start()
