from __future__ import annotations

import os
from email.message import EmailMessage
from typing import List, Tuple

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from dispatcher import message_builder, reply_codes
from dispatcher.auth import Credentials
from dispatcher.client import EmailDispatcher
from dispatcher.config import SMTPConfig
from dispatcher.errors import ConfigError, DispatcherError
from dispatcher.message_builder import Draft
from dispatcher.session import SendResult

from .widgets import Banner, ProtocolLog, mark_invalid, run_in_background


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class ComposeWindow(QMainWindow):
    logged_out = pyqtSignal(str)

    def __init__(self, config: SMTPConfig, credentials: Credentials, parent=None):
        super().__init__(parent)
        self.config = config
        self.credentials = credentials
        self._task = None
        self.setWindowTitle(f"Smart Email Dispatcher - {credentials.username}")
        self.resize(1100, 720)

        who = QLabel(f"<b>{credentials.username}</b>  ·  {config.host}:{config.port}  ·  "
                     f"{config.security.label}")
        logout = QPushButton("Log out")
        logout.clicked.connect(self._logout)
        header = QHBoxLayout()
        header.addWidget(who)
        header.addStretch()
        header.addWidget(logout)

        self.from_ = QLineEdit(credentials.username)
        self.from_.setReadOnly(True)
        self.to = QLineEdit()
        self.to.setPlaceholderText("name@example.com, another@example.com")
        self.cc = QLineEdit()
        self.cc.setPlaceholderText("optional")
        self.subject = QLineEdit()
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText("Write your message…")
        for w in (self.to, self.cc, self.subject):
            w.textChanged.connect(lambda _=None, w=w: mark_invalid(w, False))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.addRow("From", self.from_)
        form.addRow("To", self.to)
        form.addRow("Cc", self.cc)
        form.addRow("Subject", self.subject)

        self.attachments = QListWidget()
        self.attachments.setMaximumHeight(72)
        add = QPushButton("Attach files…")
        add.clicked.connect(self._add_files)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_selected)
        self.attach_total = QLabel()
        self.attach_total.setObjectName("Muted")
        arow = QHBoxLayout()
        arow.addWidget(add)
        arow.addWidget(remove)
        arow.addWidget(self.attach_total)
        arow.addStretch()

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("Primary")
        self.send_btn.clicked.connect(self._send)
        self.send_btn.setShortcut("Ctrl+Return")
        clear = QPushButton("New message")
        clear.clicked.connect(self._clear)
        brow = QHBoxLayout()
        brow.addWidget(clear)
        brow.addStretch()
        brow.addWidget(QLabel("Ctrl+Enter to send"))
        brow.addWidget(self.send_btn)

        self.banner = Banner()

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.addLayout(form)
        cl.addWidget(self.body, 1)
        cl.addWidget(QLabel("Attachments"))
        cl.addWidget(self.attachments)
        cl.addLayout(arow)
        cl.addWidget(self.banner)
        cl.addLayout(brow)

        self.log = ProtocolLog()

        split = QSplitter(Qt.Horizontal)
        split.addWidget(card)
        split.addWidget(self.log)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([640, 420])

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.addLayout(header)
        lay.addWidget(split, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Logged in. Ready to send.")
        self._update_attach_total()
        self.to.setFocus()

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Attach files")
        existing = set(self.attachment_paths())
        for p in paths:
            if p in existing:
                continue
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            item = QListWidgetItem(f"{os.path.basename(p)}   ({_human_size(size)})")
            item.setData(Qt.UserRole, p)
            item.setToolTip(p)
            self.attachments.addItem(item)
        self._update_attach_total()

    def _remove_selected(self) -> None:
        for item in self.attachments.selectedItems():
            self.attachments.takeItem(self.attachments.row(item))
        self._update_attach_total()

    def attachment_paths(self) -> List[str]:
        return [self.attachments.item(i).data(Qt.UserRole) for i in range(self.attachments.count())]

    def _update_attach_total(self) -> None:
        paths = self.attachment_paths()
        total = sum(os.path.getsize(p) for p in paths if os.path.exists(p))
        self.attach_total.setText(f"{len(paths)} file(s), {_human_size(total)}" if paths else "No files attached")

    def _draft(self) -> Draft:
        return Draft(
            sender=self.credentials.username,
            to=self.to.text(),
            cc=self.cc.text(),
            subject=self.subject.text(),
            body=self.body.toPlainText(),
            attachments=self.attachment_paths(),
        )

    def _build_message(self, draft: Draft) -> Tuple[EmailMessage, List[str]]:
        return message_builder.build_message(draft), []

    def _describe_result(self, result: SendResult) -> str:
        return reply_codes.summarise_result(result)

    def _send(self) -> None:
        if self._task is not None:
            return
        for w in (self.to, self.cc, self.subject):
            mark_invalid(w, False)
        mark_invalid(self.attachments, False)

        draft = self._draft()
        try:
            msg, warnings = self._build_message(draft)
        except ConfigError as e:
            mark_invalid({"to": self.to, "cc": self.cc, "subject": self.subject,
                          "attachments": self.attachments}.get(e.field))
            self.banner.show_error(e)
            return

        if warnings and draft.attachments:
            ok = QMessageBox.question(
                self, "Attachments won't be sent",
                warnings[0] + "\n\nSend the text-only message anyway?") == QMessageBox.Yes
            if not ok:
                return
        if not draft.subject.strip():
            if QMessageBox.question(self, "No subject", "Send without a subject?") != QMessageBox.Yes:
                return

        self._warnings = warnings
        self._set_busy(True)
        cfg, creds = self.config, self.credentials
        self.banner.show_message("info", f"Sending via {cfg.host}…")
        self.log.separator(f"Send: {draft.subject or '(no subject)'}")
        self._task = run_in_background(
            lambda log: EmailDispatcher(cfg, log=log).send(creds, msg),
            self._sent, self._send_failed, self.log.append)

    def _set_busy(self, busy: bool) -> None:
        self.send_btn.setEnabled(not busy)
        self.send_btn.setText("Sending…" if busy else "Send")
        self.statusBar().showMessage("Sending…" if busy else "Ready.")

    def _sent(self, result: SendResult) -> None:
        self._task = None
        self._set_busy(False)
        text = self._describe_result(result)
        if self._warnings:
            text += "\n" + "\n".join(self._warnings)
        if result.fully_delivered:
            self.banner.show_message("warn" if self._warnings else "ok", "Email sent.", text)
            self.statusBar().showMessage(f"Sent to {len(result.accepted)} recipient(s).")
            self._clear(keep_banner=True)
        else:
            self.banner.show_message("warn", "Sent, but some recipients were refused.", text)
            mark_invalid(self.to)

    def _send_failed(self, err: DispatcherError) -> None:
        self._task = None
        self._set_busy(False)
        self.banner.show_error(err)
        self.statusBar().showMessage("Not sent.")
        if getattr(err, "refused", None):
            mark_invalid(self.to)

    def _clear(self, keep_banner: bool = False) -> None:
        for w in (self.to, self.cc, self.subject):
            w.clear()
        self.body.clear()
        self.attachments.clear()
        self._update_attach_total()
        if not keep_banner:
            self.banner.hide()
        self.to.setFocus()

    def _logout(self) -> None:
        self.credentials = None
        self.logged_out.emit(self.from_.text())
        self.close()
