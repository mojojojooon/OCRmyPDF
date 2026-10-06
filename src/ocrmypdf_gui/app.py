# SPDX-FileCopyrightText: 2026 OCRmyPDF contributors
# SPDX-License-Identifier: MPL-2.0

"""The OCRmyPDF desktop window."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ocrmypdf_gui.core import (
    OcrResult,
    OcrSettings,
    accept_input_files,
    language_choices,
    open_file,
    parse_languages,
    reveal_in_folder,
    run_ocr_file,
    startup_warnings,
)

_STYLESHEET = """
QMainWindow, QWidget#root {
    background: #f3efe6;
    color: #1c1915;
}
QLabel#title {
    font-size: 22px;
    font-weight: 650;
}
QLabel#subtitle, QLabel#hint, QLabel#optionNote {
    color: #5c564c;
}
QFrame#dropZone {
    background: #fffdf8;
    border: 2px dashed #c3b49a;
    border-radius: 16px;
}
QFrame#dropZone[hot="true"] {
    background: #e7f2ea;
    border-color: #1f6b45;
}
QFrame#fileRow, QFrame#donePanel, QFrame#options {
    background: #fffdf8;
    border: 1px solid #e4dccb;
    border-radius: 12px;
}
QFrame#donePanel {
    background: #e7f2ea;
    border-color: #b7d7c3;
}
QLabel#notice {
    background: #fff4e5;
    color: #6a3b00;
    border: 1px solid #e2c08d;
    border-radius: 8px;
    padding: 8px 10px;
}
QLabel#rowName {
    font-weight: 600;
}
QLabel#errorText {
    color: #8a2b1b;
}
QPushButton {
    padding: 6px 12px;
    border-radius: 8px;
    border: 1px solid #d5cbb8;
    background: #fffdf8;
}
QPushButton#primary {
    background: #1f4b3a;
    color: white;
    border: none;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton#primary:hover {
    background: #17392c;
}
QProgressBar {
    border: none;
    background: #ece4d4;
    border-radius: 4px;
    max-height: 8px;
}
QProgressBar::chunk {
    background: #1f6b45;
    border-radius: 4px;
}
"""


def build_app_icon() -> QIcon:
    """Draw a simple document icon so the window is recognizable in the taskbar."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#1f4b3a'))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    painter.setPen(QColor('#f4f1ea'))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(18)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, 'OCR')
    painter.end()
    return QIcon(pixmap)


class DropZone(QFrame):
    """Large target that accepts PDF files dragged from the file manager."""

    files_dropped = Signal(list)

    def __init__(self) -> None:
        """Build the drop target and its Choose files button."""
        super().__init__()
        self.setObjectName('dropZone')
        self.setAcceptDrops(True)
        self.setMinimumHeight(150)

        self.hint = QLabel('Drop PDF files here')
        self.hint.setObjectName('title')
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail = QLabel(
            'Originals are left untouched. Each result is saved beside the original\n'
            'as name_searchable.pdf.'
        )
        detail.setObjectName('hint')
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)

        self.choose_button = QPushButton('Choose files')
        self.choose_button.setObjectName('primary')
        self.choose_button.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)
        layout.addStretch(1)
        layout.addWidget(self.hint)
        layout.addWidget(detail)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.choose_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addStretch(1)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept the drag when it carries local files."""
        if _mime_has_urls(event):
            event.acceptProposedAction()
            self._set_hot(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Keep accepting the drag while it moves over the target."""
        if _mime_has_urls(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """Clear the highlight when the drag leaves the target."""
        self._set_hot(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        """Queue the dropped local files."""
        self._set_hot(False)
        paths = _local_paths(event)
        if not paths:
            event.ignore()
            return
        self.files_dropped.emit(paths)
        event.acceptProposedAction()

    def _set_hot(self, hot: bool) -> None:
        self.setProperty('hot', hot)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class FileRow(QFrame):
    """One queued PDF: name, progress, and actions once it is finished."""

    def __init__(self, path: Path) -> None:
        """Show ``path`` as a waiting row."""
        super().__init__()
        self.setObjectName('fileRow')
        self.path = path
        self.state = 'waiting'
        self.output_path: Path | None = None

        self.name = QLabel(path.name)
        self.name.setObjectName('rowName')
        self.status = QLabel('Waiting')
        self.status.setObjectName('hint')
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.detail = QLabel('')
        self.detail.setWordWrap(True)
        self.detail.hide()
        self.open_button = QPushButton('Open')
        self.show_button = QPushButton('Show in folder')
        self.open_button.hide()
        self.show_button.hide()

        header = QHBoxLayout()
        header.addWidget(self.name, 1)
        header.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addWidget(self.open_button)
        actions.addWidget(self.show_button)
        actions.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.bar)
        layout.addWidget(self.detail)
        layout.addLayout(actions)

    def reset(self) -> None:
        """Return this row to the waiting state for another attempt."""
        self.state = 'waiting'
        self.output_path = None
        self.status.setText('Waiting')
        self.status.setObjectName('hint')
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.detail.hide()
        self.detail.setText('')
        self.open_button.hide()
        self.show_button.hide()
        self._repolish(self.status)

    def mark_running(self) -> None:
        """Show an indeterminate bar while OCR starts."""
        self.state = 'running'
        self.status.setText('Starting…')
        self.bar.setRange(0, 0)

    def update_progress(self, description: str, completed: float, total: float) -> None:
        """Refresh the bar from one OCRmyPDF progress event."""
        if self.state != 'running':
            return
        if total > 0:
            percent = max(0, min(100, int(completed / total * 100)))
            self.bar.setRange(0, 100)
            self.bar.setValue(percent)
            self.status.setText(f'{description} — {percent}%')
        else:
            self.bar.setRange(0, 0)
            self.status.setText(description or 'Working…')

    def mark_done(self, output_path: Path) -> None:
        """Show a finished searchable PDF and the buttons that open it."""
        self.state = 'done'
        self.output_path = output_path
        self.status.setText('Ready')
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.detail.setObjectName('hint')
        self.detail.setText(f'Saved {output_path.name}')
        self.detail.show()
        self.open_button.show()
        self.show_button.show()
        self._repolish(self.detail)

    def mark_failed(self, message: str) -> None:
        """Show ``message`` and stop the progress bar."""
        self.state = 'failed'
        self.status.setText('Failed')
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.detail.setObjectName('errorText')
        self.detail.setText(message)
        self.detail.show()
        self.open_button.hide()
        self.show_button.hide()
        self._repolish(self.detail)

    def _repolish(self, widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)


@dataclass
class _QueuedFile:
    path: Path
    settings: OcrSettings | None = None


class OcrJobThread(QThread):
    """Run one OCR job off the UI thread."""

    progressed = Signal(str, float, float)
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, path: Path, settings: OcrSettings) -> None:
        """Remember the file and the options to use."""
        super().__init__()
        self._path = path
        self._settings = settings

    def run(self) -> None:
        """Call OCRmyPDF and emit the outcome."""

        def on_progress(
            description: str, completed: float, total: float | None
        ) -> None:
            self.progressed.emit(
                description,
                float(completed),
                -1.0 if total is None else float(total),
            )

        result = run_ocr_file(self._path, self._settings, on_progress=on_progress)
        if result.ok and result.output_path is not None:
            self.succeeded.emit(result)
        else:
            self.failed.emit(result.code, result.message)


class MainWindow(QMainWindow):
    """Drop zone, a few OCR options, and a per-file status list."""

    def __init__(self) -> None:
        """Build the window and check that Tesseract and Ghostscript are present."""
        super().__init__()
        self.setWindowTitle('OCRmyPDF')
        self.setWindowIcon(build_app_icon())
        self.resize(760, 700)
        self.setMinimumSize(640, 560)
        self.setAcceptDrops(True)

        self._rows: dict[Path, FileRow] = {}
        self._queue: deque[_QueuedFile] = deque()
        self._thread: OcrJobThread | None = None
        self._active: Path | None = None
        self._last_output: Path | None = None

        root = QWidget()
        root.setObjectName('root')
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel('OCRmyPDF')
        title.setObjectName('title')
        subtitle = QLabel('Make a scanned PDF searchable.')
        subtitle.setObjectName('subtitle')
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.notice = QLabel()
        self.notice.setObjectName('notice')
        self.notice.setWordWrap(True)
        self.notice.hide()
        layout.addWidget(self.notice)
        self._tool_warning = '\n\n'.join(startup_warnings())
        self._set_notice('')

        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.add_paths)
        self.drop_zone.choose_button.clicked.connect(self._choose_files)
        self.choose_button = self.drop_zone.choose_button
        layout.addWidget(self.drop_zone)

        options = QFrame()
        options.setObjectName('options')
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(12, 10, 12, 10)
        language_row = QHBoxLayout()
        language_row.addWidget(QLabel('Language'))
        self.language = QComboBox()
        self.language.setEditable(True)
        self.language.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.language.setToolTip(
            'Tesseract language code. Combine languages as eng+fra.'
        )
        for code, label in language_choices():
            self.language.addItem(label, code)
        if self.language.count() == 0:
            self.language.addItem('English (eng)', 'eng')
        language_row.addWidget(self.language, 1)
        options_layout.addLayout(language_row)

        toggles = QHBoxLayout()
        self.deskew = QCheckBox('Deskew')
        self.rotate = QCheckBox('Rotate pages')
        self.skip_text = QCheckBox('Skip pages that already have text')
        self.deskew.setToolTip('Straighten pages that were scanned at an angle.')
        self.rotate.setToolTip('Turn pages that are sideways or upside down.')
        self.skip_text.setToolTip(
            'Leave pages that already contain text unchanged. '
            'Turn this off to be asked before OCR touches them.'
        )
        self.skip_text.setChecked(True)
        toggles.addWidget(self.deskew)
        toggles.addWidget(self.rotate)
        toggles.addWidget(self.skip_text)
        toggles.addStretch(1)
        options_layout.addLayout(toggles)
        note = QLabel('These options apply to each file as it starts.')
        note.setObjectName('optionNote')
        options_layout.addWidget(note)
        layout.addWidget(options)

        self.empty_list = QLabel('No files yet.')
        self.empty_list.setObjectName('hint')
        layout.addWidget(self.empty_list)

        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)
        self._rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._rows_host)
        scroll.setMinimumHeight(140)
        layout.addWidget(scroll, 1)

        self.done_panel = QFrame()
        self.done_panel.setObjectName('donePanel')
        done_layout = QHBoxLayout(self.done_panel)
        self.done_label = QLabel('')
        self.done_label.setWordWrap(True)
        self.open_button = QPushButton('Open file')
        self.open_button.setObjectName('primary')
        self.show_folder_button = QPushButton('Show in folder')
        self.open_button.clicked.connect(self._open_last)
        self.show_folder_button.clicked.connect(self._reveal_last)
        done_layout.addWidget(self.done_label, 1)
        done_layout.addWidget(self.show_folder_button)
        done_layout.addWidget(self.open_button)
        self.done_panel.hide()
        layout.addWidget(self.done_panel)

    def add_paths(self, paths: list[str] | list[Path]) -> None:
        """Validate ``paths`` and queue each PDF for OCR."""
        accepted, problems = accept_input_files(paths)
        self._set_notice('\n'.join(problems))
        for path in accepted:
            self._enqueue(path, settings=None)
        self._pump()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept file drags anywhere on the window, not only on the drop zone."""
        if _mime_has_urls(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Keep accepting a file drag while it moves across the window."""
        if _mime_has_urls(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Queue files dropped outside the drop zone."""
        paths = _local_paths(event)
        if not paths:
            event.ignore()
            return
        self.add_paths(paths)
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Ask before quitting while a file is still being processed."""
        thread = self._thread
        if thread is not None and thread.isRunning():
            answer = QMessageBox.question(
                self,
                'OCR is still running',
                'A file is still being processed. Quit anyway?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()

    def _choose_files(self) -> None:
        paths, _selected = QFileDialog.getOpenFileNames(
            self,
            'Choose scanned PDFs',
            '',
            'PDF files (*.pdf)',
        )
        if paths:
            self.add_paths(paths)

    def _enqueue(self, path: Path, settings: OcrSettings | None) -> None:
        row = self._rows.get(path)
        if row is None:
            row = FileRow(path)
            row.open_button.clicked.connect(
                lambda _checked=False, r=row: self._open_row(r)
            )
            row.show_button.clicked.connect(
                lambda _checked=False, r=row: self._reveal_row(r)
            )
            self._rows[path] = row
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
            self.empty_list.hide()
        elif row.state in {'waiting', 'running'}:
            self._set_notice(f'{path.name} is already in the list.')
            return
        else:
            row.reset()
        self._queue.append(_QueuedFile(path, settings))

    def _pump(self) -> None:
        if self._thread is not None:
            return
        if not self._queue:
            self._active = None
            return
        item = self._queue.popleft()
        row = self._rows[item.path]
        try:
            settings = (
                item.settings if item.settings is not None else self._read_settings()
            )
        except ValueError as exc:
            row.mark_failed(str(exc))
            self._pump()
            return
        row.mark_running()
        self._active = item.path
        thread = OcrJobThread(item.path, settings)
        thread.progressed.connect(
            lambda description, completed, total, r=row: r.update_progress(
                description, completed, total
            )
        )
        thread.succeeded.connect(self._on_success)
        thread.failed.connect(self._on_failure)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        thread.start()

    def _on_success(self, result: OcrResult) -> None:
        self._thread = None
        row = self._rows.get(result.input_path)
        if row is not None and result.output_path is not None:
            row.mark_done(result.output_path)
            self._last_output = result.output_path
            self._refresh_done_panel()
        self._pump()

    def _on_failure(self, code: str, message: str) -> None:
        self._thread = None
        path = self._active
        row = self._rows.get(path) if path is not None else None
        if row is None or path is None:
            self._pump()
            return
        if code in {'already_has_text', 'tagged_pdf'}:
            choice = self._ask_text_choice(path.name, tagged=code == 'tagged_pdf')
            if choice in {'skip', 'force'}:
                if choice == 'skip':
                    self.skip_text.setChecked(True)
                try:
                    retry_settings = self._settings_for_retry(choice)
                except ValueError as exc:
                    row.mark_failed(str(exc))
                    self._pump()
                    return
                row.reset()
                self._queue.appendleft(_QueuedFile(path, retry_settings))
                self._pump()
                return
        row.mark_failed(message)
        self._pump()

    def _ask_text_choice(self, filename: str, *, tagged: bool) -> str | None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle('This PDF already has text')
        if tagged:
            box.setText(f'{filename} is a tagged PDF.')
            box.setInformativeText(
                'Tagged PDFs usually already contain text. Skipping leaves those '
                'pages unchanged. Force OCR scans them again and discards their '
                'structure.'
            )
        else:
            box.setText(f'{filename} already has text.')
            box.setInformativeText(
                'It may already be searchable. Skip pages that contain text, or '
                'force OCR and replace that text by scanning the pages again.'
            )
        skip = box.addButton('Skip pages with text', QMessageBox.ButtonRole.AcceptRole)
        force = box.addButton('Force OCR', QMessageBox.ButtonRole.DestructiveRole)
        box.addButton('Cancel', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == skip:
            return 'skip'
        if clicked == force:
            return 'force'
        return None

    def _settings_for_retry(self, choice: str) -> OcrSettings:
        base = self._read_settings()
        if choice == 'skip':
            return OcrSettings(
                languages=base.languages,
                deskew=base.deskew,
                rotate_pages=base.rotate_pages,
                skip_existing_text=True,
                force_ocr=False,
            )
        return OcrSettings(
            languages=base.languages,
            deskew=base.deskew,
            rotate_pages=base.rotate_pages,
            skip_existing_text=False,
            force_ocr=True,
        )

    def _read_settings(self) -> OcrSettings:
        text = self.language.currentText().strip()
        index = self.language.findText(text)
        if index >= 0:
            stored = self.language.itemData(index)
            languages = (str(stored),) if stored else parse_languages(text)
        else:
            languages = parse_languages(text)
        return OcrSettings(
            languages=languages,
            deskew=self.deskew.isChecked(),
            rotate_pages=self.rotate.isChecked(),
            skip_existing_text=self.skip_text.isChecked(),
        )

    def _refresh_done_panel(self) -> None:
        ready = [row.output_path for row in self._rows.values() if row.output_path]
        if not ready:
            self.done_panel.hide()
            return
        last = ready[-1]
        assert last is not None
        self._last_output = last
        if len(ready) == 1:
            self.done_label.setText(f'{last.name} is ready.')
            self.open_button.setText('Open file')
        else:
            self.done_label.setText(f'{len(ready)} searchable PDFs are ready.')
            self.open_button.setText('Open last file')
        self.done_panel.show()

    def _open_last(self) -> None:
        if self._last_output is not None:
            open_file(self._last_output)

    def _reveal_last(self) -> None:
        if self._last_output is not None:
            reveal_in_folder(self._last_output)

    def _open_row(self, row: FileRow) -> None:
        if row.output_path is not None:
            open_file(row.output_path)

    def _reveal_row(self, row: FileRow) -> None:
        if row.output_path is not None:
            reveal_in_folder(row.output_path)

    def _set_notice(self, text: str) -> None:
        parts = [part for part in (self._tool_warning, text.strip()) if part]
        if parts:
            self.notice.setText('\n\n'.join(parts))
            self.notice.show()
        else:
            self.notice.hide()
            self.notice.setText('')


def _mime_has_urls(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> bool:
    mime = event.mimeData()
    return bool(mime is not None and mime.hasUrls())


def _local_paths(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> list[str]:
    mime = event.mimeData()
    if mime is None:
        return []
    return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]


def install_style(application: QApplication) -> None:
    """Apply the desktop app's theme to ``application``."""
    application.setStyle('Fusion')
    application.setStyleSheet(_STYLESHEET)


def create_window() -> MainWindow:
    """Construct the main window. The caller shows it and starts the event loop."""
    return MainWindow()
