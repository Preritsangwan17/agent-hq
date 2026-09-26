"""Redaction for logs, run records and anything sent to Grok (PLAN "Security and safety").

Removes secret values from the environment, Prerit's phone number, date of birth and address (confirmed or not),
and anything shaped like a phone number, card number or government ID. The phone number never reaches Grok.
"""
from __future__ import annotations

import re
import sqlite3

SECRET_KEYS = ("HQ_PASSCODE_HASH", "HQ_SESSION_SECRET", "HQ_GMAIL_CLIENT_SECRET", "HQ_GMAIL_REFRESH_TOKEN",
               "HQ_XAI_API_KEY")
# also: Google OAuth tokens (ya29.… access tokens, 1//… refresh tokens) wherever they appear
API_KEY = re.compile(r"\b(?:xai|sk-ant|sk)-[A-Za-z0-9_-]{20,}|\bya29\.[A-Za-z0-9_.-]{20,}|\b1//[A-Za-z0-9_-]{20,}")
PRIVATE_FIELDS = ("phone", "dob", "address")
PHONE = re.compile(r"(?<!\w)(\+?\d{1,3}[\s-]?)?(\(?\d{2,5}\)?[\s-]?)\d{3,5}[\s-]?\d{4,5}(?!\w)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
AADHAAR = re.compile(r"(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)")
PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")


def _private_values(conn: sqlite3.Connection | None) -> list[str]:
    if conn is None:
        return []
    try:
        rows = conn.execute(f"SELECT value FROM profile_fields WHERE key IN ({','.join('?' * len(PRIVATE_FIELDS))}) "
                            "AND value IS NOT NULL AND value != ''", PRIVATE_FIELDS).fetchall()
    except sqlite3.Error:
        return []
    return [r[0] for r in rows if len(str(r[0])) >= 4]


def redact(text: str, conn: sqlite3.Connection | None = None) -> str:
    if not text:
        return text
    out = text
    from hq import settings as paths

    for key in SECRET_KEYS:
        val = paths.env_fresh(key)
        if val and len(val) >= 8:
            out = out.replace(val, f"[{key}]")
    for val in _private_values(conn):
        out = out.replace(str(val), "[redacted]")
    out = API_KEY.sub("[redacted-key]", out)
    out = CARD.sub(lambda m: "[redacted-number]" if len(re.sub(r"\D", "", m.group(0))) >= 13 else m.group(0), out)
    out = AADHAAR.sub("[redacted-id]", out)
    out = PAN.sub("[redacted-id]", out)
    out = PHONE.sub(lambda m: "[redacted-phone]" if len(re.sub(r"\D", "", m.group(0))) >= 10 else m.group(0), out)
    return out
