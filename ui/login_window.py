from __future__ import annotations

import copy

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from dispatcher.auth import Credentials
from dispatcher.client import EmailDispatcher
from dispatcher.config import SMTPConfig, all_profiles
from dispatcher.errors import ConfigError, DispatcherError

from .settings_dialog import SettingsDialog
from .widgets import Banner, ProtocolLog, mark_invalid, run_in_background


class LoginWindow(QMainWindow):
    logged_in = pyqtSignal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Smart Email Dispatcher - Sign in")
        self.resize(560, 600)
        self._task = None

        title = QLabel("Smart Email Dispatcher")
        title.setObjectName("Title")
        subtitle = QLabel("Send email straight over SMTP, encrypted with SSL/TLS or STARTTLS.")
        subtitle.setObjectName("Subtitle")
        subtitle.setWordWrap(True)

        self.profile = QComboBox()
        self.profile.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.profile.activated.connect(self._profile_chosen)
        edit = QPushButton("Settings…")
        edit.clicked.connect(self._open_settings)
        prow = QHBoxLayout()
        prow.addWidget(self.profile, 1)
        prow.addWidget(edit)
        self.server_line = QLabel()
        self.server_line.setObjectName("Muted")

        self.email = QLineEdit()
        self.email.setPlaceholderText("you@gmail.com")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Password or app password")
        self.password.returnPressed.connect(self._login)
        self.show_pw = QCheckBox("Show")
        self.show_pw.toggled.connect(
            lambda on: self.password.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        pwrow = QHBoxLayout()
        pwrow.addWidget(self.password, 1)
        pwrow.addWidget(self.show_pw)
        self.email.textChanged.connect(lambda: mark_invalid(self.email, False))
        self.password.textChanged.connect(lambda: mark_invalid(self.password, False))

        self.login_btn = QPushButton("Log in")
        self.login_btn.setObjectName("Primary")
        self.login_btn.clicked.connect(self._login)
        gmail_tip = QLabel("Gmail: turn on 2-Step Verification, then create an "
                           "<b>App Password</b> and use it here.")
        gmail_tip.setObjectName("Muted")
        gmail_tip.setWordWrap(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.addRow("Server", prow)
        form.addRow("", self.server_line)
        form.addRow("Email", self.email)
        form.addRow("Password", pwrow)

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 20, 20, 20)
        cl.addLayout(form)
        cl.addSpacing(6)
        cl.addWidget(self.login_btn)
        cl.addWidget(gmail_tip)

        self.banner = Banner()
        self.toggle_log = QPushButton("Show protocol log")
        self.toggle_log.setObjectName("Link")
        self.toggle_log.clicked.connect(self._toggle_log)
        self.log = ProtocolLog()
        self.log.hide()

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.addWidget(title)
        lay.addWidget(subtitle)
        lay.addSpacing(10)
        lay.addWidget(card)
        lay.addWidget(self.banner)
        lay.addWidget(self.toggle_log, 0, Qt.AlignLeft)
        lay.addWidget(self.log, 1)
        lay.addStretch()
        self.setCentralWidget(root)

        self._load_profiles()

    def _load_profiles(self, select_name: str = None) -> None:
        self.profile.clear()
        for p in all_profiles():
            self.profile.addItem(p.name, p)
        idx = self.profile.findText(select_name) if select_name else 0
        self.profile.setCurrentIndex(max(idx, 0))
        self._profile_chosen()

    def _profile_chosen(self, _=None) -> None:
        self.config: SMTPConfig = copy.copy(self.profile.currentData())
        self._show_server()

    def _show_server(self) -> None:
        c = self.config
        self.server_line.setText(f"{c.host}:{c.port}  ·  {c.security.label}")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config, self)
        if dlg.exec_() and dlg.result_config():
            new = dlg.result_config()
            self._load_profiles(select_name=new.name)
            if self.profile.currentText() != new.name:
                self.profile.addItem(new.name, new)
                self.profile.setCurrentIndex(self.profile.count() - 1)
            self.config = new
            self._show_server()

    def _toggle_log(self) -> None:
        self.log.setVisible(not self.log.isVisible())
        self.toggle_log.setText("Hide protocol log" if self.log.isVisible() else "Show protocol log")

    def _set_busy(self, busy: bool) -> None:
        for w in (self.login_btn, self.email, self.password, self.profile):
            w.setEnabled(not busy)
        self.login_btn.setText("Connecting…" if busy else "Log in")

    def _login(self) -> None:
        creds = Credentials(self.email.text().strip(), self.password.text())
        try:
            creds.validate()
            self.config.validate()
        except ConfigError as e:
            mark_invalid({"email": self.email, "password": self.password}.get(e.field))
            self.banner.show_error(e)
            return

        cfg = self.config
        self._set_busy(True)
        self.banner.show_message("info", f"Connecting to {cfg.host}:{cfg.port} ({cfg.security.label})…")
        self.log.separator(f"Login {creds.username} @ {cfg.host}:{cfg.port}")
        self._pending = (cfg, creds)
        self._task = run_in_background(
            lambda log: EmailDispatcher(cfg, log=log).verify_login(creds),
            self._login_ok, self._login_failed, self.log.append)

    def _login_ok(self, _replies) -> None:
        self._set_busy(False)
        self.banner.hide()
        cfg, creds = self._pending
        self._pending = None
        self.logged_in.emit(cfg, creds)

    def _login_failed(self, err: DispatcherError) -> None:
        self._set_busy(False)
        self._pending = None
        self.banner.show_error(err)
        if err.code in (534, 535):
            mark_invalid(self.password)
            self.password.selectAll()
            self.password.setFocus()

    def reset_for_logout(self, email: str = "") -> None:
        self.password.clear()
        self.email.setText(email)
        self.banner.show_message("info", "You have been logged out.")
        self.password.setFocus()
