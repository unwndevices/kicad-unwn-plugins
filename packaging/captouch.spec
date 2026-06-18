# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — bundle the captouch CLI + GUI into one standalone binary.

Build from the repo root::

    pyinstaller packaging/captouch.spec --noconfirm

Produces ``dist/captouch`` (``dist/captouch.exe`` on Windows): a single file that
runs the whole CLI, and launches the PySide6 live-preview app via ``captouch gui``.
Smoke-test it headlessly with ``dist/captouch --version`` and
``QT_QPA_PLATFORM=offscreen dist/captouch gui --check``.

The same spec drives the macOS and Windows builds in CI (PyInstaller cannot
cross-compile, so each OS builds its own binary on its own runner).
"""

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH is the directory containing this spec (…/packaging); the repo is its
# parent and the importable package lives under src/.
REPO = os.path.dirname(SPECPATH)
SRC = os.path.join(REPO, "src")
ENTRY = os.path.join(SPECPATH, "captouch_entry.py")

# Make `captouch` importable while the spec is analysed (needed by
# collect_submodules and by the Analysis graph below).
sys.path.insert(0, SRC)

# Bundle every captouch submodule so lazily-imported ones (e.g. the gui package,
# only imported when `captouch gui` runs) are present in the binary.
hiddenimports = collect_submodules("captouch")

# Trim Qt modules this QtWidgets app never touches — these are the heavy ones
# (WebEngine alone is hundreds of MB). The `gui --check` smoke test exercises the
# real widget stack (QGraphicsView, combos, etc.), so an over-aggressive exclude
# would fail the build's verification rather than ship a broken binary.
EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "tkinter",
]

a = Analysis(
    [ENTRY],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="captouch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
