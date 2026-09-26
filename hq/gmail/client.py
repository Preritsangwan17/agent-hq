"""Thin async client for the Gmail REST API (users/me). Every request goes through the net guard: GETs are always
allowed, POSTs (send / drafts) only when the process runs in SELF_TEST or LIVE mode."""
from __future__ import annotations

from typing import Any

import httpx

from hq.gmail.api import GmailError, GmailMessage, GmailNotFound, GmailTransient, b64url, parse_message
from hq.gmail.auth import TokenProvider, connected
from hq.util import netguard

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailClient:
    def __init__(self, tokens: TokenProvider | None = None, *, transport: httpx.AsyncBaseTransport | None = None):
        self.tokens = tokens or TokenProvider()
        self.transport = transport

    async def _call(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                    json: dict[str, Any] | None = None, retry_auth: bool = True) -> dict[str, Any]:
        token = await self.tokens.access_token()
        try:
            async with netguard.guarded_client(timeout=httpx.Timeout(30.0, connect=10.0), transport=self.transport) as c:
                r = await c.request(method, BASE + path, params=params, json=json,
                                    headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise GmailTransient(f"{type(exc).__name__} talking to Gmail") from None
        if r.status_code == 401 and retry_auth:
            self.tokens.invalidate()
            return await self._call(method, path, params=params, json=json, retry_auth=False)
        if r.status_code == 404:
            raise GmailNotFound(404, "not found")
        if r.status_code == 429 or r.status_code >= 500:
            raise GmailTransient(f"Gmail HTTP {r.status_code}")
        if r.status_code >= 400:
            try:
                msg = (r.json().get("error") or {}).get("message") or r.text[:200]
            except ValueError:
                msg = r.text[:200]
            raise GmailError(r.status_code, str(msg))
        return r.json() if r.content else {}

    async def profile(self) -> dict[str, Any]:
        return await self._call("GET", "/profile")

    async def history(self, start_history_id: str, page_token: str | None = None) -> dict[str, Any]:
        params = {"startHistoryId": start_history_id, "historyTypes": "messageAdded", "maxResults": 500}
        if page_token:
            params["pageToken"] = page_token
        return await self._call("GET", "/history", params=params)

    async def list_messages(self, q: str, page_token: str | None = None, max_results: int = 100) -> dict[str, Any]:
        params: dict[str, Any] = {"q": q, "maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        return await self._call("GET", "/messages", params=params)

    async def get_message(self, message_id: str) -> GmailMessage:
        return parse_message(await self._call("GET", f"/messages/{message_id}", params={"format": "full"}))

    async def send(self, raw: bytes, thread_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"raw": b64url(raw)}
        if thread_id:
            body["threadId"] = thread_id
        return await self._call("POST", "/messages/send", json=body)

    async def create_draft(self, raw: bytes, thread_id: str | None = None) -> dict[str, Any]:
        msg: dict[str, Any] = {"raw": b64url(raw)}
        if thread_id:
            msg["threadId"] = thread_id
        return await self._call("POST", "/drafts", json={"message": msg})


def from_env() -> GmailClient | None:
    return GmailClient() if connected() else None


__all__ = ["GmailClient", "GmailError", "GmailNotFound", "GmailTransient", "from_env"]
