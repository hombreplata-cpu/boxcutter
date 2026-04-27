#!/usr/bin/env python3
"""Bandit LOW-severity regression gate.

Counts LOW findings in app.py + scripts/ and exits 1 if the count
exceeds THRESHOLD. Cross-platform safe (no path matching).

We can't use bandit's --baseline file because filename matching is
platform-specific (./app.py on Linux vs .\\app.py on Windows) and
would need a separate baseline per OS. Counting is coarser but works
the same on every runner.

If you legitimately FIX a LOW finding, decrement THRESHOLD below by
the same number. Any NEW low-severity finding will then fail CI.
"""

from __future__ import annotations

import json
import subprocess
import sys

THRESHOLD = 34


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bandit",
            "-r",
            "app.py",
            "scripts/",
            "-l",
            "-f",
            "json",
            "--exit-zero",
        ],
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        print(result.stderr, file=sys.stderr)
        return 1
    data = json.loads(result.stdout)
    low_count = sum(1 for r in data["results"] if r["issue_severity"] == "LOW")
    print(f"Bandit LOW count: {low_count} / threshold {THRESHOLD}")
    if low_count > THRESHOLD:
        print(
            f"FAIL: LOW count {low_count} exceeds threshold {THRESHOLD} "
            "— new low-severity finding(s) introduced. Either fix them or, "
            "if accepted, raise THRESHOLD in tools/bandit_low_gate.py.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
