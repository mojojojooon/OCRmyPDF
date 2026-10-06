# SPDX-FileCopyrightText: 2026 OCRmyPDF contributors
# SPDX-License-Identifier: MPL-2.0

"""Desktop window for turning scanned PDFs into searchable ones.

The window is started with ``ocrmypdf-gui`` or ``python -m ocrmypdf_gui``.
OCR itself is still :func:`ocrmypdf.ocr`; this package only supplies the
desktop layer.
"""

from __future__ import annotations

from ocrmypdf_gui.core import OcrSettings, run_ocr_file

__all__ = ['OcrSettings', 'run_ocr_file']
