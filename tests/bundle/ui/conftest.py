"""
Playwright fixtures for bundle UI smoke tests.

Like tests/e2e/conftest.py but targets the BUILT artifact instead of source:
    BOXCUTTER_BUNDLE_EXE=/path/to/BoxCutter.exe pytest tests/bundle/ui/

Without that env var, falls back to launching `python app.py` so the suite
can be run locally and in PR-time CI to validate the test logic itself.
The release-gate run (PR 6) sets BOXCUTTER_BUNDLE_EXE so the same tests
exercise the actual frozen build.

Why a separate conftest from tests/e2e/conftest.py:
- These tests assert bundle-only behaviour (Quit form CSRF, native window
  affordances) which the source e2e suite intentionally skips.
- Mixing the two would cross-contaminate the live_server fixture between
  the dev-mode e2e suite (always python app.py) and the bundle smoke suite
  (env-driven).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[3]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _resolve_launch_cmd() -> tuple[list[str], str]:
    """Return (cmd_argv, mode_label) for starting the server.

    If BOXCUTTER_BUNDLE_EXE points at a real file, use that — testing the
    frozen artifact. Otherwise fall back to `python app.py` in source mode.
    """
    bundle_exe = os.environ.get("BOXCUTTER_BUNDLE_EXE", "").strip()
    if bundle_exe and Path(bundle_exe).is_file():
        return [bundle_exe], f"bundle: {bundle_exe}"
    return [sys.executable, "app.py"], "source: python app.py"


@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    """Start the chosen server on a free port with an isolated temp config.
    Yields the base URL."""
    tmp = tmp_path_factory.mktemp("bundle_ui_config")
    config_path = tmp / "boxcutter_config.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")
    secret_path = tmp / "secret.bin"

    port = _find_free_port()

    env = os.environ.copy()
    env["BOXCUTTER_CONFIG_PATH"] = str(config_path)
    env["BOXCUTTER_SECRET_PATH"] = str(secret_path)
    env["BOXCUTTER_PORT"] = str(port)
    env["BOXCUTTER_TESTING"] = "1"

    cmd, mode = _resolve_launch_cmd()
    print(f"[bundle-ui] starting server in mode: {mode}")
    print(f"[bundle-ui] port: {port}")
    print(f"[bundle-ui] config: {config_path}")

    cwd = str(REPO_ROOT) if cmd[0] == sys.executable else str(Path(cmd[0]).parent)

    proc = subprocess.Popen(  # noqa: S603 — cmd built from env-validated path
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait until the server accepts connections (max 30 s — bundle startup is
    # slower than source-mode due to PyInstaller bootloader)
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=2)
            raise RuntimeError(
                f"Server exited with code {proc.returncode} before listening.\n"
                f"stdout: {stdout.decode(errors='replace')[-500:]}\n"
                f"stderr: {stderr.decode(errors='replace')[-500:]}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError(f"Server did not start on port {port} within 30s")

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


@pytest.fixture
def is_frozen_target() -> bool:
    """True if the live_server is the actual frozen bundle, False for source."""
    bundle_exe = os.environ.get("BOXCUTTER_BUNDLE_EXE", "").strip()
    return bool(bundle_exe and Path(bundle_exe).is_file())
