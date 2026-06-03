"""Tests for launcher._resolve_bind_host() — the macOS PIN-gated network bind.

Remote listen over Tailscale requires the server to bind 0.0.0.0. On macOS we
only do that once a listener PIN is configured (opt-in); otherwise we stay on
127.0.0.1. Windows/Linux always bind 0.0.0.0. BOXCUTTER_BIND overrides all.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import launcher  # noqa: E402  — importing must not crash on module-level side effects

ALL_INTERFACES = "0.0.0.0"  # noqa: S104 — expected bind value under test, not a real bind
LOCALHOST = "127.0.0.1"


def test_launcher_imports_cleanly():
    """Sanity: the module-level diagnostic write / excepthook setup at import
    time must not break test collection."""
    assert hasattr(launcher, "_resolve_bind_host")


def _bind(platform_name, config=None, env=None, config_raises=False):
    env = env or {}
    with (
        patch.object(launcher.sys, "platform", platform_name),
        patch.object(launcher.os, "environ", env),
    ):
        if config_raises:
            with patch.object(launcher, "load_config", side_effect=RuntimeError("boom")):
                return launcher._resolve_bind_host()
        with patch.object(launcher, "load_config", return_value=config or {}):
            return launcher._resolve_bind_host()


def test_darwin_with_pin_binds_all_interfaces():
    assert _bind("darwin", config={"listen_pin": "1234"}) == ALL_INTERFACES


def test_darwin_without_pin_binds_localhost():
    assert _bind("darwin", config={"listen_pin": ""}) == LOCALHOST


def test_darwin_config_error_falls_back_to_localhost():
    assert _bind("darwin", config_raises=True) == LOCALHOST


def test_boxcutter_bind_override_wins_on_darwin():
    # Override beats the localhost default even with no PIN.
    result = _bind("darwin", config={"listen_pin": ""}, env={"BOXCUTTER_BIND": ALL_INTERFACES})
    assert result == ALL_INTERFACES


def test_windows_always_binds_all_interfaces():
    assert _bind("win32", config={"listen_pin": ""}) == ALL_INTERFACES


def test_linux_always_binds_all_interfaces():
    assert _bind("linux", config={"listen_pin": ""}) == ALL_INTERFACES
