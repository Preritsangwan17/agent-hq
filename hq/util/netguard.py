"""Network guard (CONTRACT_C §1, PLAN "Security › Development never contacts third parties").

`check(method, url)` raises NetGuardError when:
- the host is a manual-lane domain (LinkedIn, Internshala, …) — any method, any mode;
- the method is not GET/HEAD and the host is not loopback — unless it is a POST to the xAI model API (redacted
  prompts), or the mode is LIVE/SELF_TEST and the host is one of the Gmail endpoints the send path needs.
All HQ HTTP clients go through `guarded_client()` (an httpx event hook calls `check` on every request).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

from hq import settings as paths

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SEND_HOSTS = {"gmail.googleapis.com", "oauth2.googleapis.com", "www.googleapis.com"}
LLM_HOSTS = {"api.x.ai"}  # cloud model API (redacted prompts only); the Claude CLI talks to Anthropic itself
AUTH_ENDPOINTS = {("oauth2.googleapis.com", "/token")}  # OAuth code exchange / token refresh (not mail)


class NetGuardError(PermissionError):
    pass


@lru_cache(maxsize=2)
def _manual_lane(path: str, mtime: float) -> frozenset[str]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return frozenset(d.lower().lstrip(".") for d in data.get("domains", []))


def manual_lane_domains() -> frozenset[str]:
    p = paths.CONFIG_DIR / "manual_lane.yaml"
    return _manual_lane(str(p), p.stat().st_mtime) if p.exists() else frozenset()


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def is_manual_lane(url_or_host: str) -> bool:
    host = host_of(url_or_host) if "://" in url_or_host else url_or_host.lower()
    return any(host == d or host.endswith("." + d) for d in manual_lane_domains())


def current_mode() -> str:
    """dry_run unless the go-live step switched it (and HQ_FORCE_DRY_RUN is not set)."""
    if os.environ.get("HQ_FORCE_DRY_RUN", "1") != "0":
        return "dry_run"
    return os.environ.get("HQ_MODE", "dry_run")


def check(method: str, url: str, *, mode: str | None = None) -> None:
    host = host_of(url)
    if is_manual_lane(host):
        raise NetGuardError(f"{host} is a manual-lane site; HQ never contacts it")
    m = method.upper()
    if m in ("GET", "HEAD") or host in LOOPBACK:
        return
    if host in LLM_HOSTS and m == "POST" and urlparse(url).path.startswith("/v1/"):
        return
    if m == "POST" and (host, urlparse(url).path) in AUTH_ENDPOINTS:
        return
    if (mode or current_mode()) in ("live", "self_test") and host in SEND_HOSTS:
        return
    raise NetGuardError(f"blocked {m} to {host}: only GETs leave this Mac in {mode or current_mode()} mode")


async def _hook(request: httpx.Request) -> None:
    check(request.method, str(request.url))


def guarded_client(**kw) -> httpx.AsyncClient:
    hooks = kw.pop("event_hooks", {}) or {}
    hooks.setdefault("request", []).append(_hook)
    return httpx.AsyncClient(event_hooks=hooks, **kw)
