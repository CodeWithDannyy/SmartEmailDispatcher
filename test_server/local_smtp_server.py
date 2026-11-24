from __future__ import annotations

import argparse
import datetime as dt
import email
import email.policy
import ipaddress
import logging
import ssl
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

warnings.filterwarnings("ignore", message=".*login_data is deprecated.*")
warnings.filterwarnings("ignore", message="Requiring AUTH while not requiring TLS.*")

logging.getLogger("mail.log").setLevel(logging.ERROR)

HERE = Path(__file__).resolve().parent
DEFAULT_USERS = {"test@dispatcher.local": "test1234"}
REJECT_DOMAIN = "@reject.test"
DEFAULT_MAX_SIZE = 5 * 1024 * 1024


def ensure_certs(cert_dir: Path = HERE / "certs") -> Tuple[Path, Path, Path]:
    cert_dir.mkdir(parents=True, exist_ok=True)
    ca_crt, srv_crt, srv_key = cert_dir / "ca.crt", cert_dir / "server.crt", cert_dir / "server.key"
    if ca_crt.exists() and srv_crt.exists() and srv_key.exists():
        return ca_crt, srv_crt, srv_key

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = dt.datetime.now(dt.timezone.utc)
    later = now + dt.timedelta(days=3650)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Smart Email Dispatcher Test CA")])
    ca_ski = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(later)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(ca_ski, critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(later)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.IPAddress(ipaddress.ip_address("::1")),
        ]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    ca_crt.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    srv_crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    srv_key.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return ca_crt, srv_crt, srv_key


def server_tls_context(cert: Path, key: Path) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(cert), str(key))
    return ctx


class Authenticator:
    def __init__(self, users: Dict[str, str]):
        self.users = users

    def __call__(self, server, session, envelope, mechanism, auth_data):
        if not isinstance(auth_data, LoginPassword):
            return AuthResult(success=False, handled=False)
        user = auth_data.login.decode("utf-8", "replace")
        ok = self.users.get(user) == auth_data.password.decode("utf-8", "replace")
        return AuthResult(success=ok, handled=False)


class InboxHandler:
    def __init__(self, inbox: Path, quiet: bool = False):
        self.inbox = inbox
        self.quiet = quiet
        self.received: List[Path] = []
        inbox.mkdir(parents=True, exist_ok=True)

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if address.lower().endswith(REJECT_DOMAIN):
            return "550 5.1.1 <%s>: Recipient address rejected: user unknown" % address
        envelope.rcpt_tos.append(address)
        return "250 2.1.5 OK"

    async def handle_DATA(self, server, session, envelope):
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = self.inbox / f"{stamp}.eml"
        path.write_bytes(envelope.original_content or envelope.content)
        self.received.append(path)
        if not self.quiet:
            msg = email.message_from_bytes(envelope.content, policy=email.policy.default)
            files = [p.get_filename() for p in msg.iter_attachments()] if msg.is_multipart() else []
            print(f"\n[received] from {envelope.mail_from} to {', '.join(envelope.rcpt_tos)}")
            print(f"           subject: {msg['Subject']!s}")
            print(f"           attachments: {', '.join(f for f in files if f) or 'none'}")
            print(f"           saved: {path}")
        return f"250 2.0.0 OK: queued as {stamp}"


def start_servers(
    starttls_port: int = 2525,
    ssl_port: int = 4650,
    *,
    host: str = "127.0.0.1",
    users: Optional[Dict[str, str]] = None,
    inbox: Path = HERE / "inbox",
    cert_dir: Path = HERE / "certs",
    max_size: int = DEFAULT_MAX_SIZE,
    quiet: bool = False,
) -> Tuple[List[Controller], InboxHandler]:
    _, crt, key = ensure_certs(cert_dir)
    handler = InboxHandler(inbox, quiet)
    common = dict(
        authenticator=Authenticator(users or DEFAULT_USERS),
        auth_required=True,
        data_size_limit=max_size,
        ident="Smart Email Dispatcher local test server",
    )
    starttls = Controller(handler, hostname=host, port=starttls_port,
                          tls_context=server_tls_context(crt, key), require_starttls=True,
                          auth_require_tls=True, **common)
    implicit = Controller(handler, hostname=host, port=ssl_port,
                          ssl_context=server_tls_context(crt, key), server_hostname="localhost",
                          auth_require_tls=False, **common)
    started: List[Controller] = []
    try:
        for c in (starttls, implicit):
            c.start()
            started.append(c)
    except Exception:
        for c in started:
            c.stop()
        raise
    return started, handler


def stop_servers(controllers: List[Controller]) -> None:
    for c in controllers:
        try:
            c.stop()
        except Exception:
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Local SMTP test server for Smart Email Dispatcher")
    ap.add_argument("--starttls-port", type=int, default=2525)
    ap.add_argument("--ssl-port", type=int, default=4650)
    args = ap.parse_args(argv)

    try:
        controllers, _ = start_servers(args.starttls_port, args.ssl_port)
    except OSError as exc:
        print(f"Could not start: {exc}\n(Is the server already running, or the port in use?)")
        return 1

    user, pw = next(iter(DEFAULT_USERS.items()))
    print("Smart Email Dispatcher - local test SMTP server")
    print(f"  STARTTLS : localhost:{args.starttls_port}")
    print(f"  SSL/TLS  : localhost:{args.ssl_port}")
    print(f"  Login    : {user} / {pw}")
    print(f"  Refused  : any address ending in {REJECT_DOMAIN}")
    print(f"  Inbox    : {HERE / 'inbox'}")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        stop_servers(controllers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
