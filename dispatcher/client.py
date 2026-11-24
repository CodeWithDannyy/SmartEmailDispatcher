from __future__ import annotations

from dataclasses import dataclass
from email.message import Message
from typing import Iterable, List, Optional

from .auth import Credentials
from .config import SMTPConfig
from .session import LogFn, SendResult, SMTPReply, SMTPSession, TLSInfo


@dataclass
class ConnectionReport:
    host: str
    port: int
    tls: Optional[TLSInfo]
    extensions: List[str]
    auth_methods: List[str]
    max_message_size: Optional[int]
    replies: List[SMTPReply]

    def summary(self) -> str:
        size = f"{self.max_message_size / 1048576:.0f} MB" if self.max_message_size else "not stated"
        return (f"Connected to {self.host}:{self.port}\n"
                f"Encryption: {self.tls}\n"
                f"Login methods: {', '.join(self.auth_methods) or 'none offered'}\n"
                f"Max message size: {size}")


class EmailDispatcher:
    def __init__(self, config: SMTPConfig, log: Optional[LogFn] = None) -> None:
        self.config = config
        self.log = log

    def _session(self) -> SMTPSession:
        return SMTPSession(self.config, log=self.log)

    def test_connection(self) -> ConnectionReport:
        with self._session() as s:
            s.connect()
            feats = s.server_features
            return ConnectionReport(
                self.config.host, self.config.port, s.tls,
                extensions=sorted(feats),
                auth_methods=feats.get("auth", "").split(),
                max_message_size=s.max_message_size,
                replies=list(s.replies),
            )

    def verify_login(self, credentials: Credentials) -> List[SMTPReply]:
        credentials.validate()
        with self._session() as s:
            s.connect()
            s.login(credentials)
            return list(s.replies)

    def send(
        self,
        credentials: Credentials,
        message: Message,
        *,
        sender: Optional[str] = None,
        recipients: Optional[Iterable[str]] = None,
    ) -> SendResult:
        credentials.validate()
        with self._session() as s:
            s.connect()
            s.login(credentials)
            return s.send_message(message, sender=sender, recipients=recipients)
