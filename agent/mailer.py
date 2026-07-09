"""
agent/mailer.py
===============
Send an email via SMTP — used for Wendy's self-notifications (reminders,
"task X finished") to the user's OWN address only.

Setup (no purchase, no API, no Google Cloud — just a free Gmail App Password):
  1. Turn on 2-Step Verification on your Google account.
  2. Google Account → Security → App passwords → create one (name it "Wendy").
  3. Put these two lines in .env:
        GMAIL_ADDRESS=you@gmail.com
        GMAIL_APP_PASSWORD=the16charcode

Optional overrides for a non-Gmail SMTP server:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_TO

If nothing is configured, sending is skipped gracefully (the app still runs;
reminders just show in-app without an email).
"""

import os
import ssl
import smtplib
from email.message import EmailMessage


def _config():
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError:
        port = 587
    user = (os.environ.get("SMTP_USER") or os.environ.get("GMAIL_ADDRESS", "")).strip()
    pw = (os.environ.get("SMTP_PASS") or os.environ.get("GMAIL_APP_PASSWORD", "")).strip()
    frm = (os.environ.get("SMTP_FROM") or user).strip()
    to = (os.environ.get("SMTP_TO") or user).strip()
    return host, port, user, pw, frm, to


def is_configured():
    """True if enough SMTP config is present to attempt sending."""
    _, _, user, pw, _, _ = _config()
    return bool(user and pw)


def recipient():
    """The address self-notes are sent to (the user's own address)."""
    return _config()[5]


def send_email(to, subject, body):
    """Send an email to ANY recipient. Returns (ok: bool, message: str)."""
    host, port, user, pw, frm, _ = _config()
    if not (user and pw):
        return False, ("Email isn't set up yet. Add GMAIL_ADDRESS and "
                       "GMAIL_APP_PASSWORD to your .env file.")
    to = (to or "").strip()
    if not to:
        return False, "No recipient address was given."

    msg = EmailMessage()
    msg["Subject"] = subject or "(no subject)"
    msg["From"] = frm or user
    msg["To"] = to
    msg.set_content(body or "")

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=ctx)
            server.login(user, pw)
            server.send_message(msg)
        return True, f"Sent to {to}."
    except Exception as e:
        return False, f"Email failed: {e}"


def send_self_email(subject, body):
    """Send an email to the user's OWN address (self-notifications)."""
    return send_email(recipient(), subject, body)