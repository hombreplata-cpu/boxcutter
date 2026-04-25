"""
launcher.py — PyInstaller entry point for BoxCutter

Starts Flask in a background thread, waits until the server is ready,
then opens the app in a native pywebview window (frozen binary only).
The main thread blocks inside webview.start() until the window is closed.
"""

import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

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

PORT = 5000


def _already_running(port: int) -> bool:
    """Return True if something is already accepting connections on port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _start_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)  # noqa: S104  # nosec B104 — intentional: Tailscale requires binding to all interfaces


def _wait_for_server():
    url = f"http://localhost:{PORT}"
    for _ in range(30):
        try:
            urllib.request.urlopen(url, timeout=1)  # noqa: S310  # nosec B310 — always http://localhost, no user input
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)


if __name__ == "__main__":
    # Single-instance guard: if BoxCutter is already running, exit silently.
    # The existing window is already open — no need to open anything new.
    if _already_running(PORT):
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
