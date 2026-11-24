from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from .errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_TEST_CA = PROJECT_ROOT / "test_server" / "certs" / "ca.crt"


class SecurityMode(str, Enum):
    SSL = "ssl"
    STARTTLS = "starttls"

    @property
    def label(self) -> str:
        return {"ssl": "SSL/TLS (implicit)", "starttls": "STARTTLS"}[self.value]

    @property
    def usual_port(self) -> int:
        return 465 if self is SecurityMode.SSL else 587


@dataclass
class SMTPConfig:
    name: str = "Custom"
    host: str = ""
    port: int = 587
    security: SecurityMode = SecurityMode.STARTTLS
    timeout: float = 20.0
    verify_certificate: bool = True
    ca_file: Optional[str] = None

    def validate(self) -> List[str]:
        host = (self.host or "").strip()
        if not host:
            raise ConfigError("Enter the SMTP server address.", field="host")
        if "://" in host or "/" in host:
            raise ConfigError(
                "Enter just the server name, without smtp:// or slashes.",
                field="host", hint="Example: smtp.gmail.com",
            )
        if not _is_valid_host(host):
            raise ConfigError(f"'{host}' is not a valid host name or IP address.", field="host")

        if not isinstance(self.port, int) or isinstance(self.port, bool):
            raise ConfigError("Port must be a whole number.", field="port")
        if not 1 <= self.port <= 65535:
            raise ConfigError("Port must be between 1 and 65535.", field="port")

        if not isinstance(self.security, SecurityMode):
            raise ConfigError("Choose SSL/TLS or STARTTLS.", field="security")

        if not 1 <= float(self.timeout) <= 300:
            raise ConfigError("Timeout must be between 1 and 300 seconds.", field="timeout")

        if self.ca_file and not Path(self.ca_file).is_file():
            hint = None
            if Path(self.ca_file).resolve() == LOCAL_TEST_CA.resolve():
                hint = "Start the local test server once (python test_server/local_smtp_server.py); it creates this file."
            raise ConfigError(f"CA certificate file not found: {self.ca_file}", field="ca_file", hint=hint)

        warnings: List[str] = []
        if self.security is SecurityMode.SSL and self.port == 587:
            warnings.append("Port 587 normally uses STARTTLS, not SSL/TLS. The connection will probably fail.")
        if self.security is SecurityMode.STARTTLS and self.port == 465:
            warnings.append("Port 465 normally uses SSL/TLS, not STARTTLS. The connection will probably time out.")
        if self.port == 25:
            warnings.append("Port 25 is often blocked by ISPs and campus networks; prefer 587 or 465.")
        if not self.verify_certificate:
            warnings.append("Certificate checking is OFF: the connection is encrypted but the server is not verified.")
        return warnings

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["security"] = self.security.value
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "SMTPConfig":
        d = dict(d)
        d["security"] = SecurityMode(d.get("security", "starttls"))
        d["port"] = int(d.get("port", 587))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


_HOST_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def _is_valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if len(host) > 253:
        return False
    return all(_HOST_LABEL.match(part) for part in host.rstrip(".").split("."))


def presets() -> List[SMTPConfig]:
    return [
        SMTPConfig("Gmail (SSL 465)", "smtp.gmail.com", 465, SecurityMode.SSL),
        SMTPConfig("Gmail (STARTTLS 587)", "smtp.gmail.com", 587, SecurityMode.STARTTLS),
        SMTPConfig("Outlook / Microsoft 365", "smtp.office365.com", 587, SecurityMode.STARTTLS),
        SMTPConfig("Yahoo Mail", "smtp.mail.yahoo.com", 465, SecurityMode.SSL),
        SMTPConfig("Local test server (STARTTLS)", "localhost", 2525, SecurityMode.STARTTLS,
                   timeout=10, ca_file=str(LOCAL_TEST_CA)),
        SMTPConfig("Local test server (SSL)", "localhost", 4650, SecurityMode.SSL,
                   timeout=10, ca_file=str(LOCAL_TEST_CA)),
    ]


def _profiles_path() -> Path:
    base = os.environ.get("SED_CONFIG_DIR") or (Path.home() / ".smart_email_dispatcher")
    return Path(base) / "profiles.json"


def load_saved_profiles() -> List[SMTPConfig]:
    path = _profiles_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [SMTPConfig.from_dict(d) for d in data]
    except (OSError, ValueError, TypeError, KeyError):
        return []


def save_profile(config: SMTPConfig) -> None:
    config.validate()
    profiles = [p for p in load_saved_profiles() if p.name != config.name]
    profiles.append(config)
    path = _profiles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([p.to_dict() for p in profiles], indent=2), encoding="utf-8")


def delete_profile(name: str) -> None:
    profiles = [p for p in load_saved_profiles() if p.name != name]
    path = _profiles_path()
    if path.exists():
        path.write_text(json.dumps([p.to_dict() for p in profiles], indent=2), encoding="utf-8")


def all_profiles() -> List[SMTPConfig]:
    saved = load_saved_profiles()
    names = {p.name for p in saved}
    return saved + [p for p in presets() if p.name not in names]
