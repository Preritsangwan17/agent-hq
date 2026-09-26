"""In-memory Gmail API double for tests (CONTRACT_D §1): history ids, threads, messages, labels, drafts, Sent.

Mirrors the real client's async interface (hq/gmail/client.py). Failure injection covers what the send path must
survive: `fail_next_send` = "timeout" (ambiguous), "500" (ambiguous), "400" (definite) or "crash_after_send"
(the message is delivered but the caller never hears back — the duplicate-send recovery case).
"""
from __future__ import annotations

import email
import itertools
from email import policy
from typing import Any

from hq.gmail.api import GmailError, GmailMessage, GmailNotFound, GmailTransient, b64url, parse_message


class FakeGmail:
    def __init__(self, address: str = "sangwanprerit40@gmail.com", scopes: tuple[str, ...] = ("gmail.readonly",)):
        self.address = address
        self.scopes = scopes
        self._ids = itertools.count(1)
        self.history_id = 1000
        self.messages: dict[str, dict[str, Any]] = {}
        self.history_log: list[tuple[int, str]] = []    # (history id, message id added)
        self.min_history = 1000                            # history older than this answers 404
        self.drafts: list[dict[str, Any]] = []
        self.fail_next_send: str | None = None
        self.calls: list[tuple[str, Any]] = []

    # ── test helpers ─────────────────────────────────────────────────────────────────────────────────
    def deliver(self, *, from_addr: str, subject: str, body: str, to_addr: str | None = None,
                thread_id: str | None = None, in_reply_to: str | None = None, labels: tuple[str, ...] = ("INBOX",),
                from_name: str = "", date_ms: int | None = None) -> str:
        mid = f"m{next(self._ids):05d}"
        msg = email.message.EmailMessage()
        msg["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
        msg["To"] = to_addr or self.address
        msg["Subject"] = subject
        msg["Message-ID"] = f"<{mid}@fake.gmail>"
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)
        return self._store(mid, msg.as_bytes(), thread_id or f"t{mid}", list(labels), date_ms)

    def expire_history(self) -> None:
        """Make every stored history id too old (the next history call answers 404)."""
        self.min_history = self.history_id + 1

    def sent(self) -> list[GmailMessage]:
        return [parse_message(m) for m in self.messages.values() if "SENT" in m["labelIds"]]

    # ── internals ────────────────────────────────────────────────────────────────────────────────────
    def _store(self, mid: str, raw: bytes, thread_id: str, labels: list[str], date_ms: int | None = None) -> str:
        parsed = email.message_from_bytes(raw, policy=policy.default)
        body_part = parsed.get_body(preferencelist=("plain", "html"))
        text = body_part.get_content() if body_part is not None else ""
        self.history_id += 1
        self.messages[mid] = {
            "id": mid, "threadId": thread_id, "labelIds": labels, "historyId": str(self.history_id),
            "internalDate": str(date_ms or 1_790_000_000_000 + self.history_id * 1000), "snippet": text[:120],
            "payload": {"mimeType": "multipart/mixed" if parsed.is_multipart() else "text/plain",
                        "headers": [{"name": k, "value": str(v)} for k, v in parsed.items()],
                        "parts": [{"mimeType": "text/plain", "filename": "",
                                   "body": {"data": b64url(text.encode())}}]}}
        self.history_log.append((self.history_id, mid))
        return mid

    # ── API ──────────────────────────────────────────────────────────────────────────────────────────
    async def profile(self) -> dict[str, Any]:
        self.calls.append(("profile", None))
        return {"emailAddress": self.address, "historyId": str(self.history_id), "messagesTotal": len(self.messages)}

    async def history(self, start_history_id: str, page_token: str | None = None) -> dict[str, Any]:
        self.calls.append(("history", start_history_id))
        start = int(start_history_id)
        if start < self.min_history:
            raise GmailNotFound(404, "Requested entity was not found.")
        added = [{"id": str(h), "messagesAdded": [{"message": {"id": m, "threadId": self.messages[m]["threadId"],
                                                               "labelIds": self.messages[m]["labelIds"]}}]}
                 for h, m in self.history_log if h > start and m in self.messages]
        return {"history": added, "historyId": str(self.history_id)}

    async def list_messages(self, q: str, page_token: str | None = None, max_results: int = 100) -> dict[str, Any]:
        self.calls.append(("list", q))
        items = list(self.messages.values())
        if "in:sent" in q:
            items = [m for m in items if "SENT" in m["labelIds"]]
        if "rfc822msgid:" in q:
            want = q.split("rfc822msgid:", 1)[1].split()[0].strip("<>")
            items = [m for m in items if (parse_message(m).rfc822_id or "").strip("<>") == want]
        return {"messages": [{"id": m["id"], "threadId": m["threadId"]} for m in items][:max_results],
                "resultSizeEstimate": len(items)}

    async def get_message(self, message_id: str) -> GmailMessage:
        self.calls.append(("get", message_id))
        if message_id not in self.messages:
            raise GmailNotFound(404, "Requested entity was not found.")
        return parse_message(self.messages[message_id])

    async def send(self, raw: bytes, thread_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("send", thread_id))
        if not any(s.endswith(("gmail.send", "gmail.compose")) for s in self.scopes):
            raise GmailError(403, "Request had insufficient authentication scopes.")
        mode, self.fail_next_send = self.fail_next_send, None
        if mode == "timeout":
            raise GmailTransient("timed out")
        if mode == "500":
            raise GmailTransient("Gmail HTTP 500")
        if mode == "400":
            raise GmailError(400, "Invalid To header")
        mid = f"s{next(self._ids):05d}"
        self._store(mid, raw, thread_id or f"t{mid}", ["SENT"])
        if mode == "crash_after_send":
            raise GmailTransient("connection reset after the request was written")
        return {"id": mid, "threadId": self.messages[mid]["threadId"], "labelIds": ["SENT"]}

    async def create_draft(self, raw: bytes, thread_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("draft", thread_id))
        if not any(s.endswith("gmail.compose") for s in self.scopes):
            raise GmailError(403, "Request had insufficient authentication scopes.")
        d = {"id": f"d{next(self._ids):05d}", "message": {"threadId": thread_id}, "raw": raw}
        self.drafts.append(d)
        return {"id": d["id"], "message": {"id": d["id"], "threadId": thread_id}}
