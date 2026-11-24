from __future__ import annotations

import ast
import copy
import email.generator
import io
import smtplib
import socket
import ssl
from dataclasses import dataclass, field
from email.message import Message
from email.utils import getaddresses
from typing import Callable, Dict, Iterable, List, Optional

from .auth import Credentials
from .config import SecurityMode, SMTPConfig
from .errors import (
    AuthenticationFailed, ConfigError, ConnectionFailed, ConnectionTimeout,
    DeliveryFailed, DispatcherError, NotLoggedIn, RecipientsRefused,
    SecureChannelError, SenderRefused,
)

LogFn = Callable[[str], None]


@dataclass
class SMTPReply:
    stage: str
    code: int
    message: str

    @property
    def is_success(self) -> bool:
        return 200 <= self.code < 400

    def __str__(self) -> str:
        return f"{self.stage}: {self.code} {self.message}"


@dataclass
class SendResult:
    sender: str
    accepted: List[str]
    refused: Dict[str, SMTPReply]
    replies: List[SMTPReply]
    size_bytes: int

    @property
    def fully_delivered(self) -> bool:
        return not self.refused

    @property
    def final_reply(self) -> SMTPReply:
        return self.replies[-1]


@dataclass
class TLSInfo:
    version: str
    cipher: str
    verified: bool

    def __str__(self) -> str:
        v = "certificate verified" if self.verified else "certificate NOT verified"
        return f"{self.version}, {self.cipher}, {v}"


def make_ssl_context(config: SMTPConfig) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=config.ca_file or None)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if not config.verify_certificate:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class _ProtocolLogMixin:
    _log_fn: Optional[LogFn] = None
    _hide_sends: bool = False

    def _print_debug(self, *args):
        if self._log_fn is None or not args:
            return
        try:
            line = _format_debug_line(str(args[0]), args[1:], self._hide_sends)
        except Exception:
            line = None
        if line:
            self._log_fn(line)


def _literal(value) -> str:
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _format_debug_line(tag: str, rest: tuple, hide: bool) -> Optional[str]:
    if tag == "send:":
        text = _literal(rest[0]) if rest else ""
        if hide:
            if text.upper().startswith("AUTH"):
                return "C: " + " ".join(text.split()[:2]) + " ********  (credentials hidden)"
            return "C: ********  (credentials hidden)"
        if text.count("\n") > 1 or len(text) > 300:
            return f"C: [message content, {len(text.encode('utf-8', 'replace')):,} bytes]\nC: ."
        return "C: " + text.rstrip("\r\n")
    if tag == "reply:":
        return "S: " + (_literal(rest[0]).rstrip("\r\n") if rest else "")
    if tag == "connect: to" and rest:
        host, port = rest[0]
        return f"* Opening TCP connection to {host}:{port}"
    return None


class _LoggedSMTP(_ProtocolLogMixin, smtplib.SMTP):
    pass


class _LoggedSMTP_SSL(_ProtocolLogMixin, smtplib.SMTP_SSL):
    pass


def _text(raw) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace").strip()
    return str(raw or "").strip()


def _is_loopback(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1")


def envelope_recipients(msg: Message) -> List[str]:
    fields = []
    for header in ("To", "Cc", "Bcc"):
        fields.extend(str(v) for v in msg.get_all(header, []))
    seen, out = set(), []
    for _, addr in getaddresses(fields):
        key = addr.lower()
        if addr and key not in seen:
            seen.add(key)
            out.append(addr)
    return out


def flatten_message(msg: Message) -> bytes:
    msg_copy = copy.copy(msg)
    del msg_copy["Bcc"]
    del msg_copy["Resent-Bcc"]
    with io.BytesIO() as buf:
        email.generator.BytesGenerator(buf, mangle_from_=False).flatten(msg_copy, linesep="\r\n")
        return buf.getvalue()


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def translate_error(exc: BaseException, stage: str, config: SMTPConfig) -> DispatcherError:
    if isinstance(exc, DispatcherError):
        return exc

    where = f"{config.host}:{config.port}"
    mode_hint = None
    if config.security is SecurityMode.SSL and config.port != 465:
        mode_hint = f"Port {config.port} may expect STARTTLS. Switch to STARTTLS, or use SSL/TLS on port 465."
    elif config.security is SecurityMode.STARTTLS and config.port == 465:
        mode_hint = "Port 465 expects SSL/TLS mode, not STARTTLS. Switch the security mode to SSL/TLS."

    if isinstance(exc, ssl.SSLCertVerificationError):
        hint = ("For the local test server, the profile's CA file must point to test_server/certs/ca.crt."
                if _is_loopback(config.host) else
                "Check the server name is spelled exactly right; the certificate must match it.")
        return SecureChannelError(
            f"The server's certificate could not be verified ({exc.verify_message}).", hint=hint)
    if isinstance(exc, ssl.SSLError):
        reason = getattr(exc, "reason", None) or str(exc)
        return SecureChannelError(
            f"The secure (TLS) connection failed during {stage}: {reason}.",
            hint=mode_hint or "The server may not support TLS 1.2 or newer, or the security mode is wrong.")

    if isinstance(exc, smtplib.SMTPServerDisconnected):
        if stage == "sending":
            return DeliveryFailed(
                "The server closed the connection while sending. The email may not have been delivered.")
        return ConnectionFailed(f"{where} closed the connection unexpectedly during {stage}.",
                                hint=mode_hint or "The server may be overloaded or the security mode may be wrong.")
    if isinstance(exc, smtplib.SMTPConnectError):
        return ConnectionFailed("The server refused to start an SMTP session.",
                                code=exc.smtp_code, server_reply=_text(exc.smtp_error),
                                hint="The server may be busy, or it may be blocking your network. Try again later.")
    if isinstance(exc, smtplib.SMTPHeloError):
        return ConnectionFailed("The server rejected the EHLO greeting.",
                                code=exc.smtp_code, server_reply=_text(exc.smtp_error))
    if isinstance(exc, smtplib.SMTPDataError):
        return DeliveryFailed("The server refused to accept the message content.",
                              code=exc.smtp_code, server_reply=_text(exc.smtp_error),
                              hint="It may be too large, look like spam, or break the server's policy.")
    if isinstance(exc, smtplib.SMTPResponseException):
        if stage == "STARTTLS":
            return SecureChannelError("The server refused to start TLS (STARTTLS).",
                                      code=exc.smtp_code, server_reply=_text(exc.smtp_error))
        return DispatcherError(f"Unexpected server reply during {stage}.",
                               code=exc.smtp_code, server_reply=_text(exc.smtp_error))

    if isinstance(exc, (socket.timeout, TimeoutError)):
        return ConnectionTimeout(
            f"{where} did not respond within {config.timeout:g} seconds.",
            hint=mode_hint or "Check the host and port, and that your network allows outgoing SMTP "
                              "(some Wi-Fi networks block ports 465/587).")
    if isinstance(exc, socket.gaierror):
        return ConnectionFailed(f"Couldn't find the server '{config.host}' (DNS lookup failed).",
                                hint="Check the spelling of the server name and your internet connection.")
    if isinstance(exc, ConnectionRefusedError):
        hint = ("Start the local test server first: python test_server/local_smtp_server.py"
                if _is_loopback(config.host) else
                "Nothing is accepting connections on that port. Check the port number.")
        return ConnectionFailed(f"{where} refused the connection.", hint=hint)
    if isinstance(exc, OSError):
        return ConnectionFailed(f"Network error while contacting {where}: {exc.strerror or exc}.",
                                hint="Check your internet connection.")
    return DispatcherError(f"Unexpected error during {stage}: {exc}")


def _auth_error(exc: smtplib.SMTPAuthenticationError, config: SMTPConfig) -> AuthenticationFailed:
    code, text = exc.smtp_code, _text(exc.smtp_error)
    host, low = config.host.lower(), text.lower()
    if 400 <= code < 500:
        return AuthenticationFailed("Login is temporarily unavailable. Try again in a few minutes.",
                                    code=code, server_reply=text)
    return AuthenticationFailed("Login failed: the server rejected your email or password.",
                                code=code, server_reply=text, hint=_login_hint(config, low))


def _login_hint(config: SMTPConfig, server_text: str = "") -> str:
    host = config.host.lower()
    if "gmail" in host or "google" in host or "google" in server_text:
        return ("Gmail needs an App Password, not your normal password: turn on 2-Step Verification, "
                "then create one at myaccount.google.com/apppasswords and paste the 16-character code here.")
    if "office365" in host or "outlook" in host:
        return ("Microsoft may have SMTP login (basic auth) disabled for this account; "
                "check it's allowed, or test with Gmail instead.")
    return "Check your email address and password."


class SMTPSession:
    def __init__(self, config: SMTPConfig, log: Optional[LogFn] = None) -> None:
        self.config = config
        self._log = log
        self._smtp: Optional[smtplib.SMTP] = None
        self.replies: List[SMTPReply] = []
        self.tls: Optional[TLSInfo] = None
        self.logged_in_as: Optional[str] = None

    def __enter__(self) -> "SMTPSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def is_connected(self) -> bool:
        return self._smtp is not None and self._smtp.sock is not None

    @property
    def is_encrypted(self) -> bool:
        return self.is_connected and isinstance(self._smtp.sock, ssl.SSLSocket)

    @property
    def server_features(self) -> Dict[str, str]:
        return dict(self._smtp.esmtp_features) if self._smtp else {}

    @property
    def max_message_size(self) -> Optional[int]:
        size = self.server_features.get("size", "").strip()
        return int(size) if size.isdigit() and int(size) > 0 else None

    def _emit(self, line: str) -> None:
        if self._log:
            self._log(line)

    def _record(self, stage: str, code: int, msg) -> SMTPReply:
        reply = SMTPReply(stage, code, _text(msg))
        self.replies.append(reply)
        return reply

    def _note_tls(self) -> None:
        sock = self._smtp.sock
        if isinstance(sock, ssl.SSLSocket):
            cipher = sock.cipher()
            self.tls = TLSInfo(sock.version() or "TLS", cipher[0] if cipher else "?",
                               self.config.verify_certificate)
            self._emit(f"* Secure channel established: {self.tls}")

    def connect(self) -> None:
        cfg = self.config
        cfg.validate()
        ctx = make_ssl_context(cfg)

        if cfg.security is SecurityMode.SSL:
            smtp = _LoggedSMTP_SSL(timeout=cfg.timeout, context=ctx)
        else:
            smtp = _LoggedSMTP(timeout=cfg.timeout)
        smtp._host = cfg.host
        smtp._log_fn = self._log
        smtp.set_debuglevel(1)

        stage = "connect"
        try:
            code, msg = smtp.connect(cfg.host, cfg.port)
            self._record("Greeting", code, msg)
            if code != 220:
                raise smtplib.SMTPConnectError(code, msg)
            self._smtp = smtp
            if cfg.security is SecurityMode.SSL:
                self._note_tls()

            stage = "EHLO"
            code, msg = smtp.ehlo()
            self._record("EHLO", code, msg)
            if not 200 <= code < 300:
                raise smtplib.SMTPHeloError(code, msg)

            if cfg.security is SecurityMode.STARTTLS:
                stage = "STARTTLS"
                if not smtp.has_extn("starttls"):
                    raise SecureChannelError(
                        "This server does not offer STARTTLS, so the connection can't be encrypted.",
                        hint="Try SSL/TLS mode on port 465, or check the server address.")
                code, msg = smtp.starttls(context=ctx)
                self._record("STARTTLS", code, msg)
                self._note_tls()
                stage = "EHLO"
                code, msg = smtp.ehlo()
                self._record("EHLO", code, msg)
                if not 200 <= code < 300:
                    raise smtplib.SMTPHeloError(code, msg)
        except BaseException as exc:
            self._smtp = None
            try:
                smtp.close()
            except Exception:
                pass
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise translate_error(exc, stage, cfg) from exc

    def login(self, credentials: Credentials) -> SMTPReply:
        if not self.is_connected:
            raise NotLoggedIn("Not connected to the server.")
        credentials.validate()
        if not self.is_encrypted:
            raise AuthenticationFailed("Refusing to send your password over an unencrypted connection.")
        if not self._smtp.has_extn("auth"):
            raise AuthenticationFailed("This server doesn't accept logins (it offers no AUTH method).",
                                       hint="Check you're using the provider's submission server (port 465/587).")

        smtp = self._smtp
        smtp._hide_sends = True
        try:
            code, msg = self._authenticate(credentials)
        except smtplib.SMTPServerDisconnected as exc:
            raise AuthenticationFailed(
                "Login failed: the server closed the connection while checking your email and password, "
                "which usually means it rejected them.",
                hint=_login_hint(self.config)) from exc
        except smtplib.SMTPAuthenticationError as exc:
            self._record("AUTH", exc.smtp_code, exc.smtp_error)
            raise _auth_error(exc, self.config) from exc
        except smtplib.SMTPNotSupportedError as exc:
            raise AuthenticationFailed("This server doesn't support logging in.") from exc
        except smtplib.SMTPException as exc:
            if "authentication method" in str(exc).lower():
                methods = self.server_features.get("auth", "none")
                raise AuthenticationFailed(
                    f"The server's login methods ({methods}) aren't supported by this app.") from exc
            raise translate_error(exc, "AUTH", self.config) from exc
        except OSError as exc:
            raise translate_error(exc, "AUTH", self.config) from exc
        finally:
            smtp._hide_sends = False

        reply = self._record("AUTH", code, msg)
        self.logged_in_as = credentials.username
        self._emit(f"* Logged in as {credentials.username}")
        return reply

    def _authenticate(self, credentials: Credentials):
        smtp = self._smtp
        offered = self.server_features.get("auth", "").upper().split()
        smtp.user, smtp.password = credentials.username, credentials.password
        for mech, method in (("PLAIN", smtp.auth_plain), ("LOGIN", smtp.auth_login),
                             ("CRAM-MD5", smtp.auth_cram_md5)):
            if mech in offered:
                return smtp.auth(mech, method, initial_response_ok=True)
        raise smtplib.SMTPException("No suitable authentication method found.")

    def send_message(
        self,
        msg: Message,
        *,
        sender: Optional[str] = None,
        recipients: Optional[Iterable[str]] = None,
    ) -> SendResult:
        if not self.is_connected or not self.logged_in_as:
            raise NotLoggedIn("Log in before sending.")
        if not isinstance(msg, Message):
            raise TypeError("send_message() needs an email.message.Message (build it with message_builder).")

        sender = sender or self.logged_in_as
        rcpts = list(dict.fromkeys(recipients)) if recipients is not None else envelope_recipients(msg)
        if not rcpts:
            raise ConfigError("The message has no recipients.", field="to")

        data = flatten_message(msg)
        limit = self.max_message_size
        if limit and len(data) > limit:
            raise DeliveryFailed(
                f"The email is {_mb(len(data))} but this server accepts at most {_mb(limit)}.",
                hint="Remove or shrink attachments. Base64 encoding makes files about 33% bigger.")

        smtp = self._smtp
        options = []
        if smtp.has_extn("size"):
            options.append(f"SIZE={len(data)}")
        if any(b > 127 for b in data) and smtp.has_extn("8bitmime"):
            options.append("BODY=8BITMIME")

        replies: List[SMTPReply] = []

        def record(stage, code, text) -> SMTPReply:
            r = SMTPReply(stage, code, _text(text))
            replies.append(r)
            self.replies.append(r)
            return r

        stage = "sending"
        try:
            code, text = smtp.mail(sender, options)
            r = record("MAIL FROM", code, text)
            if code != 250:
                self._reset()
                raise SenderRefused(f"The server rejected the sender address {sender}.",
                                    code=code, server_reply=r.message,
                                    hint="Send from the same address you logged in with.")

            accepted: List[str] = []
            refused: Dict[str, SMTPReply] = {}
            for addr in rcpts:
                code, text = smtp.rcpt(addr)
                r = record(f"RCPT TO <{addr}>", code, text)
                if code in (250, 251):
                    accepted.append(addr)
                else:
                    refused[addr] = r

            if not accepted:
                self._reset()
                first = next(iter(refused.values()))
                raise RecipientsRefused(
                    "The server rejected every recipient, so nothing was sent.",
                    refused={a: (r.code, r.message) for a, r in refused.items()},
                    code=first.code, server_reply=first.message,
                    hint="Check the addresses are spelled correctly.")

            code, text = smtp.data(data)
            r = record("DATA", code, text)
            if code != 250:
                self._reset()
                raise DeliveryFailed("The server did not accept the message.",
                                     code=code, server_reply=r.message)
        except DispatcherError:
            raise
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise translate_error(exc, stage, self.config) from exc

        self._emit(f"* Message accepted for {len(accepted)} of {len(rcpts)} recipient(s)")
        return SendResult(sender, accepted, refused, replies, len(data))

    def _reset(self) -> None:
        try:
            self._smtp.rset()
        except Exception:
            pass

    def close(self) -> None:
        if self._smtp is None:
            return
        smtp, self._smtp = self._smtp, None
        try:
            code, msg = smtp.quit()
            self._record("QUIT", code, msg)
        except Exception:
            try:
                smtp.close()
            except Exception:
                pass
        self.logged_in_as = None
