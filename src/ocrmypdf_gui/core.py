# SPDX-FileCopyrightText: 2026 OCRmyPDF contributors
# SPDX-License-Identifier: MPL-2.0

"""OCR jobs for the desktop app, without any GUI toolkit.

The window calls :func:`run_ocr_file`. Tests can call it the same way.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import ocrmypdf
from ocrmypdf.exceptions import (
    EncryptedPdfError,
    ExitCode,
    ExitCodeException,
    InputFileError,
    MissingDependencyError,
    PriorOcrFoundError,
    TaggedPDFError,
)
from ocrmypdf_gui.progress import ProgressCallback, bind_progress

PROGRESS_PLUGIN = 'ocrmypdf_gui.progress'

# Names Tesseract prints that are not document languages.
_IGNORED_LANGS = frozenset({'osd', 'equ'})

LANGUAGE_NAMES: dict[str, str] = {
    'afr': 'Afrikaans',
    'ara': 'Arabic',
    'ces': 'Czech',
    'chi_sim': 'Chinese, simplified',
    'chi_tra': 'Chinese, traditional',
    'dan': 'Danish',
    'deu': 'German',
    'ell': 'Greek',
    'eng': 'English',
    'fin': 'Finnish',
    'fra': 'French',
    'heb': 'Hebrew',
    'hin': 'Hindi',
    'hun': 'Hungarian',
    'ind': 'Indonesian',
    'ita': 'Italian',
    'jpn': 'Japanese',
    'kor': 'Korean',
    'nld': 'Dutch',
    'nor': 'Norwegian',
    'pol': 'Polish',
    'por': 'Portuguese',
    'ron': 'Romanian',
    'rus': 'Russian',
    'spa': 'Spanish',
    'swe': 'Swedish',
    'tur': 'Turkish',
    'ukr': 'Ukrainian',
    'vie': 'Vietnamese',
}

FALLBACK_LANGUAGES: tuple[str, ...] = (
    'eng',
    'deu',
    'fra',
    'spa',
    'ita',
    'por',
    'nld',
    'pol',
    'rus',
    'ukr',
)

_LANG_CODE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')
_DISPLAY_CODE = re.compile(r'^[A-Za-z0-9_ ,]+\(([A-Za-z][A-Za-z0-9_]*)\)\s*$')
_NAME_TO_CODE = {name.casefold(): code for code, name in LANGUAGE_NAMES.items()}
_GS_NAMES = frozenset({'gs', 'gswin64c', 'ghostscript'})


@dataclass(frozen=True)
class OcrSettings:
    """Options the desktop window exposes for one OCR run."""

    languages: tuple[str, ...] = ('eng',)
    deskew: bool = False
    rotate_pages: bool = False
    skip_existing_text: bool = True
    force_ocr: bool = False

    def as_ocr_kwargs(self) -> dict[str, object]:
        """Keyword arguments for :func:`ocrmypdf.ocr`.

        Skipping existing text is the default, because a scanned file that
        already contains a text layer is usually already searchable. Forcing
        OCR wins when both are set, which is how a one-file retry works.
        """
        if self.force_ocr:
            mode = 'force'
        elif self.skip_existing_text:
            mode = 'skip'
        else:
            mode = 'default'
        return {
            'language': list(self.languages),
            'deskew': self.deskew,
            'rotate_pages': self.rotate_pages,
            'mode': mode,
            'progress_bar': True,
            'plugins': [PROGRESS_PLUGIN],
        }


@dataclass(frozen=True)
class OcrResult:
    """Outcome of running OCR on one file."""

    ok: bool
    code: str
    message: str
    input_path: Path
    output_path: Path | None = None


def parse_languages(text: str) -> tuple[str, ...]:
    """Parse a language box value such as ``eng`` or ``eng+fra``.

    A combo label like ``English (eng)`` is reduced to its code. A known
    language name such as ``English`` is accepted too. Codes are separated
    with ``+`` or a comma, not spaces.

    Raises:
        ValueError: The text is empty or is not a Tesseract language code.
    """
    raw = text.strip()
    display = _DISPLAY_CODE.fullmatch(raw)
    if display:
        return (display.group(1),)
    named = _NAME_TO_CODE.get(raw.casefold())
    if named:
        return (named,)
    codes = tuple(piece.strip() for piece in re.split(r'[+,]', raw) if piece.strip())
    if not codes or any(_LANG_CODE.fullmatch(code) is None for code in codes):
        raise ValueError(
            'Enter a Tesseract language code such as eng, or combine them as eng+fra.'
        )
    return codes


def language_choices() -> list[tuple[str, str]]:
    """Return ``(code, label)`` pairs for the language menu.

    Installed Tesseract languages are listed when the program is available.
    Otherwise a short built-in list is used so the menu still has a default.
    English is first when it is present.
    """
    codes = installed_language_codes()
    if not codes:
        codes = list(FALLBACK_LANGUAGES)
    choices = [(code, _language_label(code)) for code in codes]
    choices.sort(key=lambda item: (item[0] != 'eng', item[1].casefold()))
    return choices


def installed_language_codes() -> list[str] | None:
    """Return Tesseract language codes, or ``None`` if Tesseract cannot answer."""
    try:
        from ocrmypdf._exec import tesseract

        if not tesseract.available():
            return None
        reported = tesseract.get_languages()
    except Exception:
        return None
    return sorted(code for code in reported if code not in _IGNORED_LANGS)


def searchable_output_path(input_path: Path) -> Path:
    """Return a new ``<name>_searchable.pdf`` path next to ``input_path``.

    The original file is never returned. If the preferred name already exists,
    a numeric suffix is added (``_searchable_2``, then ``_searchable_3``, ...).
    """
    directory = input_path.parent
    stem = input_path.stem
    candidate = directory / f'{stem}_searchable.pdf'
    counter = 2
    while _path_taken(candidate, input_path):
        candidate = directory / f'{stem}_searchable_{counter}.pdf'
        counter += 1
        if counter > 10_000:
            raise RuntimeError(f'Could not find a free name for {input_path.name}')
    return candidate


def accept_input_files(paths: Iterable[Path | str]) -> tuple[list[Path], list[str]]:
    """Split dropped paths into PDFs to queue and messages for the rest."""
    accepted: list[Path] = []
    problems: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            problems.append(f'{path.name} is a folder. Drop PDF files instead.')
            continue
        if path.suffix.lower() != '.pdf':
            problems.append(f'{path.name} is not a PDF file.')
            continue
        if not path.is_file():
            problems.append(f'Could not find {path.name}.')
            continue
        accepted.append(path.resolve())
    return accepted, problems


def startup_warnings() -> list[str]:
    """Messages to show when Tesseract or Ghostscript is not installed."""
    try:
        from ocrmypdf._exec import ghostscript, tesseract
    except Exception as exc:
        return [f'Could not check for Tesseract and Ghostscript ({exc}).']
    warnings: list[str] = []
    if not tesseract.available():
        warnings.append(tesseract_install_instructions())
    if not ghostscript.available():
        warnings.append(ghostscript_install_instructions())
    return warnings


def explain_failure(
    exc: BaseException, log_lines: Sequence[str] | None = None
) -> tuple[str, str]:
    """Turn an OCRmyPDF exception into a short code and a message for the window.

    The code is one of ``already_has_text``, ``tagged_pdf``,
    ``missing_tesseract``, ``missing_ghostscript``, ``missing_language``,
    ``encrypted``, or ``error``.
    """
    code = _classify(exc)
    message = _message_for(code, exc)
    extra = _useful_log_lines(message, log_lines or ())
    if extra:
        message = f'{message}\n\nDetails:\n{extra}'
    return code, message


def run_ocr_file(
    input_path: Path,
    settings: OcrSettings,
    *,
    output_path: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> OcrResult:
    """Run :func:`ocrmypdf.ocr` on one PDF and return a result instead of raising.

    The output is written beside the input as ``<name>_searchable.pdf`` unless
    ``output_path`` is given. The original file is not overwritten. Progress
    events are delivered on the same thread that called this function.
    """
    input_path = Path(input_path)
    if input_path.suffix.lower() != '.pdf' or not input_path.is_file():
        return OcrResult(
            ok=False,
            code='error',
            message=f'{input_path.name} is not a PDF file.',
            input_path=input_path,
        )

    destination = (
        Path(output_path)
        if output_path is not None
        else searchable_output_path(input_path)
    )
    if destination.resolve() == input_path.resolve():
        return OcrResult(
            ok=False,
            code='error',
            message='Refusing to overwrite the original PDF.',
            input_path=input_path,
        )
    preexisting = destination.exists()
    notes: list[str] = []
    handler = _CaptureHandler(notes)
    logger = logging.getLogger('ocrmypdf')
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        with bind_progress(on_progress):
            code = ocrmypdf.ocr(input_path, destination, **settings.as_ocr_kwargs())
    except ExitCodeException as exc:
        _remove_failed_output(destination, preexisting)
        failure, message = explain_failure(exc, notes)
        return OcrResult(False, failure, message, input_path, None)
    except Exception as exc:
        _remove_failed_output(destination, preexisting)
        _failure, message = explain_failure(exc, notes)
        return OcrResult(False, 'error', message, input_path, None)
    else:
        if (
            code != ExitCode.ok
            or not destination.is_file()
            or destination.stat().st_size == 0
        ):
            _remove_failed_output(destination, preexisting)
            return OcrResult(
                ok=False,
                code='error',
                message='OCRmyPDF finished without creating a PDF.',
                input_path=input_path,
            )
        return OcrResult(
            ok=True,
            code='ok',
            message=f'Saved {destination.name}',
            input_path=input_path,
            output_path=destination,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def open_file(path: Path) -> None:
    """Open ``path`` with the desktop's usual application."""
    _launch(path, reveal=False)


def reveal_in_folder(path: Path) -> None:
    """Show ``path`` in the file manager, selecting it when that is supported."""
    _launch(path, reveal=True)


def tesseract_install_instructions() -> str:
    """Explain how to install Tesseract on this operating system."""
    if sys.platform == 'win32':
        return (
            'Tesseract OCR is not installed, or it is not on PATH. '
            'OCRmyPDF needs it to read scanned pages.\n'
            'Install the 64-bit build, then start this app again from a new window:\n'
            '  winget install -e --id tesseract-ocr.tesseract\n'
            'Or use the installer from https://github.com/UB-Mannheim/tesseract/wiki'
        )
    if sys.platform == 'darwin':
        return (
            'Tesseract OCR is not installed, or it is not on PATH. '
            'OCRmyPDF needs it to read scanned pages.\n'
            'Install it with Homebrew, then start this app again:\n'
            '  brew install tesseract'
        )
    return (
        'Tesseract OCR is not installed, or it is not on PATH. '
        'OCRmyPDF needs it to read scanned pages.\n'
        'On Debian or Ubuntu: sudo apt install tesseract-ocr\n'
        'On Fedora: sudo dnf install tesseract tesseract-osd'
    )


def ghostscript_install_instructions() -> str:
    """Explain how to install Ghostscript on this operating system."""
    if sys.platform == 'win32':
        return (
            'Ghostscript is not installed, or it is not on PATH. '
            'OCRmyPDF uses it when converting a PDF (including PDF/A).\n'
            'Install the 64-bit build from https://ghostscript.com/releases/gsdnld.html\n'
            'Or, in an Administrator command prompt: choco install ghostscript'
        )
    if sys.platform == 'darwin':
        return (
            'Ghostscript is not installed, or it is not on PATH. '
            'OCRmyPDF uses it when converting a PDF (including PDF/A).\n'
            'Install it with Homebrew, then start this app again:\n'
            '  brew install ghostscript'
        )
    return (
        'Ghostscript is not installed, or it is not on PATH. '
        'OCRmyPDF uses it when converting a PDF (including PDF/A).\n'
        'On Debian or Ubuntu: sudo apt install ghostscript\n'
        'On Fedora: sudo dnf install ghostscript'
    )


class _CaptureHandler(logging.Handler):
    """Keep a short list of OCRmyPDF log lines from one job."""

    def __init__(self, sink: list[str]) -> None:
        super().__init__(level=logging.INFO)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        """Store one formatted log line."""
        try:
            self._sink.append(record.getMessage())
        except Exception:
            self.handleError(record)


def _language_label(code: str) -> str:
    name = LANGUAGE_NAMES.get(code)
    if name:
        return f'{name} ({code})'
    return code


def _path_taken(candidate: Path, original: Path) -> bool:
    if candidate.exists():
        return True
    try:
        return candidate.resolve() == original.resolve()
    except OSError:
        return False


def _remove_failed_output(path: Path, preexisting: bool) -> None:
    if preexisting or not path.exists():
        return
    with suppress(OSError):
        path.unlink()


def _classify(exc: BaseException) -> str:
    if isinstance(exc, PriorOcrFoundError):
        return 'already_has_text'
    if isinstance(exc, TaggedPDFError):
        return 'tagged_pdf'
    if isinstance(exc, EncryptedPdfError):
        return 'encrypted'
    if isinstance(exc, MissingDependencyError):
        return _classify_missing(str(exc))
    return 'error'


def _classify_missing(text: str) -> str:
    lowered = text.lower()
    if 'language' in lowered:
        return 'missing_language'
    stripped = lowered.strip()
    if stripped in _GS_NAMES or 'ghostscript' in lowered:
        return 'missing_ghostscript'
    if 'tesseract' in lowered:
        return 'missing_tesseract'
    return 'error'


def _message_for(code: str, exc: BaseException) -> str:
    detail = str(exc).strip()
    if code == 'already_has_text':
        lead = (
            'This PDF already has text, so OCR stopped rather than duplicating it. '
            'Skip pages that already have text, or force OCR to scan the pages again.'
        )
    elif code == 'tagged_pdf':
        lead = (
            'This PDF is tagged, which usually means it already came from a document '
            'and has text. Skip those pages, or force OCR. Forcing OCR discards the '
            'tag structure on pages it reprocesses.'
        )
    elif code == 'missing_tesseract':
        lead = tesseract_install_instructions()
    elif code == 'missing_ghostscript':
        lead = ghostscript_install_instructions()
    elif code == 'missing_language':
        lead = (
            'Tesseract does not have language data for the language you chose. '
            'Install that language pack, or pick another language such as English.'
        )
    elif code == 'encrypted':
        lead = (
            'This PDF is password-protected. Remove the password with a PDF tool, '
            'then try again. OCRmyPDF does not remove passwords.'
        )
    elif isinstance(exc, InputFileError):
        lead = 'This PDF could not be read.'
    else:
        lead = 'OCR failed.'
    if not detail or detail.lower() in _GS_NAMES or detail.lower() == 'tesseract':
        return lead
    if detail in lead:
        return lead
    return f'{lead}\n\n{detail}'


def _useful_log_lines(message: str, log_lines: Sequence[str]) -> str:
    kept: list[str] = []
    for line in log_lines:
        text = ' '.join(line.split())
        if not text or text in message or text in kept:
            continue
        kept.append(text)
    return '\n'.join(kept[-6:])


def _launch(path: Path, *, reveal: bool) -> None:
    target = path if path.exists() else path.parent
    if sys.platform == 'win32':
        if reveal and path.is_file():
            subprocess.run(['explorer', f'/select,{path}'], check=False)
            return
        import os

        os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606
        return
    if sys.platform == 'darwin':
        if reveal and path.is_file():
            subprocess.run(['open', '-R', str(path)], check=False)
            return
        subprocess.run(['open', str(target if reveal else path)], check=False)
        return
    if reveal:
        subprocess.run(
            ['xdg-open', str(path.parent if path.is_file() else target)], check=False
        )
        return
    subprocess.run(['xdg-open', str(path)], check=False)
