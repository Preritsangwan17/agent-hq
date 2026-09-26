"""Authentication and request hardening (CONTRACT §2).

- Passcode: scrypt (n=2^14, r=8, p=1) stored in .env as `scrypt$n$r$p$salt_b64$hash_b64`.
- Session: `hq_session` cookie signed with itsdangerous TimestampSigner (HttpOnly, SameSite=Strict, 30 days).
- Host allowlist (DNS-rebinding defence) → 421; mutations need `X-HQ: 1` and an allowlisted Origin → 403.
- Login rate limit 5/min/IP; setup is loopback-only.
Never log passcodes, hashes, cookies or secrets.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from hq import settings

COOKIE_NAME = "hq_session"
SESSION_MAX_AGE = 30 * 24 * 3600
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 2 ** 14, 8, 1, 32
MIN_PASSCODE_LEN = 6
DEFAULT_HOSTS = {"localhost", "127.0.0.1", "::1"}
MUTATING = {"POST", "PATCH", "PUT", "DELETE"}


class ApiError(Exception):
    def __init__(self, status: int, error: str, detail: Any = None):
        super().__init__(error)
        self.status = status
        self.error = error
        self.detail = detail


# ── passcode hashing ─────────────────────────────────────────────────────────────────────────────────
def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_passcode(passcode: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.scrypt(passcode.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_passcode(passcode: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        scheme, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        n_i, r_i, p_i = int(n), int(r), int(p)
        if scheme != "scrypt" or not (2 <= n_i <= 2 ** 20 and 1 <= r_i <= 32 and 1 <= p_i <= 16):
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(hash_b64)
        dk = hashlib.scrypt(passcode.encode("utf-8"), salt=salt, n=n_i, r=r_i, p=p_i, dklen=len(expected),
                            maxmem=256 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, expected)


def passcode_hash() -> str | None:
    return os.environ.get("HQ_PASSCODE_HASH") or None


def is_configured() -> bool:
    return bool(passcode_hash())


def ensure_session_secret() -> None:
    """First run: create HQ_SESSION_SECRET in .env if it is missing."""
    settings.load_env()
    if not os.environ.get("HQ_SESSION_SECRET"):
        settings.set_env_value("HQ_SESSION_SECRET", secrets.token_hex(32))


def set_passcode(passcode: str) -> None:
    settings.set_env_value("HQ_PASSCODE_HASH", hash_passcode(passcode))


# ── sessions ─────────────────────────────────────────────────────────────────────────────────────────
def _signer() -> TimestampSigner:
    secret = os.environ.get("HQ_SESSION_SECRET")
    if not secret:
        raise ApiError(500, "session secret missing; run ./start.sh")
    return TimestampSigner(secret, salt="hq-session")


def new_session_token() -> str:
    return _signer().sign(f"v1.{secrets.token_hex(12)}".encode()).decode()


def session_valid(token: str | None) -> bool:
    if not token:
        return False
    try:
        _signer().unsign(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    return True


def set_session_cookie(response: Any) -> None:
    response.set_cookie(COOKIE_NAME, new_session_token(), max_age=SESSION_MAX_AGE, path="/", httponly=True,
                        samesite="strict", secure=False)


def clear_session_cookie(response: Any) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")


def is_authenticated(request: Request) -> bool:
    return session_valid(request.cookies.get(COOKIE_NAME))


def require_session(request: Request) -> None:
    if not is_authenticated(request):
        raise ApiError(401, "unauthorized")


# ── network checks ───────────────────────────────────────────────────────────────────────────────────
def allowed_hosts() -> set[str]:
    hosts = set(DEFAULT_HOSTS)
    if os.environ.get("HQ_LAN") == "1":
        hosts.update(h.strip().lower() for h in os.environ.get("HQ_ALLOWED_HOSTS", "").split(",") if h.strip())
    return hosts


def hostname(value: str | None) -> str | None:
    """'localhost:8765' → 'localhost', '[::1]:8765' → '::1'. Ports are ignored."""
    if not value:
        return None
    value = value.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else None
    if value.count(":") > 1:  # bare IPv6
        return value
    return value.split(":", 1)[0]


def origin_allowed(origin: str | None) -> bool:
    if not origin or origin == "null":
        return False
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and hostname(parts.netloc) in allowed_hosts()


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def is_loopback(request: Request) -> bool:
    host = client_ip(request)
    if not host:
        return False
    try:
        addr = ip_address(host)
    except ValueError:
        return False
    mapped = getattr(addr, "ipv4_mapped", None)
    return addr.is_loopback or bool(mapped and mapped.is_loopback)


def require_loopback(request: Request) -> None:
    if not is_loopback(request):
        raise ApiError(403, "this action is only allowed from the Mac itself (loopback)")


class RateLimiter:
    def __init__(self, limit: int = 5, window_s: float = 60.0):
        self.limit = limit
        self.window_s = window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


class SecurityMiddleware:
    """Pure ASGI middleware: Host allowlist on everything, CSRF headers on /api mutations."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if hostname(headers.get("host")) not in allowed_hosts():
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await _json(send, 421, {"error": "misdirected request: host not allowed"})
            return
        method = scope.get("method", "GET").upper()
        if scope["type"] == "http" and method in MUTATING and scope.get("path", "").startswith("/api/"):
            if headers.get("x-hq") != "1" or not origin_allowed(headers.get("origin")):
                await _json(send, 403, {"error": "forbidden: mutating requests need X-HQ: 1 and an allowed Origin"})
                return
        await self.app(scope, receive, send)


async def _json(send: Any, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]})
    await send({"type": "http.response.body", "body": payload})
