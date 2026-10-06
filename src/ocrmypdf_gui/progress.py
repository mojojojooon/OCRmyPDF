# SPDX-FileCopyrightText: 2026 OCRmyPDF contributors
# SPDX-License-Identifier: MPL-2.0

"""OCRmyPDF plugin that reports progress to the desktop window.

OCRmyPDF asks plugins for a progress-bar class and updates it on the thread
that called :func:`ocrmypdf.ocr`. A context variable carries the callback for
that call, so the bar never has to be pickled into a worker process.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from ocrmypdf import hookimpl

#: ``description``, work completed so far, and total work (``None`` if unknown).
ProgressCallback = Callable[[str, float, float | None], None]

_progress: ContextVar[ProgressCallback | None] = ContextVar(
    'ocrmypdf_gui_progress', default=None
)


@contextmanager
def bind_progress(callback: ProgressCallback | None) -> Iterator[None]:
    """Send progress events from the current OCR call to ``callback``."""
    token = _progress.set(callback)
    try:
        yield
    finally:
        _progress.reset(token)


class CallbackProgressBar:
    """Progress bar that forwards updates to :func:`bind_progress`."""

    def __init__(
        self,
        *,
        total: int | float | None = None,
        desc: str | None = None,
        unit: str | None = None,
        disable: bool = False,
        **kwargs: object,
    ) -> None:
        """Record the totals OCRmyPDF supplies for this stage of work."""
        del unit, kwargs
        self.total = float(total) if total is not None else None
        self.desc = desc or 'Working'
        self.disable = disable
        self.completed = 0.0

    def __enter__(self) -> CallbackProgressBar:
        """Start reporting this stage."""
        self._emit()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        """Leave exception handling to OCRmyPDF."""
        del exc_type, exc_value, traceback
        return False

    def update(self, n: float = 1, *, completed: float | None = None) -> None:
        """Advance this stage by ``n``, or set an absolute ``completed`` value."""
        if completed is not None:
            self.completed = float(completed)
        else:
            self.completed += float(n)
        self._emit()

    def _emit(self) -> None:
        if self.disable:
            return
        callback = _progress.get()
        if callback is None:
            return
        callback(self.desc, self.completed, self.total)


@hookimpl
def get_progressbar_class() -> type[CallbackProgressBar]:
    """Return the progress bar used while the desktop app is running OCR."""
    return CallbackProgressBar
