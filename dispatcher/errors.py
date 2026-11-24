from __future__ import annotations

from typing import Dict, Optional, Tuple


class DispatcherError(Exception):
    def __init__(
        self,
        user_message: str,
        *,
        hint: Optional[str] = None,
        code: Optional[int] = None,
        server_reply: Optional[str] = None,
    ) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.hint = hint
        self.code = code
        self.server_reply = server_reply

    def details(self) -> str:
        parts = [self.user_message]
        if self.code is not None:
            reply = f" {self.server_reply}" if self.server_reply else ""
            parts.append(f"Server reply: {self.code}{reply}")
        if self.hint:
            parts.append(f"Tip: {self.hint}")
        return "\n".join(parts)

    def __str__(self) -> str:
        return self.details()


class ConfigError(DispatcherError):
    def __init__(self, user_message: str, *, field: Optional[str] = None, **kw) -> None:
        super().__init__(user_message, **kw)
        self.field = field


class ConnectionFailed(DispatcherError):
    pass
class ConnectionTimeout(ConnectionFailed):
    pass
class SecureChannelError(DispatcherError):
    pass
class AuthenticationFailed(DispatcherError):
    pass
class NotLoggedIn(DispatcherError):
    pass
class SenderRefused(DispatcherError):
    pass
class RecipientsRefused(DispatcherError):
    def __init__(self, user_message: str, *, refused: Dict[str, Tuple[int, str]], **kw) -> None:
        super().__init__(user_message, **kw)
        self.refused = refused


class DeliveryFailed(DispatcherError):
    pass
