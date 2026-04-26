"""
crash_logger.py — stdlib-only crash log writer for BoxCutter

Imported by both app.py and launcher.py. No Flask dependency so it
survives import failures in either module.
"""

import platform
import secrets
import sys
import traceback as tb
from datetime import datetime
from pathlib import Path

try:
    from version import __version__ as APP_VERSION
except ImportError:
    APP_VERSION = "unknown"

LOG_DIR = Path.home() / ".boxcutter_logs"


def write_crash_log(surface: str, body: str, context: dict | None = None) -> Path | None:
    """Write a structured crash log and return the Path.

    Never raises — a logging failure must not mask the real crash.

    Args:
        surface:  "startup" | "route" | "script"
        body:     Full traceback string or captured script output
        context:  Optional dict with extra fields (e.g. request URL, script name)
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now()
        # Append a short random suffix so two crashes in the same second don't
        # overwrite each other (R-06).
        filename = f"crash_{ts.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}.log"
        log_path = LOG_DIR / filename

        mode = "frozen" if getattr(sys, "frozen", False) else "dev"
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        lines = [
            "=== BoxCutter crash log ===",
            f"Time:      {ts.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Version:   {APP_VERSION}",
            f"Platform:  {platform.platform()}",
            f"Python:    {py_ver}",
            f"Mode:      {mode}",
            "",
            "=== Context ===",
            f"Surface:   {surface}",
        ]

        if context:
            for key, value in context.items():
                lines.append(f"{key + ':':10} {value}")

        lines += [
            "",
            "=== Output / Traceback ===",
            body,
        ]

        log_path.write_text("\n".join(lines), encoding="utf-8")
        return log_path
    except Exception:  # noqa: BLE001
        return None


def current_traceback() -> str:
    """Return the current exception traceback as a string."""
    return tb.format_exc()
