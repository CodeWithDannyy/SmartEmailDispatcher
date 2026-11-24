import base64
from email.message import EmailMessage

import pytest

from conftest import MAX_SIZE, PASSWORD, USER, free_port
from dispatcher import (
    AuthenticationFailed, ConfigError, ConnectionFailed, ConnectionTimeout, Credentials,
    DeliveryFailed, EmailDispatcher, NotLoggedIn, RecipientsRefused, SecureChannelError,
    SecurityMode, SMTPConfig, SMTPSession,
)


def message(to="friend@example.com", cc=None, bcc=None, body="Hello from the test suite."):
    m = EmailMessage()
    m["From"] = USER
    m["To"] = to
    if cc:
        m["Cc"] = cc
    if bcc:
        m["Bcc"] = bcc
    m["Subject"] = "Test"
    m.set_content(body)
    return m


@pytest.mark.parametrize("which", ["starttls_cfg", "ssl_cfg"])
def test_connection_is_encrypted_and_verified(which, request):
    report = EmailDispatcher(request.getfixturevalue(which)).test_connection()
    assert report.tls.version in ("TLSv1.2", "TLSv1.3") and report.tls.verified
    assert "LOGIN" in report.auth_methods or "PLAIN" in report.auth_methods
    assert report.replies[0].stage == "Greeting" and report.replies[0].code == 220


def test_starttls_reply_sequence(starttls_cfg):
    report = EmailDispatcher(starttls_cfg).test_connection()
    stages = [(r.stage, r.code) for r in report.replies]
    assert stages[:4] == [("Greeting", 220), ("EHLO", 250), ("STARTTLS", 220), ("EHLO", 250)]


def test_untrusted_certificate_rejected(starttls_cfg):
    starttls_cfg.ca_file = None
    with pytest.raises(SecureChannelError) as e:
        EmailDispatcher(starttls_cfg).test_connection()
    assert "certificate" in e.value.user_message.lower()


def test_ssl_mode_on_starttls_port(server):
    cfg = SMTPConfig("t", "localhost", server["ports"]["starttls"], SecurityMode.SSL,
                     timeout=5, ca_file=server["ca"])
    with pytest.raises(SecureChannelError) as e:
        EmailDispatcher(cfg).test_connection()
    assert e.value.hint and "STARTTLS" in e.value.hint


def test_starttls_mode_on_ssl_port_times_out(server):
    cfg = SMTPConfig("t", "localhost", server["ports"]["ssl"], SecurityMode.STARTTLS,
                     timeout=2, ca_file=server["ca"])
    with pytest.raises((ConnectionTimeout, ConnectionFailed)):
        EmailDispatcher(cfg).test_connection()


def test_connection_refused():
    cfg = SMTPConfig("t", "127.0.0.1", free_port(), SecurityMode.STARTTLS, timeout=3)
    with pytest.raises(ConnectionFailed) as e:
        EmailDispatcher(cfg).test_connection()
    assert "refused" in e.value.user_message


def test_unknown_host():
    cfg = SMTPConfig("t", "no-such-host.invalid", 587, SecurityMode.STARTTLS, timeout=3)
    with pytest.raises(ConnectionFailed):
        EmailDispatcher(cfg).test_connection()


def test_invalid_config_rejected_before_connecting():
    with pytest.raises(ConfigError):
        EmailDispatcher(SMTPConfig("t", "", 587)).test_connection()


@pytest.mark.parametrize("which", ["starttls_cfg", "ssl_cfg"])
def test_login_success(which, request, creds):
    replies = EmailDispatcher(request.getfixturevalue(which)).verify_login(creds)
    auth = [r for r in replies if r.stage == "AUTH"][0]
    assert auth.code == 235


def test_wrong_password(starttls_cfg):
    with pytest.raises(AuthenticationFailed) as e:
        EmailDispatcher(starttls_cfg).verify_login(Credentials(USER, "wrong-password"))
    assert e.value.code == 535


def test_wrong_password_makes_one_attempt_only(starttls_cfg):
    lines = []
    with pytest.raises(AuthenticationFailed):
        EmailDispatcher(starttls_cfg, log=lines.append).verify_login(Credentials(USER, "wrong-password"))
    assert sum(1 for l in lines if l.startswith("C: AUTH")) == 1


def test_disconnect_during_login_is_reported_as_login_failure(starttls_cfg, creds, monkeypatch):
    import smtplib

    def hang_up(*a, **kw):
        raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    monkeypatch.setattr(smtplib.SMTP, "auth", hang_up)
    with pytest.raises(AuthenticationFailed) as e:
        EmailDispatcher(starttls_cfg).verify_login(creds)
    assert "rejected" in e.value.user_message


def test_gmail_hint_mentions_app_password():
    from dispatcher.session import _login_hint
    assert "App Password" in _login_hint(SMTPConfig("g", "smtp.gmail.com", 465, SecurityMode.SSL))


def test_password_never_in_protocol_log(starttls_cfg, creds):
    lines = []
    EmailDispatcher(starttls_cfg, log=lines.append).verify_login(creds)
    log = "\n".join(lines)
    assert PASSWORD not in log
    for blob in (f"\0{USER}\0{PASSWORD}", PASSWORD, USER):
        assert base64.b64encode(blob.encode()).decode() not in log
    assert "credentials hidden" in log


def test_send_without_login(starttls_cfg):
    with SMTPSession(starttls_cfg) as s:
        s.connect()
        with pytest.raises(NotLoggedIn):
            s.send_message(message())


def test_send_success(starttls_cfg, creds, server):
    before = len(server["handler"].received)
    result = EmailDispatcher(starttls_cfg).send(creds, message(cc="c@example.com", bcc="hidden@example.com"))
    assert result.fully_delivered
    assert result.accepted == ["friend@example.com", "c@example.com", "hidden@example.com"]
    assert [r.stage for r in result.replies] == [
        "MAIL FROM", "RCPT TO <friend@example.com>", "RCPT TO <c@example.com>",
        "RCPT TO <hidden@example.com>", "DATA"]
    assert result.final_reply.code == 250
    saved = server["handler"].received[before].read_bytes()
    assert b"Hello from the test suite." in saved
    assert b"hidden@example.com" not in saved


def test_send_over_ssl(ssl_cfg, creds):
    assert EmailDispatcher(ssl_cfg).send(creds, message()).fully_delivered


def test_partial_refusal(starttls_cfg, creds):
    result = EmailDispatcher(starttls_cfg).send(creds, message(to="ok@example.com, nobody@reject.test"))
    assert result.accepted == ["ok@example.com"]
    assert result.refused["nobody@reject.test"].code == 550
    assert not result.fully_delivered


def test_all_recipients_refused(starttls_cfg, creds):
    with pytest.raises(RecipientsRefused) as e:
        EmailDispatcher(starttls_cfg).send(creds, message(to="a@reject.test, b@reject.test"))
    assert set(e.value.refused) == {"a@reject.test", "b@reject.test"}
    assert e.value.code == 550


def test_too_large_caught_before_upload(starttls_cfg, creds):
    big = message()
    big.add_attachment(b"x" * MAX_SIZE, maintype="application", subtype="octet-stream", filename="big.bin")
    with pytest.raises(DeliveryFailed) as e:
        EmailDispatcher(starttls_cfg).send(creds, big)
    assert "at most" in e.value.user_message


def test_no_recipients(starttls_cfg, creds):
    m = message()
    del m["To"]
    with pytest.raises(ConfigError):
        EmailDispatcher(starttls_cfg).send(creds, m)


def test_non_ascii_body(starttls_cfg, creds):
    assert EmailDispatcher(starttls_cfg).send(creds, message(body="Assalam o Alaikum - café ✓")).fully_delivered


def test_explicit_envelope(starttls_cfg, creds):
    r = EmailDispatcher(starttls_cfg).send(creds, message(), recipients=["x@example.com", "x@example.com"])
    assert r.accepted == ["x@example.com"]
