# PyInstaller spec for Flower 刷花助手
# Build: uv run pyinstaller specs/Flower.spec  (from project root)
# Output: dist/Flower.exe

block_cipher = None

a = Analysis(
    ["app/flower.py"],
    pathex=[".", "app"],
    binaries=[],
    datas=[],
    hiddenimports=[
        "win32api",
        "win32con",
        "win32gui",
        "pywintypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Flower",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    uac_admin=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
