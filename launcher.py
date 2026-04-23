"""
launcher.py — PyInstaller entry point for rekordbox-tools

Starts Flask in a background thread, waits until the server is ready,
then opens the browser. The main thread blocks on the Flask thread so
the process stays alive until Flask exits.
"""

import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

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

from app import app  # noqa: E402

PORT = 5000


def _start_flask():
    app.run(port=PORT, debug=False, use_reloader=False)


def _wait_and_open():
    url = f"http://localhost:{PORT}"
    for _ in range(30):
        try:
            urllib.request.urlopen(url, timeout=1)  # noqa: S310  # nosec B310 — always http://localhost, no user input
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    webbrowser.open(url)


if __name__ == "__main__":
    flask_thread = threading.Thread(target=_start_flask, daemon=True)
    flask_thread.start()
    _wait_and_open()
    flask_thread.join()
