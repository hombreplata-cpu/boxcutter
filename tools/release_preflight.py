#!/usr/bin/env python3
"""
tools/release_preflight.py — strict pre-release gate.

Thin wrapper over `tools/check.py --strict`. Single source of truth for what
a release-gate run does. Invoked manually (Step 0 of the Release Workflow
in CONTRIBUTING.md) and by .github/workflows/release-gate.yml on tag pushes.

Exits with the first non-zero check's exit code. Run from the repo root.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    sys.exit(
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "check.py"), "--strict"],
            cwd=REPO_ROOT,
        ).returncode
    )
