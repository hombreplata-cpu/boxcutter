"""
Shared fixtures for Playwright E2E tests.

live_server  — starts app.py as a subprocess on a free port with an isolated
               temp config file so the user's ~/.boxcutter_config.json is never
               touched. Uses BOXCUTTER_CONFIG_PATH + BOXCUTTER_PORT env vars.
browser      — session-scoped headless Chromium instance.
page         — function-scoped Playwright page (new tab per test).
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).parent.parent.parent


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    """
    Start app.py as a subprocess on a free port with a temp config.
    Yields the base URL, e.g. 'http://127.0.0.1:54321'.
    """
    tmp = tmp_path_factory.mktemp("e2e_config")
    config_path = tmp / "boxcutter_config.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")

    port = _find_free_port()

    env = os.environ.copy()
    env["BOXCUTTER_CONFIG_PATH"] = str(config_path)
    env["BOXCUTTER_PORT"] = str(port)
    env["BOXCUTTER_TESTING"] = "1"  # suppresses browser-open timer

    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait until the server accepts connections (max 20 s)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.15)
    else:
        proc.terminate()
        raise RuntimeError(f"Flask test server did not start on port {port} within 20 s")

    base_url = f"http://127.0.0.1:{port}"
    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


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
