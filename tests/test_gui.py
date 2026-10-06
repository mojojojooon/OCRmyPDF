# SPDX-FileCopyrightText: 2026 OCRmyPDF contributors
# SPDX-License-Identifier: MPL-2.0

"""Tests for the desktop OCR window and its worker."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ocrmypdf.exceptions import (
    EncryptedPdfError,
    MissingDependencyError,
    PriorOcrFoundError,
    TaggedPDFError,
)
from ocrmypdf_gui.core import (
    OcrSettings,
    accept_input_files,
    explain_failure,
    parse_languages,
    run_ocr_file,
    searchable_output_path,
)
from ocrmypdf_gui.progress import CallbackProgressBar, bind_progress

RESOURCES = Path(__file__).parent / 'resources'


def test_output_name_sits_beside_input_and_does_not_clobber(tmp_path: Path):
    source = tmp_path / 'scan.pdf'
    source.write_bytes(b'%PDF-1.4')
    first = searchable_output_path(source)
    assert first == tmp_path / 'scan_searchable.pdf'
    assert first != source
    first.write_bytes(b'already')
    second = searchable_output_path(source)
    assert second == tmp_path / 'scan_searchable_2.pdf'
    assert second.resolve() != source.resolve()


def test_accept_input_files_keeps_pdfs_only(tmp_path: Path):
    pdf = tmp_path / 'notes.PDF'
    pdf.write_bytes(b'%PDF')
    text = tmp_path / 'notes.txt'
    text.write_text('hello', encoding='utf-8')
    folder = tmp_path / 'scans'
    folder.mkdir()
    missing = tmp_path / 'gone.pdf'
    accepted, problems = accept_input_files([pdf, text, folder, missing])
    assert accepted == [pdf.resolve()]
    assert any('not a PDF' in problem for problem in problems)
    assert any('folder' in problem for problem in problems)
    assert any('Could not find' in problem for problem in problems)


def test_parse_languages():
    assert parse_languages('eng') == ('eng',)
    assert parse_languages('eng+fra') == ('eng', 'fra')
    assert parse_languages('eng, fra') == ('eng', 'fra')
    assert parse_languages('English') == ('eng',)
    assert parse_languages('English (eng)') == ('eng',)
    assert parse_languages('Chinese, simplified (chi_sim)') == ('chi_sim',)
    with pytest.raises(ValueError):
        parse_languages('')
    with pytest.raises(ValueError):
        parse_languages('not a language')


def test_settings_skip_text_by_default_and_force_wins():
    default = OcrSettings().as_ocr_kwargs()
    assert default['mode'] == 'skip'
    assert default['language'] == ['eng']
    assert default['deskew'] is False
    assert default['rotate_pages'] is False
    assert default['plugins'] == ['ocrmypdf_gui.progress']

    forced = OcrSettings(
        languages=('deu', 'eng'),
        deskew=True,
        rotate_pages=True,
        skip_existing_text=True,
        force_ocr=True,
    ).as_ocr_kwargs()
    assert forced['mode'] == 'force'
    assert forced['language'] == ['deu', 'eng']
    assert forced['deskew'] is True
    assert forced['rotate_pages'] is True


def test_explain_existing_text_and_missing_programs():
    code, message = explain_failure(PriorOcrFoundError('page 1 already has text'))
    assert code == 'already_has_text'
    assert 'already has text' in message.lower()
    assert 'skip' in message.lower()
    assert 'force' in message.lower()

    code, message = explain_failure(TaggedPDFError())
    assert code == 'tagged_pdf'
    assert 'tagged' in message.lower()

    code, message = explain_failure(MissingDependencyError('tesseract'))
    assert code == 'missing_tesseract'
    assert 'Tesseract' in message
    assert 'install' in message.lower()

    code, message = explain_failure(MissingDependencyError('gs'))
    assert code == 'missing_ghostscript'
    assert 'Ghostscript' in message

    code, message = explain_failure(
        MissingDependencyError(
            'OCR engine does not have language data for the following languages: xyz'
        )
    )
    assert code == 'missing_language'
    assert 'language' in message.lower()

    code, message = explain_failure(EncryptedPdfError())
    assert code == 'encrypted'
    assert 'password' in message.lower()


def test_progress_callback_receives_page_updates():
    seen: list[tuple[str, float, float | None]] = []

    def record(description: str, completed: float, total: float | None) -> None:
        seen.append((description, completed, total))

    with bind_progress(record):
        bar = CallbackProgressBar(total=2, desc='OCR', unit='page')
        with bar as entered:
            assert entered is bar
            bar.update(1)
            bar.update(1)
    assert seen[0] == ('OCR', 0.0, 2.0)
    assert seen[-1] == ('OCR', 2.0, 2.0)

    with bind_progress(None):
        silent = CallbackProgressBar(total=1, desc='OCR', unit='page', disable=True)
        with silent:
            silent.update(1)
    assert seen[-1] == ('OCR', 2.0, 2.0)


def _tools_available() -> bool:
    from ocrmypdf._exec import ghostscript, tesseract

    return bool(tesseract.available() and ghostscript.available())


@pytest.mark.skipif(
    not (RESOURCES / 'graph_ocred.pdf').is_file(), reason='sample PDF missing'
)
def test_worker_reports_pdf_that_already_has_text(tmp_path: Path):
    if not _tools_available():
        pytest.skip('Tesseract and Ghostscript are required')
    source = tmp_path / 'already.pdf'
    shutil.copy(RESOURCES / 'graph_ocred.pdf', source)
    result = run_ocr_file(source, OcrSettings(skip_existing_text=False))
    assert result.ok is False
    assert result.code == 'already_has_text'
    assert result.output_path is None
    assert not (tmp_path / 'already_searchable.pdf').exists()
    assert source.stat().st_size == (RESOURCES / 'graph_ocred.pdf').stat().st_size


@pytest.mark.skipif(
    not (RESOURCES / 'ccitt.pdf').is_file(), reason='sample PDF missing'
)
def test_worker_writes_searchable_pdf(tmp_path: Path):
    if not _tools_available():
        pytest.skip('Tesseract and Ghostscript are required')
    source = tmp_path / 'notes.pdf'
    shutil.copy(RESOURCES / 'ccitt.pdf', source)
    original = source.read_bytes()
    updates: list[tuple[str, float, float | None]] = []
    result = run_ocr_file(
        source,
        OcrSettings(),
        on_progress=lambda description, completed, total: updates.append(
            (description, completed, total)
        ),
    )
    assert result.ok, result.message
    assert result.output_path == tmp_path / 'notes_searchable.pdf'
    assert result.output_path.is_file()
    assert result.output_path.stat().st_size > 100
    assert source.read_bytes() == original
    from pdfminer.high_level import extract_text

    text = extract_text(str(result.output_path))
    assert 'the' in text.lower()
    assert updates


def test_help_does_not_need_a_display():
    from ocrmypdf_gui.__main__ import main

    assert main(['--help']) == 0


def test_window_opens_offscreen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip('PySide6')
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QMimeData, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication

    from ocrmypdf_gui.app import MainWindow

    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    application.processEvents()
    assert window.windowTitle() == 'OCRmyPDF'
    assert window.skip_text.isChecked()
    assert window.language.currentData() == 'eng'
    assert 'Drop PDF' in window.drop_zone.hint.text()

    notes = tmp_path / 'notes.txt'
    notes.write_text('not a pdf', encoding='utf-8')
    window.add_paths([str(notes)])
    application.processEvents()
    assert window._thread is None
    assert 'not a PDF' in window.notice.text()

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(notes))])
    event = QDropEvent(
        window.drop_zone.rect().center(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.drop_zone.dropEvent(event)
    application.processEvents()
    assert 'not a PDF' in window.notice.text()
    window.close()
