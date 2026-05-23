# -*- mode: python ; coding: utf-8 -*-
# GP2Logic — PyInstaller build spec for macOS .app bundle
#
# Usage:
#   pyinstaller GP2Logic.spec
#
# Output:
#   dist/GP2Logic.app   ← drag this to /Applications

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Collect PyQt6 data files (Qt plugins, translations, etc.) ──────────────
pyqt6_datas = collect_data_files("PyQt6", includes=["Qt6/plugins/**/*"])

# ── guitarpro ships some internal data (effect definitions, etc.) ──────────
guitarpro_datas = collect_data_files("guitarpro")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("presets", "presets"),          # built-in preset JSON files
        *pyqt6_datas,
        *guitarpro_datas,
    ],
    hiddenimports=[
        *collect_submodules("guitarpro"),
        "mido",
        "mido.backends",
        "PyQt6.QtPrintSupport",          # needed by some Qt widgets at runtime
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest",
        "pydoc", "doctest", "difflib",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GP2Logic",
    debug=False,
    strip=False,
    upx=False,          # UPX can break Qt dylibs on macOS
    console=False,      # windowed GUI — no Terminal window
    argv_emulation=False,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="GP2Logic",
)

app = BUNDLE(
    coll,
    name="GP2Logic.app",
    icon=None,           # place GP2Logic.icns here to add a custom icon
    bundle_identifier="com.kobayashikk.gp2logic",
    info_plist={
        "CFBundleName":              "GP2Logic",
        "CFBundleDisplayName":       "GP2Logic",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion":           "1",
        "NSPrincipalClass":          "NSApplication",
        "NSHighResolutionCapable":   True,
        "LSMinimumSystemVersion":    "12.0",
        # Associate .gp / .gpx files with this app
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName":       "Guitar Pro File",
                "CFBundleTypeExtensions": ["gp", "gpx", "gp5", "gp4", "gp3"],
                "CFBundleTypeRole":       "Viewer",
            }
        ],
    },
)
