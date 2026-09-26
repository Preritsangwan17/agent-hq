"""Gmail OAuth for a Desktop client (CONTRACT_D §1): installed-app flow with a loopback redirect and PKCE.

Prerit consents in his own browser; the redirect lands on a one-shot listener on 127.0.0.1:<random port> inside the
API process. The refresh token and the granted scopes go to .env (HQ_GMAIL_REFRESH_TOKEN, HQ_GMAIL_SCOPES) and
nowhere else. Phase (d) asks only for gmail.readonly; the go-live step asks again for gmail.send + gmail.compose.
While HQ_FORCE_DRY_RUN is on, a send-capable grant makes the worker refuse to start (`startup_refusal`).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from hq import settings as paths
from hq.gmail.api import GmailAuthError, GmailTransient
from hq.util import netguard

log = logging.getLogger(__name__)

SCOPE_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_SEND = "https://www.googleapis.com/auth/gmail.send"
SCOPE_COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
FLOW_TIMEOUT_S = 600


def client_id() -> str | None:
    return paths.env_fresh("HQ_GMAIL_CLIENT_ID")


def client_secret() -> str | None:
    return paths.env_fresh("HQ_GMAIL_CLIENT_SECRET")


def refresh_token() -> str | None:
    return paths.env_fresh("HQ_GMAIL_REFRESH_TOKEN")


def granted_scopes() -> list[str]:
    return [s for s in (paths.env_fresh("HQ_GMAIL_SCOPES") or "").split() if s]


def connected() -> bool:
    return bool(refresh_token() and client_id() and client_secret())


def has_send_scope(scopes: list[str] | None = None) -> bool:
    return any(s.endswith(("gmail.send", "gmail.compose", "mail.google.com/")) for s in (scopes or granted_scopes()))


def has_compose_scope(scopes: list[str] | None = None) -> bool:
    return any(s.endswith(("gmail.compose", "mail.google.com/")) for s in (scopes or granted_scopes()))


def forced_dry_run() -> bool:
    return os.environ.get("HQ_FORCE_DRY_RUN", "1") != "0"


def startup_refusal() -> str | None:
    """Why the worker must not start (None = fine). Uses the .env on disk, not a stale environment."""
    if forced_dry_run() and has_send_scope():
        return ("HQ_FORCE_DRY_RUN is on but the stored Gmail grant can send mail. Either finish going live (Settings › "
                "Autonomy & Mode) or disconnect Gmail and reconnect read-only (Settings › Gmail).")
    return None


class TokenProvider:
    """Access tokens from the stored refresh token, cached until a minute before expiry."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport
        self._token: str | None = None
        self._expires = 0.0

    def invalidate(self) -> None:
        self._token, self._expires = None, 0.0

    async def access_token(self) -> str:
        if self._token and time.monotonic() < self._expires - 60:
            return self._token
        rt, cid, sec = refresh_token(), client_id(), client_secret()
        if not (rt and cid and sec):
            raise GmailAuthError("Gmail is not connected (no refresh token / client in .env)")
        data = await _token_request({"client_id": cid, "client_secret": sec, "refresh_token": rt,
                                     "grant_type": "refresh_token"}, self.transport)
        self._token = data["access_token"]
        self._expires = time.monotonic() + float(data.get("expires_in", 3600))
        return self._token


async def _token_request(form: dict[str, str], transport: httpx.AsyncBaseTransport | None) -> dict[str, Any]:
    try:
        async with netguard.guarded_client(timeout=httpx.Timeout(20.0), transport=transport) as c:
            r = await c.post(TOKEN_URL, data=form)
    except httpx.HTTPError as exc:
        raise GmailTransient(f"token endpoint unreachable ({type(exc).__name__})") from None
    if r.status_code >= 500:
        raise GmailTransient(f"token endpoint HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200 or "access_token" not in data:
        err = data.get("error") or f"HTTP {r.status_code}"
        if err in ("invalid_grant", "unauthorized_client", "invalid_client"):
            raise GmailAuthError(f"Google rejected the stored Gmail grant ({err}) — reconnect in Settings › Gmail")
        raise GmailAuthError(f"token request failed: {err}")
    return data


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


_PAGE = ("<!doctype html><meta charset=utf-8><title>Agent HQ</title><body style='font-family:system-ui;background:"
         "#070B14;color:#E6EAF2;display:grid;place-items:center;height:100vh'><div><h2>{title}</h2><p>{text}</p>"
         "</div></body>")


class OAuthFlow:
    """One consent at a time. `start()` returns the Google URL; the loopback listener finishes the exchange."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport
        self.status = "idle"             # idle | pending | done | error
        self.error: str | None = None
        self.purpose: str | None = None
        self.scopes_granted: list[str] = []
        self.started_at: float | None = None
        self._server: asyncio.base_events.Server | None = None
        self._state = ""
        self._verifier = ""
        self._redirect = ""
        self._timeout: asyncio.Task | None = None

    def state(self) -> dict[str, Any]:
        return {"status": self.status, "error": self.error, "purpose": self.purpose,
                "scopes": self.scopes_granted}

    async def start(self, purpose: str) -> str:
        cid = client_id()
        if not (cid and client_secret()):
            raise GmailAuthError("add the OAuth client ID and secret first")
        await self.close()
        scopes = [SCOPE_READONLY] + ([SCOPE_SEND, SCOPE_COMPOSE] if purpose == "send" else [])
        self._verifier, challenge = _pkce()
        self._state = secrets.token_urlsafe(24)
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self._redirect = f"http://127.0.0.1:{port}/"
        self.status, self.error, self.purpose, self.started_at = "pending", None, purpose, time.time()
        self._timeout = asyncio.get_running_loop().create_task(self._expire())
        return AUTH_URL + "?" + urlencode({
            "client_id": cid, "redirect_uri": self._redirect, "response_type": "code", "scope": " ".join(scopes),
            "code_challenge": challenge, "code_challenge_method": "S256", "state": self._state,
            "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"})

    async def _expire(self) -> None:
        await asyncio.sleep(FLOW_TIMEOUT_S)
        if self.status == "pending":
            self.status, self.error = "error", "timed out waiting for consent"
        await self.close(cancel_timeout=False)

    async def close(self, cancel_timeout: bool = True) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if cancel_timeout and self._timeout and not self._timeout.done():
            self._timeout.cancel()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        title, text = "Something went wrong", "Go back to Agent HQ and try again."
        try:
            line = (await asyncio.wait_for(reader.readline(), 10)).decode("latin-1")
            path = line.split(" ")[1] if line.count(" ") >= 2 else "/"
            q = parse_qs(urlparse(path).query)
            if urlparse(path).path != "/" or not q:
                title, text = "Not found", ""
            elif q.get("state", [""])[0] != self._state:
                self.status, self.error = "error", "state mismatch (ignored a stray request)"
            elif "error" in q:
                self.status, self.error = "error", f"consent was not given ({q['error'][0]})"
                title, text = "Consent cancelled", "Nothing was stored. You can close this tab."
            elif "code" in q:
                await self._exchange(q["code"][0])
                title, text = "Gmail connected", "You can close this tab and go back to Agent HQ."
        except Exception as exc:  # noqa: BLE001 — surface any failure to the UI, never crash the API
            self.status, self.error = "error", str(exc)[:300]
        body = _PAGE.format(title=title, text=text).encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n"
                     + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        try:
            await writer.drain()
        finally:
            writer.close()
        if self.status != "pending":
            await self.close()

    async def _exchange(self, code: str) -> None:
        data = await _token_request({"client_id": client_id() or "", "client_secret": client_secret() or "",
                                     "code": code, "code_verifier": self._verifier, "redirect_uri": self._redirect,
                                     "grant_type": "authorization_code"}, self.transport)
        scopes = [s for s in (data.get("scope") or "").split() if s]
        if SCOPE_READONLY not in scopes:
            raise GmailAuthError("the read-only Gmail permission was not granted")
        if data.get("refresh_token"):
            paths.set_env_value("HQ_GMAIL_REFRESH_TOKEN", data["refresh_token"])
        elif not refresh_token():
            raise GmailAuthError("Google returned no refresh token — remove Agent HQ's access in your Google "
                                 "account settings and connect again")
        paths.set_env_value("HQ_GMAIL_SCOPES", " ".join(sorted(set(scopes))))
        self.scopes_granted = scopes
        self.status = "done"


FLOW = OAuthFlow()


def disconnect() -> None:
    """Forget the grant locally (Prerit can also revoke it at myaccount.google.com/permissions)."""
    paths.set_env_value("HQ_GMAIL_REFRESH_TOKEN", "")
    paths.set_env_value("HQ_GMAIL_SCOPES", "")
