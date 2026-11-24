# Smart Email Dispatcher (SMTP Based)

CS3001 Computer Networks, Fall 2026, FAST-NUCES Karachi

| Name | Roll No. | Part |
|---|---|---|
| Daanial Tejani | 24K-0671 | Half 1: authentication, SMTP configuration, secure connection, transmission, error handling |
| Bazil Uddin Khan | 24K-0559 | Half 2: message construction, attachments, reply codes, integration |
| Abdul Mannan | 23K-0829 | Half 2 |

A PyQt5 desktop app that sends email directly over SMTP using Python's `smtplib`
and `email` libraries. It shows the protocol at work: the window has a live
SMTP log of every command and server reply.

---

## How it works

```
App                                   SMTP server
 | ---- TCP connect -------------------> |
 | <--- 220 greeting ------------------- |
 | ---- EHLO --------------------------> |
 | <--- 250 + extensions --------------- |   (STARTTLS, AUTH, SIZE...)
 | ---- STARTTLS ----------------------> |   STARTTLS mode only; SSL mode
 | <--- 220, TLS handshake ------------- |   is encrypted from the first byte
 | ---- EHLO (again, now encrypted) ---> |
 | ---- AUTH PLAIN/LOGIN --------------> |   password only ever sent over TLS
 | <--- 235 authenticated -------------- |
 | ---- MAIL FROM:<you> ---------------> |
 | ---- RCPT TO:<each recipient> ------> |   each one accepted/refused separately
 | ---- DATA + MIME message -----------> |
 | <--- 250 queued --------------------- |
 | ---- QUIT --------------------------> |
```

Security choices:
- Only **SSL/TLS (port 465)** and **STARTTLS (port 587)** are offered. Plain-text SMTP isn't.
- TLS 1.2 minimum. Certificate and hostname checking are on by default.
- The app refuses to send a password over an unencrypted link.
- Passwords stay in memory only. Saved profiles hold host, port and mode, never the password.
- The protocol log hides AUTH lines, so credentials never show on screen.

## Setup

Python 3.9+ (tested on 3.11, 3.12 and 3.13).

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

### Test without a real email account (recommended)

In a second terminal:

```bash
python test_server/local_smtp_server.py
```

Then in the app choose **Local test server (STARTTLS)** or **(SSL)** and log in with
`test@dispatcher.local` / `test1234`.

- Recipients ending in `@reject.test` are refused (550), which tests partial or failed delivery.
- Messages over 5 MB are rejected, which tests the size error.
- Every delivered email is saved in `test_server/inbox/*.eml`.

### Test with Gmail

Gmail needs an **App Password**: Google Account → Security → 2-Step Verification → App passwords.
Use the 16-character code as the password, with profile *Gmail (SSL 465)* or *Gmail (STARTTLS 587)*.

Microsoft (Outlook/365) accounts often have password-based SMTP login turned off, so use Gmail to test.

### Command-line check (no GUI)

```bash
python scripts/check_login.py --list
python scripts/check_login.py --profile "Gmail (SSL 465)" --email you@gmail.com --send-to you@gmail.com
```

### Automated tests

```bash
python -m pytest
```

These start the local server on random ports and exercise real TLS connections.
They need no internet access.

## Project structure

```
main.py                       entry point (login -> compose)
dispatcher/                   core logic, no GUI code
  config.py        [Half 1]   SMTP profiles, presets, validation, saving
  auth.py          [Half 1]   credentials + validation
  session.py       [Half 1]   connect, SSL/STARTTLS, AUTH, MAIL/RCPT/DATA, error translation, protocol log
  client.py        [Half 1]   EmailDispatcher: test_connection / verify_login / send
  errors.py        [Half 1]   error types shown to the user
  message_builder.py [Half 2] MIME message + attachments
  reply_codes.py     [Half 2] reply codes -> plain English
ui/                           PyQt5 windows (shared)
  login_window.py, settings_dialog.py, compose_window.py, widgets.py, styles.py
test_server/local_smtp_server.py   local SMTP server with TLS + AUTH for testing
scripts/check_login.py             command-line tester
tests/                             pytest suite
```
