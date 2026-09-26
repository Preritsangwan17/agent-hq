"""Types, errors and message parsing shared by the real Gmail client and the fake."""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import getaddresses, parseaddr
from typing import Any, Protocol


class GmailError(Exception):
    """An answer from Gmail that says the request did not happen (4xx other than 429)."""

    def __init__(self, status: int, reason: str):
        super().__init__(f"Gmail HTTP {status}: {reason}")
        self.status, self.reason = status, reason


class GmailNotFound(GmailError):
    pass


class GmailAuthError(Exception):
    """The stored grant is missing, revoked or expired — Prerit has to reconnect."""


class GmailTransient(Exception):
    """Timeouts, connection errors, 429 and 5xx: the request may or may not have happened."""


@dataclass
class GmailMessage:
    id: str
    thread_id: str
    label_ids: list[str]
    history_id: str | None
    internal_date: str | None          # ISO 8601 UTC
    from_addr: str
    from_name: str
    to_addrs: list[str]
    subject: str
    rfc822_id: str | None
    in_reply_to: str | None
    references: str | None
    snippet: str
    body_text: str
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def is_sent(self) -> bool:
        return "SENT" in self.label_ids


class GmailApi(Protocol):
    async def profile(self) -> dict[str, Any]: ...
    async def history(self, start_history_id: str, page_token: str | None = None) -> dict[str, Any]: ...
    async def list_messages(self, q: str, page_token: str | None = None, max_results: int = 100) -> dict[str, Any]: ...
    async def get_message(self, message_id: str) -> GmailMessage: ...
    async def send(self, raw: bytes, thread_id: str | None = None) -> dict[str, Any]: ...
    async def create_draft(self, raw: bytes, thread_id: str | None = None) -> dict[str, Any]: ...


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def unb64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _walk(part: dict[str, Any], out: dict[str, list[str]]) -> None:
    mime = (part.get("mimeType") or "").lower()
    data = (part.get("body") or {}).get("data")
    if data and mime in ("text/plain", "text/html") and not (part.get("filename") or ""):
        try:
            out.setdefault(mime, []).append(unb64url(data).decode("utf-8", "replace"))
        except (ValueError, TypeError):
            pass
    for sub in part.get("parts") or []:
        _walk(sub, out)


def parse_message(raw: dict[str, Any]) -> GmailMessage:
    payload = raw.get("payload") or {}
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers") or []}
    bodies: dict[str, list[str]] = {}
    _walk(payload, bodies)
    if bodies.get("text/plain"):
        text = "\n".join(bodies["text/plain"])
    elif bodies.get("text/html"):
        from hq.pipeline.discover.text import html_to_text

        text = "\n".join(html_to_text(h) for h in bodies["text/html"])
    else:
        text = raw.get("snippet") or ""
    name, addr = parseaddr(headers.get("from", ""))
    tos = [a for _, a in getaddresses([headers.get("to", ""), headers.get("cc", "")]) if a]
    internal = raw.get("internalDate")
    when = datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") \
        if internal and str(internal).isdigit() else None
    return GmailMessage(
        id=str(raw.get("id")), thread_id=str(raw.get("threadId")), label_ids=list(raw.get("labelIds") or []),
        history_id=str(raw["historyId"]) if raw.get("historyId") else None, internal_date=when,
        from_addr=addr.lower(), from_name=name, to_addrs=[t.lower() for t in tos], subject=headers.get("subject", ""),
        rfc822_id=_angle(headers.get("message-id")), in_reply_to=_angle(headers.get("in-reply-to")),
        references=headers.get("references"), snippet=raw.get("snippet") or text[:200], body_text=text.strip(),
        headers={k: v for k, v in headers.items() if k in ("from", "to", "cc", "subject", "date", "message-id",
                                                           "in-reply-to", "references", "list-unsubscribe")})


def _angle(v: str | None) -> str | None:
    if not v:
        return None
    m = re.search(r"<[^>]+>", v)
    return m.group(0) if m else v.strip()
