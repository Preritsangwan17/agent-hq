"""RFC 5322 messages for the send path: our own deterministic Message-ID (so a crash can be recovered by searching
Sent for `rfc822msgid:`), threading headers for replies, and attachments (the résumé PDF)."""
from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from typing import Any

FROM_NAME = "Prerit Sangwan"


def build_mime(*, from_addr: str, to_addr: str, subject: str, body: str, message_id: str,
               attachments: list[dict[str, Any]] | None = None, in_reply_to: str | None = None,
               references: str | None = None) -> bytes:
    msg = EmailMessage()
    msg["From"] = f"{FROM_NAME} <{from_addr}>"
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = (references + " " + in_reply_to) if references and in_reply_to not in references \
            else (references or in_reply_to)
    msg.set_content(body)
    for a in attachments or []:
        p = Path(a["path"])
        ctype, _ = mimetypes.guess_type(p.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=a.get("name") or p.name)
    return msg.as_bytes()


def reply_subject(subject: str | None) -> str:
    s = (subject or "").strip()
    return s if s.lower().startswith("re:") else f"Re: {s}" if s else "Re: your message"
