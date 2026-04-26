#!/usr/bin/env python3
"""
tools/check.py — single command for local quality checks.

Mirrors CI exactly so a green local run is a green CI run (modulo
platform-specific bugs). Three modes:

    tools/check.py --fast      ruff only — meant for pre-commit (~5s)
    tools/check.py             default: + pytest unit + bandit-baseline
    tools/check.py --strict    + pytest e2e + installer-build smoke (Win)
                               equivalent to tools/release_preflight.py

Exits with the FIRST non-zero return code seen, so CI logs surface the
relevant failure first. Designed to be re-runnable.
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(label: str, cmd: list[str]) -> int:
    """Run a command, stream output, return its exit code."""
    print(f"\n--- {label} " + "-" * (60 - len(label)))
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    return result.returncode


def fast_checks() -> list[tuple[str, list[str]]]:
    base = [
        ("ruff format --check", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("ruff check", [sys.executable, "-m", "ruff", "check", "."]),
    ]
    # Layer 1 invariant tests — fast (<2s), high signal. Only invoke
    # pytest if at least one invariant file exists, so the script works
    # during the bootstrap window when these tests are not yet committed.
    invariant_files = [
        f
        for f in [
            "tests/test_invariants_routes.py",
            "tests/test_invariants_static.py",
        ]
        if (REPO_ROOT / f).exists()
    ]
    if invariant_files:
        base.append(
            (
                "invariant tests",
                [sys.executable, "-m", "pytest", *invariant_files, "-x", "--no-header"],
            )
        )
    return base


def default_checks() -> list[tuple[str, list[str]]]:
    baseline = REPO_ROOT / "tools" / "bandit-baseline.json"
    bandit_cmd = [sys.executable, "-m", "bandit", "-r", "app.py", "scripts/", "-l"]
    if baseline.exists():
        bandit_cmd += ["--baseline", str(baseline)]
    return [
        *fast_checks(),
        (
            "pytest (unit)",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/",
                "--ignore=tests/e2e",
                "-x",
                "--no-header",
            ],
        ),
        ("bandit (low + baseline)", bandit_cmd),
    ]


def strict_checks() -> list[tuple[str, list[str]]]:
    checks = list(default_checks())
    checks.append(
        (
            "pytest (e2e)",
            [sys.executable, "-m", "pytest", "tests/e2e", "-x", "--no-header"],
        )
    )
    if platform.system() == "Windows":
        # Installer-build smoke is Windows-only (Inno Setup).
        # We only verify the spec parses + imports succeed; full build
        # belongs in the release.yml workflow.
        checks.append(
            (
                "installer spec smoke",
                [sys.executable, "-c", "import app.spec  # noqa: F401  # parse-only"],
            )
        )
    return checks


def aggregate(checks: list[tuple[str, list[str]]]) -> int:
    first_fail = 0
    for label, cmd in checks:
        rc = run(label, cmd)
        # pytest exit 5 means "no tests collected" — treat as soft-pass
        # so this script works during bootstrap when invariant tests
        # haven't been committed yet.
        if rc == 5 and "pytest" in cmd[1:]:
            print(f"   (no tests collected — soft pass for {label})")
            continue
        if rc != 0 and first_fail == 0:
            first_fail = rc
            print(f"\n   FAIL: {label} (exit {rc})")
    if first_fail == 0:
        print("\nOK: all checks passed")
    return first_fail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fast", action="store_true", help="ruff + invariants only")
    mode.add_argument(
        "--strict", action="store_true", help="full release-gate (e2e + installer smoke)"
    )
    args = parser.parse_args()

    if args.fast:
        return aggregate(fast_checks())
    if args.strict:
        return aggregate(strict_checks())
    return aggregate(default_checks())


if __name__ == "__main__":
    sys.exit(main())
