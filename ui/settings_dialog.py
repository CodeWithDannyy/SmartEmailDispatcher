from __future__ import annotations

import copy
from typing import Optional

from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from dispatcher.client import EmailDispatcher
from dispatcher.config import SecurityMode, SMTPConfig, presets, save_profile
from dispatcher.errors import ConfigError, DispatcherError

from .widgets import Banner, ProtocolLog, mark_invalid, run_in_background


class SettingsDialog(QDialog):
    def __init__(self, config: SMTPConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SMTP server settings")
        self.setMinimumWidth(560)
        self._task = None
        self._result: Optional[SMTPConfig] = None

        self.preset = QComboBox()
        self.preset.addItem("Load a preset…")
        for p in presets():
            self.preset.addItem(p.name, p)
        self.preset.activated.connect(self._load_preset)

        self.name = QLineEdit()
        self.host = QLineEdit()
        self.host.setPlaceholderText("smtp.gmail.com")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.security = QComboBox()
        for mode in SecurityMode:
            self.security.addItem(mode.label, mode)
        self.security.activated.connect(self._security_changed)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(1, 300)
        self.timeout.setSuffix(" s")
        self.timeout.setDecimals(0)
        self.verify = QCheckBox("Verify the server's certificate (recommended)")
        self.ca_file = QLineEdit()
        self.ca_file.setPlaceholderText("Only for the local test server / private servers")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_ca)
        ca_row = QHBoxLayout()
        ca_row.addWidget(self.ca_file)
        ca_row.addWidget(browse)

        for w in (self.host, self.name, self.ca_file):
            w.textChanged.connect(self._refresh_warnings)
        self.port.valueChanged.connect(self._refresh_warnings)
        self.verify.toggled.connect(self._refresh_warnings)

        form = QFormLayout()
        form.addRow("Preset", self.preset)
        form.addRow("Profile name", self.name)
        form.addRow("SMTP server", self.host)
        form.addRow("Port", self.port)
        form.addRow("Security", self.security)
        form.addRow("Timeout", self.timeout)
        form.addRow("", self.verify)
        form.addRow("Extra CA file", ca_row)

        card = QFrame()
        card.setObjectName("Card")
        card.setLayout(form)

        self.warnings = QLabel()
        self.warnings.setObjectName("Muted")
        self.warnings.setWordWrap(True)
        self.banner = Banner()
        self.log = ProtocolLog()
        self.log.setMinimumHeight(170)
        self.log.hide()

        self.test_btn = QPushButton("Test connection")
        self.test_btn.clicked.connect(self._test)
        self.save_btn = QPushButton("Save as profile")
        self.save_btn.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok_btn = QPushButton("Use these settings")
        self.ok_btn.setObjectName("Primary")
        self.ok_btn.clicked.connect(self._accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.test_btn)
        buttons.addWidget(self.save_btn)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok_btn)

        lay = QVBoxLayout(self)
        lay.addWidget(card)
        lay.addWidget(self.warnings)
        lay.addWidget(self.banner)
        lay.addWidget(self.log)
        lay.addLayout(buttons)

        self._fill(config)

    def _fill(self, c: SMTPConfig) -> None:
        self.name.setText(c.name)
        self.host.setText(c.host)
        self.port.setValue(int(c.port))
        self.security.setCurrentIndex(self.security.findData(c.security))
        self.timeout.setValue(float(c.timeout))
        self.verify.setChecked(c.verify_certificate)
        self.ca_file.setText(c.ca_file or "")
        self._refresh_warnings()

    def current_config(self) -> SMTPConfig:
        return SMTPConfig(
            name=self.name.text().strip() or "Custom",
            host=self.host.text().strip(),
            port=self.port.value(),
            security=self.security.currentData(),
            timeout=self.timeout.value(),
            verify_certificate=self.verify.isChecked(),
            ca_file=self.ca_file.text().strip() or None,
        )

    def result_config(self) -> Optional[SMTPConfig]:
        return self._result

    def _load_preset(self, index: int) -> None:
        p = self.preset.itemData(index)
        if p is not None:
            self._fill(copy.copy(p))
        self.preset.setCurrentIndex(0)

    def _security_changed(self, _=None) -> None:
        mode = self.security.currentData()
        if self.port.value() in (465, 587):
            self.port.setValue(mode.usual_port)
        self._refresh_warnings()

    def _browse_ca(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose CA certificate", "",
                                              "Certificates (*.crt *.pem *.cer);;All files (*)")
        if path:
            self.ca_file.setText(path)

    def _validate(self) -> Optional[SMTPConfig]:
        for w in (self.host, self.port, self.ca_file):
            mark_invalid(w, False)
        cfg = self.current_config()
        try:
            cfg.validate()
        except ConfigError as e:
            mark_invalid({"host": self.host, "port": self.port, "ca_file": self.ca_file}.get(e.field))
            self.banner.show_error(e)
            return None
        return cfg

    def _refresh_warnings(self, *_):
        try:
            warns = self.current_config().validate()
        except ConfigError:
            warns = []
        self.warnings.setText("\n".join("⚠ " + w for w in warns))
        self.warnings.setVisible(bool(warns))

    def _test(self) -> None:
        cfg = self._validate()
        if not cfg:
            return
        self.banner.show_message("info", f"Connecting to {cfg.host}:{cfg.port}…")
        self.test_btn.setEnabled(False)
        self.log.show()
        self.log.separator(f"Test connection {cfg.host}:{cfg.port} ({cfg.security.label})")
        self._task = run_in_background(
            lambda log: EmailDispatcher(cfg, log=log).test_connection(),
            self._test_ok, self._test_failed, self.log.append)

    def _test_ok(self, report) -> None:
        self.test_btn.setEnabled(True)
        self.banner.show_message("ok", "Connection works. No password was sent.", report.summary())

    def _test_failed(self, err: DispatcherError) -> None:
        self.test_btn.setEnabled(True)
        self.banner.show_error(err)

    def _save(self) -> None:
        cfg = self._validate()
        if not cfg:
            return
        try:
            save_profile(cfg)
        except (OSError, ConfigError) as e:
            self.banner.show_message("error", "Couldn't save the profile.", str(e))
            return
        self.banner.show_message("ok", f"Saved profile “{cfg.name}”. (Passwords are never saved.)")

    def _accept(self) -> None:
        cfg = self._validate()
        if cfg:
            self._result = cfg
            self.accept()
