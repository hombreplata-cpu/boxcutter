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
