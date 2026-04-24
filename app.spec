# app.spec — PyInstaller build spec for BoxCutter (one-dir)
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

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
    icon="static/favicon.ico",
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
