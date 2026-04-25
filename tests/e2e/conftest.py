"""
Shared fixtures for Playwright E2E tests.

live_server  — starts a real Flask server in a daemon thread on a free port,
               using a temp config file so the user's ~/.boxcutter_config.json
               is never touched.
browser      — session-scoped headless Chromium instance.
page         — function-scoped Playwright page (new tab per test).
"""

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

# Make the repo root importable from this file's location (tests/e2e/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    """
    Start the Flask app on a free port with an isolated temp config.
    Yields the base URL, e.g. 'http://127.0.0.1:54321'.
    """
    tmp = tmp_path_factory.mktemp("e2e_config")
    config_path = tmp / "boxcutter_config.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")

    port = _find_free_port()
    os.environ["BOXCUTTER_CONFIG_PATH"] = str(config_path)

    # Import app after setting the env var so CONFIG_FILE resolves to our temp path
    import importlib

    import app as flask_app

    importlib.reload(flask_app)

    def _run():
        flask_app.app.run(
            host="127.0.0.1",
            port=port,
            use_reloader=False,
            threaded=True,
            debug=False,
        )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    # Wait until the server is accepting connections (max 15 s)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError(f"Flask test server did not start on port {port} within 15 s")

    base_url = f"http://127.0.0.1:{port}"
    yield base_url

    os.environ.pop("BOXCUTTER_CONFIG_PATH", None)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    p = browser.new_page()
    yield p
    p.close()
