"""
Bundle import-contract test.

Runs INSIDE the bundled BoxCutter.exe / .app via the launcher's runpy script
dispatcher. Asserts that every package and submodule the production code
imports is bundled and importable.

This is the test that would have caught REG-001 (mutagen submodules missing
from the frozen build) at PR time. It catches the same class for any future
script-only import that PyInstaller's static analyser misses because it only
follows the entry-point graph from launcher.py → app.py.

How to run
----------

Locally against the source tree (smoke check):
    python tests/bundle/verify_imports.py

Against the frozen bundle (the real test):
    BoxCutter.exe path/to/tests/bundle/verify_imports.py

In CI, this is invoked via:
    BoxCutter.exe <bundled-path-to>/verify_imports.py

If any import fails, the script prints "[FAIL] ..." lines and exits non-zero.
The wrapping CI workflow (PR 6) treats non-zero exit as a release blocker.

What gets verified
------------------

Two kinds of imports:

1. **Top-level requirements** — every package in requirements.txt must
   import. If pyrekordbox or mutagen is missing entirely the bundle is
   broken.

2. **Per-script imports** — every `from X import Y` and `import X.Y` line
   in `scripts/*.py` and `app.py` is exercised. This is what catches
   submodule-level misses like REG-001 (mutagen.flac present but
   mutagen.id3 missing, or vice versa). Discovery is via AST walk if the
   scripts directory is findable; falls back to the hardcoded list below
   if not.

Adding a new dependency
-----------------------

If you add a new package to requirements.txt, also add it to
REQUIREMENTS_IMPORTS below. PyInstaller's static analyser may or may not
auto-discover it; this contract makes the requirement explicit and CI
will fail the next release if it didn't make it into the bundle.
"""

from __future__ import annotations

import ast
import importlib
import sys
import traceback
from pathlib import Path

# Top-level packages from requirements.txt. Each must import in the bundle
# AND in a typical dev Python (source-tree) install. Keep in sync with
# requirements.txt — adding a dep without adding it here is a drift bug.
REQUIREMENTS_IMPORTS = [
    "flask",
    "pyrekordbox",
    "mutagen",
    "webview",  # pywebview package name
    "proxy_tools",
    "bottle",
]

# Bundle-only imports: required when sys.frozen, exempt otherwise. These are
# pythonnet's runtime modules — only installed when `pip install pythonnet`
# runs as part of the PyInstaller build. Local dev environments typically
# don't have them.
BUNDLE_ONLY_IMPORTS = []
if sys.platform == "win32":
    BUNDLE_ONLY_IMPORTS.extend(["clr", "clr_loader"])

# Submodules the production code collectively touches. PyInstaller does NOT
# bundle these unless collect_submodules() is used in app.spec, so this list
# is the explicit contract — every entry here must be present in the bundle.
# REG-001 was caught precisely because mutagen.flac et al. weren't on this
# list (and not in app.spec); the new collect_submodules('mutagen') line
# fixes the build, this list locks in the verification.
EXPECTED_SUBMODULES = [
    # mutagen submodules — REG-001 class.
    "mutagen.flac",
    "mutagen.id3",
    "mutagen.mp4",
    "mutagen.mp3",
    "mutagen.wave",
    "mutagen.aiff",
    # sqlcipher3 — must be importable for pyrekordbox to open master.db.
    "sqlcipher3",
    # sqlalchemy — pulled in transitively by pyrekordbox.
    "sqlalchemy",
    "sqlalchemy.orm",
    # Flask deps the app relies on directly.
    "flask",
    "werkzeug.exceptions",
]

# App-root modules — at repo root in source mode, at _MEIPASS in frozen.
# Both layouts get added to sys.path before checking so these always resolve.
# NOTE: launcher.py is intentionally absent — PyInstaller compiles it INTO
# the bundle's executable as the entry point, so it's not importable as a
# module from inside the bundle. Including it here would fail every frozen run.
APP_ROOT_MODULES = [
    "app",
    "crash_logger",
    "version",
]


# ---------------------------------------------------------------------------
# AST walk over scripts/ to auto-discover imports
# ---------------------------------------------------------------------------


def _find_scripts_dir() -> Path | None:
    """Locate scripts/ in the running environment.

    Frozen bundle: lives at <_MEIPASS>/scripts/.
    Source tree:   lives at <repo-root>/scripts/.
    Returns None if neither resolves.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate = Path(sys._MEIPASS) / "scripts"  # noqa: SLF001
        if candidate.is_dir():
            return candidate
    here = Path(__file__).resolve()
    repo_scripts = here.parent.parent.parent / "scripts"
    if repo_scripts.is_dir():
        return repo_scripts
    return None


def _imports_from_file(path: Path) -> set[str]:
    """Extract every module name imported in path. Returns module names like
    'mutagen.flac' (not symbol names). Skips relative imports."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


# Modules that exist in source but not in the bundle (and don't need to).
# Anything in this set is exempt from the contract.
_LOCAL_ONLY = {
    "utils",  # bundled as a data file, imported by sys.path tweak in launcher
    "scripts.utils",
}

# Stdlib-only modules — always importable, no point checking.
_SKIP = {
    "os",
    "sys",
    "re",
    "json",
    "argparse",
    "shutil",
    "datetime",
    "pathlib",
    "hashlib",
    "subprocess",
    "platform",
    "tempfile",
    "urllib",
    "secrets",
    "threading",
    "time",
    "contextlib",
    "signal",
    "socket",
    "webbrowser",
    "traceback",
    "uuid",
    "typing",
    "collections",
    "functools",
    "itertools",
    "copy",
    "unicodedata",
    "ast",
    "importlib",
    "io",
    "struct",
    "wave",
    "aifc",
    "warnings",
    "logging",
    "dataclasses",
    "abc",
    "enum",
    "math",
    "random",
    "string",
    "html",
    "urllib.parse",
    "urllib.request",
    "urllib.error",
    "http",
    "http.client",
    "http.server",
    "email",
    "base64",
    "binascii",
    "codecs",
    "operator",
    "weakref",
    "queue",
    "concurrent",
    "concurrent.futures",
    "asyncio",
    "ssl",
    "ipaddress",
    "decimal",
    "fractions",
    "statistics",
}


def _is_skippable(modname: str) -> bool:
    if modname in _SKIP or modname in _LOCAL_ONLY:
        return True
    # Submodule of stdlib? (e.g. urllib.parse — already in _SKIP, but be defensive)
    root = modname.split(".", 1)[0]
    return root in _SKIP


def _try_import(modname: str) -> tuple[bool, str]:
    """Return (ok, error_message)."""
    try:
        importlib.import_module(modname)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _setup_paths() -> Path:
    """Add the app root and scripts/ to sys.path so app.py / utils / crash_logger
    resolve regardless of which directory the test was invoked from.
    Returns the resolved app root."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        root_dir = Path(sys._MEIPASS)  # noqa: SLF001
    else:
        root_dir = Path(__file__).resolve().parent.parent.parent
    for p in (root_dir, root_dir / "scripts"):
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))
    return root_dir


def main() -> int:
    print("=" * 70)
    is_frozen = getattr(sys, "frozen", False)
    print(f"Bundle import-contract test (frozen={is_frozen})")
    print(f"Python: {sys.version.split()[0]} on {sys.platform}")
    print("=" * 70)

    root_dir = _setup_paths()
    print(f"App root: {root_dir}")

    failures: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _check(modname: str, source: str, *, required: bool = True) -> None:
        if modname in seen or _is_skippable(modname):
            return
        seen.add(modname)
        ok, err = _try_import(modname)
        if ok:
            print(f"  [OK]   {modname}  (source: {source})")
        elif not required:
            print(f"  [skip] {modname}  (source: {source})  — {err}  [not required here]")
        else:
            print(f"  [FAIL] {modname}  (source: {source})  — {err}")
            failures.append((modname, err))

    # 1. Top-level requirements
    print("\n--- Top-level requirements ---")
    for mod in REQUIREMENTS_IMPORTS:
        _check(mod, "requirements.txt")

    # 2. Bundle-only imports — required when frozen, soft-skip in source.
    print("\n--- Bundle-only imports ---")
    for mod in BUNDLE_ONLY_IMPORTS:
        _check(mod, "bundle-only contract", required=is_frozen)

    # 3. Hardcoded expected submodules
    print("\n--- Expected submodules (REG-001 class) ---")
    for mod in EXPECTED_SUBMODULES:
        _check(mod, "expected-submodules contract")

    # 4. App root modules
    print("\n--- App-root modules ---")
    for mod in APP_ROOT_MODULES:
        _check(mod, "app root")

    # 5. AST walk over scripts/ if findable
    scripts_dir = _find_scripts_dir()
    if scripts_dir is None:
        print("\n--- AST walk: SKIPPED (scripts/ dir not findable) ---")
    else:
        print(f"\n--- AST walk over {scripts_dir} ---")
        for py_file in sorted(scripts_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            for modname in sorted(_imports_from_file(py_file)):
                _check(modname, f"scripts/{py_file.name}")

    # 6. AST walk over app.py / launcher.py / crash_logger.py at app root
    print("\n--- AST walk over app root ---")
    for fn in ("app.py", "launcher.py", "crash_logger.py"):
        py_file = root_dir / fn
        if not py_file.is_file():
            print(f"  [skip] {fn} not present at {root_dir}")
            continue
        for modname in sorted(_imports_from_file(py_file)):
            _check(modname, fn)

    # Summary
    print("\n" + "=" * 70)
    if failures:
        print(f"FAILED — {len(failures)} import(s) broken in the bundle:")
        for modname, err in failures:
            print(f"  • {modname}: {err}")
        print("=" * 70)
        return 1

    print(f"OK — {len(seen)} imports verified, all importable in this environment.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
