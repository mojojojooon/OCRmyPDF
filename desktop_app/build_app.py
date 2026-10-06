# SPDX-FileCopyrightText: 2026 OCRmyPDF contributors
# SPDX-License-Identifier: MPL-2.0

"""Build a standalone OCRmyPDF desktop app with PyInstaller.

Tesseract and Ghostscript are not bundled. Install them separately and keep
them on PATH (on Windows, OCRmyPDF also checks the usual install locations).

From the repository root, after ``pip install pyinstaller``::

    python desktop_app/build_app.py

The app is written to ``dist/OCRmyPDF/``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """Run PyInstaller on ``ocrmypdf-gui.spec``."""
    try:
        import PyInstaller.__main__
    except ImportError:
        print(
            'PyInstaller is not installed. Install it with:\n'
            '    pip install pyinstaller',
            file=sys.stderr,
        )
        return 1
    spec = Path(__file__).resolve().parent / 'ocrmypdf-gui.spec'
    PyInstaller.__main__.run([str(spec), '--noconfirm'])
    print('Built dist/OCRmyPDF/')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
