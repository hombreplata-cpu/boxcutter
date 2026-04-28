# app.spec — PyInstaller build spec for BoxCutter (one-dir)
import sys

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# pywebview's transitive deps are not auto-discovered if `import webview`
# fails at PyInstaller-build time (collect_submodules silently returns []).
# List them explicitly so the bundle is correct regardless of whether the
# build environment has every transitive installed at import time.
_PYWEBVIEW_TRANSITIVE = [
    "proxy_tools",
    "bottle",
]
if sys.platform == "win32":
    # pythonnet's `clr` module is the .NET bridge pywebview uses to render
    # the native window on Windows. Without this the GUI fails at start().
    _PYWEBVIEW_TRANSITIVE += ["clr", "clr_loader"]
if sys.platform == "darwin":
    # pyobjc is the Cocoa bridge pywebview uses to render the native window
    # on macOS. collect_submodules('webview') does not reliably pull these in
    # transitively, so list them explicitly. Without this, webview.create_window()
    # raises ImportError deep in webview.platforms.cocoa at runtime — the
    # bundle launches, the trace file is written, but the GUI never appears.
    _PYWEBVIEW_TRANSITIVE += ["objc", "Foundation", "AppKit", "WebKit"]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("templates", "templates"),
        ("scripts", "scripts"),
        ("static", "static"),
    ],
    hiddenimports=collect_submodules("pyrekordbox")
    + collect_submodules("webview")
    # mutagen is imported by scripts/*.py only (relocate, add_new, fix_metadata,
    # strip_comment_urls). PyInstaller follows imports from launcher.py → app.py,
    # not from runpy-dispatched scripts, so its submodules (mutagen.flac,
    # mutagen.id3, mutagen.mp4, …) are never auto-discovered. Without this every
    # tag-touching tool crashes at import in the frozen build.
    + collect_submodules("mutagen")
    + _PYWEBVIEW_TRANSITIVE
    + [
        "sqlcipher3",
        "engineio.async_drivers.threading",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BoxCutter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="static/boxcutter.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BoxCutter",
)

# macOS .app bundle — ignored on Windows
app = BUNDLE(
    coll,
    name="BoxCutter.app",
    bundle_identifier="com.boxcutter.app",
    icon="static/boxcutter.icns",
)
