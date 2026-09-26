"""Polite fetcher (CONTRACT_C §1/§3). GET only, transparent user agent, robots.txt (cached 24 h), a per-domain
minimum delay (5 s HTML, 1 s APIs, or the site's Crawl-delay if longer), ETag/If-Modified-Since caching and a hard
block on manual-lane domains. Every request — including refusals — is written to `fetch_log`."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

import httpx

from hq import settings as paths
from hq.adapters.base import TransientError
from hq.db.conn import tx
from hq.util import netguard
from hq.util.timeutil import now_iso, parse_iso, utcnow

USER_AGENT = "AgentHQ/1.0 (personal job search; +local)"
ROBOTS_TTL = timedelta(hours=24)
DELAY = {"html": 5.0, "api": 1.0}
MAX_BYTES = 6_000_000


class FetchBlocked(Exception):
    """Refused by policy (manual lane, robots.txt, netguard). Not retried."""


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    from_cache: bool
    etag: str | None = None

    def json(self) -> Any:
        return json.loads(self.text)


def cache_dir() -> Path:
    d = paths.DATA / "cache" / "http"
    d.mkdir(parents=True, exist_ok=True)
    return d


def domain_of(url: str) -> str:
    host = netguard.host_of(url)
    return host[4:] if host.startswith("www.") else host


class Fetcher:
    def __init__(self, conn: sqlite3.Connection, *, transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], Any] = asyncio.sleep,
                 check_robots: bool = True):
        self.conn = conn
        self.transport = transport
        self.clock = clock
        self.sleep = sleep
        self.check_robots = check_robots
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _client(self) -> httpx.AsyncClient:
        return netguard.guarded_client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True,
                                       headers={"User-Agent": USER_AGENT}, transport=self.transport)

    def _log(self, method: str, url: str, *, status: int | None = None, size: int | None = None,
             from_cache: bool = False, source_id: str | None = None, blocked: str | None = None,
             ms: int | None = None) -> None:
        with tx(self.conn):
            self.conn.execute(
                "INSERT INTO fetch_log(ts, method, url, domain, status, bytes, from_cache, source_id, blocked_reason, "
                "duration_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (now_iso(), method, url, domain_of(url), status, size, int(from_cache), source_id, blocked, ms))

    # ── robots ──────────────────────────────────────────────────────────────────────────────────────
    async def _robots(self, client: httpx.AsyncClient, url: str) -> urllib.robotparser.RobotFileParser:
        domain = domain_of(url)
        host = netguard.host_of(url)
        row = self.conn.execute("SELECT robots_txt, robots_fetched_at FROM domain_policy WHERE domain=?",
                                (domain,)).fetchone()
        fresh = row and row["robots_fetched_at"] and utcnow() - parse_iso(row["robots_fetched_at"]) < ROBOTS_TTL
        text = row["robots_txt"] if fresh else None
        if not fresh:
            robots_url = f"https://{host}/robots.txt"
            try:
                r = await client.get(robots_url)
                self._log("GET", robots_url, status=r.status_code, size=len(r.content))
                if r.status_code >= 500:
                    text = "User-agent: *\nDisallow: /"   # RFC 9309: unreachable → assume disallowed for now
                elif r.status_code >= 400:
                    text = ""                             # no robots.txt → everything allowed
                else:
                    text = r.text[:500_000]
            except httpx.HTTPError as exc:
                self._log("GET", robots_url, blocked=f"robots fetch failed: {type(exc).__name__}")
                text = ""
            with tx(self.conn):
                self.conn.execute(
                    "INSERT INTO domain_policy(domain, robots_txt, robots_fetched_at, manual_lane) VALUES (?,?,?,?) "
                    "ON CONFLICT(domain) DO UPDATE SET robots_txt=excluded.robots_txt, "
                    "robots_fetched_at=excluded.robots_fetched_at", (domain, text, now_iso(), 0))
        rp = urllib.robotparser.RobotFileParser()
        rp.parse((text or "").splitlines())
        return rp

    # ── GET ─────────────────────────────────────────────────────────────────────────────────────────
    async def get(self, url: str, *, kind: str = "html", source_id: str | None = None,
                  use_cache: bool = True) -> FetchResult:
        domain = domain_of(url)
        if netguard.is_manual_lane(url):
            self._log("GET", url, source_id=source_id, blocked="manual lane")
            raise FetchBlocked(f"{domain} is a manual-lane site; HQ never fetches it")
        if self.transport is None and os.environ.get("HQ_OFFLINE") == "1" and \
                netguard.host_of(url) not in netguard.LOOPBACK:
            self._log("GET", url, source_id=source_id, blocked="offline (HQ_OFFLINE=1)")
            raise FetchBlocked(f"offline: not fetching {domain}")
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock, self._client() as client:
            delay = DELAY.get(kind, 5.0)
            if self.check_robots:
                rp = await self._robots(client, url)
                if not rp.can_fetch(USER_AGENT, url):
                    self._log("GET", url, source_id=source_id, blocked="robots.txt disallows")
                    raise FetchBlocked(f"robots.txt on {domain} disallows {url}")
                cd = rp.crawl_delay(USER_AGENT)
                if cd:
                    delay = max(delay, float(cd))
            wait = self._last.get(domain, -1e9) + delay - self.clock()
            if wait > 0:
                await self.sleep(wait)
            cached = self.conn.execute("SELECT * FROM http_cache WHERE url=?", (url,)).fetchone() if use_cache else None
            headers = {}
            if cached and cached["body_path"] and Path(cached["body_path"]).exists():
                if cached["etag"]:
                    headers["If-None-Match"] = cached["etag"]
                if cached["last_modified"]:
                    headers["If-Modified-Since"] = cached["last_modified"]
            t0 = time.monotonic()
            try:
                r = await client.get(url, headers=headers)
            except netguard.NetGuardError as exc:
                self._log("GET", url, source_id=source_id, blocked=str(exc))
                raise FetchBlocked(str(exc)) from exc
            except httpx.HTTPError as exc:
                self._log("GET", url, source_id=source_id, blocked=f"{type(exc).__name__}")
                raise TransientError(f"GET {url}: {type(exc).__name__}: {exc}") from exc
            finally:
                self._last[domain] = self.clock()
            ms = int((time.monotonic() - t0) * 1000)
            if r.status_code == 304 and cached:
                self._log("GET", url, status=304, size=0, from_cache=True, source_id=source_id, ms=ms)
                return FetchResult(url, 200, Path(cached["body_path"]).read_text(errors="replace"), True, cached["etag"])
            body = r.content[:MAX_BYTES]
            self._log("GET", url, status=r.status_code, size=len(body), source_id=source_id, ms=ms)
            if r.status_code in (429, 503) or r.status_code >= 500:
                raise TransientError(f"GET {url} → HTTP {r.status_code}"
                                     + (f" (Retry-After {r.headers.get('retry-after')})" if r.headers.get("retry-after")
                                        else ""))
            text = body.decode(r.encoding or "utf-8", errors="replace")
            if r.status_code == 200 and use_cache:
                sha = hashlib.sha256(url.encode()).hexdigest()[:32]
                path = cache_dir() / f"{sha}.body"
                path.write_text(text)
                with tx(self.conn):
                    self.conn.execute(
                        "INSERT INTO http_cache(url, etag, last_modified, status, fetched_at, body_path, sha256) "
                        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET etag=excluded.etag, "
                        "last_modified=excluded.last_modified, status=excluded.status, fetched_at=excluded.fetched_at, "
                        "body_path=excluded.body_path, sha256=excluded.sha256",
                        (url, r.headers.get("etag"), r.headers.get("last-modified"), r.status_code, now_iso(),
                         str(path), hashlib.sha256(body).hexdigest()))
            return FetchResult(url, r.status_code, text, False, r.headers.get("etag"))
