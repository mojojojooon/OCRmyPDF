# -*- mode: python ; coding: utf-8 -*-
# SPDX-FileCopyrightText: 2026 OCRmyPDF contributors
# SPDX-License-Identifier: MPL-2.0

"""PyInstaller spec for the OCRmyPDF desktop window.

Build from the repository root with ``python desktop_app/build_app.py``.
The result is an onedir app at ``dist/OCRmyPDF/`` (onedir starts faster and
is more reliable for Qt than a single-file executable).

Tesseract and Ghostscript stay outside the bundle. A frozen app still needs
them installed, the same way the command-line tool does.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

spec_dir = Path(SPECPATH)
root = spec_dir.parent
entry = root / 'src' / 'ocrmypdf_gui' / '__main__.py'

hiddenimports = [
    name
    for name in collect_submodules('ocrmypdf') + collect_submodules('ocrmypdf_gui')
    if not name.startswith('ocrmypdf._pyinstaller')
]
datas = collect_data_files('ocrmypdf') + collect_data_files('pikepdf')

a = Analysis(
    [str(entry)],
    pathex=[str(root / 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OCRmyPDF',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='OCRmyPDF',
)
