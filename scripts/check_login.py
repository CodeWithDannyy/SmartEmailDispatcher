import argparse
import getpass
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dispatcher import (
    Credentials, DispatcherError, EmailDispatcher, SecurityMode, SMTPConfig, all_profiles,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list available profiles")
    ap.add_argument("--profile", help="profile name (see --list)")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--mode", choices=["ssl", "starttls"])
    ap.add_argument("--email")
    ap.add_argument("--send-to", help="also send a short test email to this address")
    ap.add_argument("--quiet", action="store_true", help="hide the SMTP protocol log")
    a = ap.parse_args()

    profiles = {p.name: p for p in all_profiles()}
    if a.list:
        for p in profiles.values():
            print(f"  {p.name:32} {p.host}:{p.port} {p.security.label}")
        return 0

    if a.profile:
        if a.profile not in profiles:
            print(f"Unknown profile {a.profile!r}. Use --list.")
            return 2
        cfg = profiles[a.profile]
    elif a.host:
        mode = SecurityMode(a.mode or "starttls")
        cfg = SMTPConfig("CLI", a.host, a.port or mode.usual_port, mode)
    else:
        ap.error("give --profile or --host")

    email = a.email or input("Email: ").strip()
    password = getpass.getpass("Password (hidden): ")
    log = None if a.quiet else (lambda line: print("   " + line))
    d = EmailDispatcher(cfg, log=log)

    try:
        print(f"\n[1] Connection + TLS to {cfg.host}:{cfg.port} ({cfg.security.label})")
        print(d.test_connection().summary())
        print(f"\n[2] Login as {email}")
        d.verify_login(Credentials(email, password))
        print("Login OK")
        if a.send_to:
            print(f"\n[3] Sending a test email to {a.send_to}")
            msg = EmailMessage()
            msg["From"], msg["To"] = email, a.send_to
            msg["Subject"] = "Smart Email Dispatcher - test"
            msg["Date"], msg["Message-ID"] = formatdate(localtime=True), make_msgid()
            msg.set_content("If you can read this, SMTP login and secure sending work.")
            r = d.send(Credentials(email, password), msg)
            print(f"Sent. Server said: {r.final_reply.code} {r.final_reply.message}")
            for addr, rep in r.refused.items():
                print(f"Refused {addr}: {rep.code} {rep.message}")
    except DispatcherError as e:
        print("\nFAILED: " + e.details())
        return 1
    print("\nAll good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
