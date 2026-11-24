from .auth import Credentials
from .client import ConnectionReport, EmailDispatcher
from .config import SecurityMode, SMTPConfig, all_profiles, presets, save_profile
from .errors import (
    AuthenticationFailed, ConfigError, ConnectionFailed, ConnectionTimeout,
    DeliveryFailed, DispatcherError, NotLoggedIn, RecipientsRefused,
    SecureChannelError, SenderRefused,
)
from .session import SendResult, SMTPReply, SMTPSession, TLSInfo

__all__ = [
    "Credentials", "EmailDispatcher", "ConnectionReport", "SecurityMode", "SMTPConfig",
    "all_profiles", "presets", "save_profile", "SendResult", "SMTPReply", "SMTPSession",
    "TLSInfo", "DispatcherError", "ConfigError", "ConnectionFailed", "ConnectionTimeout",
    "SecureChannelError", "AuthenticationFailed", "NotLoggedIn", "SenderRefused",
    "RecipientsRefused", "DeliveryFailed",
]
