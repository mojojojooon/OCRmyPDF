# SPDX-FileCopyrightText: 2026 OCRmyPDF contributors
# SPDX-License-Identifier: MPL-2.0

"""Start the OCRmyPDF desktop window."""

from __future__ import annotations

import multiprocessing
import sys

HELP = """\
Usage: ocrmypdf-gui

Open a window where you can drop scanned PDFs and get searchable copies back.
Each result is saved next to the original as <name>_searchable.pdf.

Tesseract OCR and Ghostscript must be installed. See desktop_app/README.md
for Windows install steps.

You can also start the window with: python -m ocrmypdf_gui
"""


def main(argv: list[str] | None = None) -> int:
    """Launch the desktop window.

    ``--help`` prints usage and does not open a window, which is useful when
    checking that the command is on PATH.

    Returns:
        Process exit code. ``0`` after the window closes, ``1`` if the GUI
        toolkit is not installed.
    """
    multiprocessing.freeze_support()
    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg in {'-h', '--help'} for arg in args):
        print(HELP)
        return 0

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(
            'The desktop app needs PySide6.\n'
            'Install OCRmyPDF with the gui extra:\n'
            '    pip install ocrmypdf[gui]\n'
            'or, from a checkout of this repository:\n'
            '    pip install -e ".[gui]"',
            file=sys.stderr,
        )
        return 1

    from ocrmypdf_gui.app import build_app_icon, create_window, install_style

    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName('OCRmyPDF')
    application.setWindowIcon(build_app_icon())
    install_style(application)
    window = create_window()
    window.show()
    return int(application.exec())


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
