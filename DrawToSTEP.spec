# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DrawToSTEP (Windows .exe).

One-file build with everything bundled for offline use:
  - PySide6 UI, CadQuery/OCP (OpenCASCADE), OpenCV, RapidOCR models
  - the demo example PDF (flange_shaft_demo.pdf) and a real scan example
    (data/examples/real/scan_test.png — regenerated in CI before the build,
    never committed to git)

Build:  pyinstaller --noconfirm DrawToSTEP.spec
Output: dist/DrawToSTEP.exe
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "data/examples/flange_shaft_demo.pdf"), "data/examples"),
    (str(ROOT / "data/examples/real/shaft_3step_chamfer_bore.pdf"), "data/examples/real"),
    # regenerated in CI (gitignored); bundled so the exe works offline end-to-end
    (str(ROOT / "data/examples/real/scan_test.png"), "data/examples/real"),
]
binaries = []
hiddenimports = []

for package in (
    "cadquery",
    "OCP",
    "rapidocr_onnxruntime",
    "pymupdf",
    "fitz",
    "cv2",
    "numpy",
):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

# OCR configs & ONNX models (belt and braces — rapidocr_onnxruntime already
# ships them as package data, collect_all picks them up)
hiddenimports += ["rapidocr_onnxruntime", "onnxruntime"]

excludes = [
    "pytest",
    "matplotlib",
    "reportlab",
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
]

a = Analysis(
    ["app/main.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
    name="DrawToSTEP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    # windowed builds default to a modal "Fatal error" dialog on unhandled
    # exceptions, which hangs forever on headless CI runners. Print the
    # traceback to stderr instead so CI can capture it.
    disable_windowed_traceback=True,
    icon=None,
)
