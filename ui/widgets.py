from __future__ import annotations

import html
from typing import Callable, Optional

from PyQt5.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from dispatcher.errors import DispatcherError


class _TaskSignals(QObject):
    log = pyqtSignal(str)
    done = pyqtSignal(object)
    failed = pyqtSignal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[Callable[[str], None]], object]):
        super().__init__()
        self.fn = fn
        self.signals = _TaskSignals()

    def run(self) -> None:
        try:
            result = self.fn(self.signals.log.emit)
        except DispatcherError as exc:
            self.signals.failed.emit(exc)
        except Exception as exc:
            self.signals.failed.emit(DispatcherError(f"Unexpected error: {exc}"))
        else:
            self.signals.done.emit(result)


def run_in_background(fn, on_done, on_failed, on_log=None) -> _Task:
    task = _Task(fn)
    task.signals.done.connect(on_done)
    task.signals.failed.connect(on_failed)
    if on_log:
        task.signals.log.connect(on_log)
    QThreadPool.globalInstance().start(task)
    return task


class Banner(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.hide()

    def show_message(self, kind: str, title: str, detail: str = "") -> None:
        body = f"<b>{html.escape(title)}</b>"
        if detail:
            body += "<br>" + html.escape(detail).replace("\n", "<br>")
        self.setText(body)
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()

    def show_error(self, err: DispatcherError) -> None:
        lines = []
        if err.code is not None:
            lines.append(f"Server reply: {err.code} {err.server_reply or ''}".rstrip())
        if err.hint:
            lines.append(f"Tip: {err.hint}")
        self.show_message("error", err.user_message, "\n".join(lines))


class ProtocolLog(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("SMTP protocol log", parent)
        self.view = QPlainTextEdit()
        self.view.setObjectName("ProtocolLog")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setFont(QFont("Consolas", 9))
        clear = QPushButton("Clear")
        clear.setObjectName("Link")
        clear.clicked.connect(self.view.clear)
        hint = QLabel("C: = sent by this app   S: = server reply   passwords are hidden")
        hint.setObjectName("Muted")
        top = QHBoxLayout()
        top.addWidget(hint)
        top.addStretch()
        top.addWidget(clear)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.view)

    def append(self, text: str) -> None:
        for line in text.splitlines():
            colour = "#94a3b8"
            if line.startswith("C:"):
                colour = "#93c5fd"
            elif line.startswith("S:"):
                code = line[3:6]
                colour = "#fca5a5" if code[:1] in ("4", "5") else "#86efac"
            self.view.appendHtml(
                f'<span style="color:{colour}; white-space:pre">{html.escape(line)}</span>')

    def separator(self, title: str) -> None:
        self.view.appendHtml(f'<span style="color:#fbbf24">--- {html.escape(title)} ---</span>')


def mark_invalid(widget: Optional[QWidget], invalid: bool = True) -> None:
    if widget is None:
        return
    widget.setProperty("invalid", "true" if invalid else "false")
    widget.style().unpolish(widget)
    widget.style().polish(widget)
