# app.spec — PyInstaller build spec for rekordbox-tools
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("templates", "templates"),
        ("scripts", "scripts"),
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
    a.binaries,
    a.zipfiles,
    a.datas,
    name="rekordbox-tools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

# macOS .app bundle — ignored on Windows
app = BUNDLE(
    exe,
    name="rekordbox-tools.app",
    bundle_identifier="com.rekordbox-tools.app",
)
