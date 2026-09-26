"""xAI (Grok) API runner — HQ's only paid cloud model. Local models do everything they can first (hq.llm.policy).

`available()` (cached 10 min) and `run(prompt, schema, system_prompt, model, max_budget_usd)` → CloudResult with
structured output validated against the schema. Plain chat completions: no
tools, no web search, nothing but the redacted prompt leaves the Mac, and only to api.x.ai (the net guard allows
nothing else). The key lives in .env as HQ_XAI_API_KEY and is never logged or sent anywhere but that host.
An empty account (no credit) or a rejected key becomes one Needs Prerit item instead of retries.
"""
from __future__ import annotations

import sqlite3
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import yaml

from hq import settings as paths
from hq.llm.errors import CloudBadOutput, CloudBudgetExceeded, CloudError, CloudRateLimited, CloudResult, \
    CloudUnavailable
from hq.llm.json_utils import parse_and_validate, repair_message
from hq.util import netguard
from hq.util.redact import redact

BASE_URL = "https://api.x.ai/v1"
KEY_ENV = "HQ_XAI_API_KEY"
AVAILABILITY_TTL_S = 600
TIMEOUT_S = 120
MAX_OUTPUT_TOKENS = 2000
NEED_TITLE = "Fix Grok (xAI) API access"
CREDIT_WORDS = ("credit", "billing", "balance", "spending limit", "insufficient", "payment", "exhausted")


def api_key() -> str | None:
    key = (paths.env_fresh(KEY_ENV) or "").strip()
    return key or None


@lru_cache(maxsize=2)
def _prices(path: str, mtime: float) -> dict[str, Any]:
    return (yaml.safe_load(Path(path).read_text()) or {}).get("xai", {})


def price_for(model: str) -> tuple[float, float]:
    p = paths.CONFIG_DIR / "cloud_prices.yaml"
    table = _prices(str(p), p.stat().st_mtime) if p.exists() else {}
    best_name, best = "", table.get("default") or {"input": 3.0, "output": 15.0}
    for name, v in table.items():  # longest matching prefix wins (grok-4-fast-reasoning → grok-4-fast)
        if name != "default" and model.startswith(name) and len(name) > len(best_name):
            best_name, best = name, v
    return float(best["input"]), float(best["output"])


def cost_of(model: str, usage: dict[str, Any]) -> float:
    return cost_with_source(model, usage)[0]


def cost_with_source(model: str, usage: dict[str, Any]) -> tuple[float, str]:
    """(cost, "reported") when xAI returned the exact cost of the call, else (price-table estimate, "estimated")."""
    ticks = usage.get("cost_in_usd_ticks")
    if isinstance(ticks, (int, float)) and ticks >= 0:
        return round(ticks / 1e10, 8), "reported"
    pin, pout = price_for(model)
    return round((usage.get("prompt_tokens") or 0) * pin / 1e6 + (usage.get("completion_tokens") or 0) * pout / 1e6,
                 6), "estimated"


KEY_INFO_FIELDS = ("name", "redacted_api_key", "api_key_blocked", "api_key_disabled", "team_blocked", "create_time")


def ensure_need(conn: sqlite3.Connection, reason: str) -> str | None:
    from hq.db import repo, serializers
    from hq.db.conn import tx

    if conn.execute("SELECT 1 FROM needs_prerit WHERE title=? AND status IN ('open','snoozed')", (NEED_TITLE,)).fetchone():
        return None
    credit = any(w in reason.lower() for w in CREDIT_WORDS)
    steps = ("Add credit to your xAI account at https://console.x.ai (Billing), then mark this done."
             if credit else
             f"Put a valid key in `.env` on this Mac as `{KEY_ENV}=…` (create one at https://console.x.ai → API Keys), "
             "restart HQ (`make down && make up`), then mark this done.")
    with tx(conn):
        need_id = repo.insert_need(conn, {
            "kind": "decision", "title": NEED_TITLE, "priority": 60, "est_minutes": 2,
            "instructions_md": f"Grok (xAI) is unavailable ({reason}). Grok sign-off, polish and escalations wait; local "
                               f"models keep working.\n\n{steps}\n\nHQ re-checks every 10 minutes.",
            "direct_url": "https://console.x.ai"})
        need = serializers.need_json(repo.get_need_row(conn, need_id))
        repo.emit(conn, "needs.created", need["title"], level="warn", data={"need": need})
    return need_id


class XaiRunner:
    provider = "xai"

    def __init__(self, conn: sqlite3.Connection | None = None, *, transport: httpx.AsyncBaseTransport | None = None):
        self.conn = conn
        self.transport = transport
        self._checked_at = 0.0
        self._available: bool | None = None
        self.reason: str | None = None
        self.models: list[str] = []
        self.nag = True
        self.key_info: dict[str, Any] = {}         # from GET /v1/api-key (name, blocked/disabled flags)
        self.rate_limits: dict[str, str] = {}      # x-ratelimit-* headers of the last response, when xAI sends them
        self.rate_limits_at: float | None = None

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return netguard.guarded_client(base_url=BASE_URL, timeout=httpx.Timeout(timeout, connect=10.0),
                                       transport=self.transport,
                                       headers={"Authorization": f"Bearer {api_key() or ''}",
                                                "User-Agent": "AgentHQ/1.0"})

    def _set_unavailable(self, reason: str) -> bool:
        """`nag` is on only while xAI is the active provider, so an unused provider never raises Needs items."""
        self._available, self.reason = False, reason
        if self.conn is not None and self.nag:
            ensure_need(self.conn, reason)
        return False

    def mark_unavailable(self, reason: str) -> None:
        self._checked_at = time.monotonic()
        self._set_unavailable(reason)

    async def available(self, force: bool = False) -> bool:
        if not force and self._available is not None and time.monotonic() - self._checked_at < AVAILABILITY_TTL_S:
            return self._available
        self._checked_at = time.monotonic()
        if not api_key():
            return self._set_unavailable(f"no {KEY_ENV} in .env")
        try:
            async with self._client(20) as c:
                r = await c.get("/models")
        except (httpx.HTTPError, netguard.NetGuardError) as exc:
            return self._set_unavailable(f"couldn't reach api.x.ai ({type(exc).__name__})")
        if r.status_code != 200:
            return self._set_unavailable(_http_reason(r))
        try:
            self.models = sorted(m["id"] for m in r.json().get("data", []) if isinstance(m, dict) and m.get("id"))
        except (ValueError, AttributeError):
            self.models = []
        await self._refresh_key_info()
        self._available, self.reason = True, None
        return True

    async def _refresh_key_info(self) -> None:
        """Best effort, free: what xAI says about this key. It does NOT include a credit balance."""
        try:
            async with self._client(10) as c:
                r = await c.get("/api-key")
            if r.status_code == 200 and isinstance(r.json(), dict):
                data = r.json()
                self.key_info = {k: data[k] for k in KEY_INFO_FIELDS if k in data}
        except (httpx.HTTPError, netguard.NetGuardError, ValueError):
            pass

    def _note_headers(self, r: httpx.Response) -> None:
        limits = {k.lower(): v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
        if limits:
            self.rate_limits, self.rate_limits_at = limits, time.time()

    def resolve(self, name: str) -> str:
        """Configured names may drift (grok-4-fast → grok-4-fast-reasoning): pick the closest listed model."""
        if not self.models or name in self.models:
            return name
        for pred in (lambda m: m.startswith(name), lambda m: m.startswith(name.split("-fast")[0]),
                     lambda m: m.startswith("grok")):
            hit = [m for m in self.models if pred(m) and not any(x in m for x in ("image", "vision", "imagine"))]
            if hit:
                return hit[0]
        return name

    async def run(self, prompt: str, *, schema: dict[str, Any], system_prompt: str, model: str = "grok-4",
                  max_budget_usd: float = 0.5, timeout_s: float = TIMEOUT_S, **_: Any) -> CloudResult:
        if not api_key():
            raise CloudUnavailable(f"no {KEY_ENV} in .env")
        model = self.resolve(model.removeprefix("xai:"))
        system, user = redact(system_prompt, self.conn), redact(prompt, self.conn)
        pin, pout = price_for(model)
        est_in = (len(system) + len(user)) / 3.2
        room = (max_budget_usd - est_in * pin / 1e6) * 1e6 / pout
        if room < 200:
            raise CloudBudgetExceeded(f"prompt alone would exceed the ${max_budget_usd:.2f} per-call cap")
        max_tokens = int(min(MAX_OUTPUT_TOKENS, room))
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        fmt: dict[str, Any] | None = {"type": "json_schema",
                                      "json_schema": {"name": "hq_output", "schema": schema, "strict": False}}
        t0 = time.monotonic()
        total_cost, tin, tout, cached = 0.0, 0, 0, 0
        sources: set[str] = set()
        errors: list[str] = []
        async with self._client(timeout_s) as c:
            for attempt in range(3):
                body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0,
                                        "max_tokens": max_tokens}
                if fmt:
                    body["response_format"] = fmt
                try:
                    r = await c.post("/chat/completions", json=body)
                except httpx.TimeoutException:
                    raise CloudError(f"xAI timed out after {timeout_s:.0f} s") from None
                except httpx.HTTPError as exc:
                    raise CloudError(f"xAI request failed ({type(exc).__name__})") from None
                self._note_headers(r)
                if r.status_code == 400 and fmt and "response_format" in r.text:
                    fmt = None  # model without structured outputs: fall back to prompt-only JSON + validation
                    continue
                if r.status_code != 200:
                    reason = _http_reason(r)
                    if r.status_code in (401, 403) or any(w in r.text.lower() for w in CREDIT_WORDS):
                        self.mark_unavailable(reason)
                        raise CloudUnavailable(reason)
                    if r.status_code == 429:
                        raise CloudRateLimited(reason)
                    raise CloudError(reason)
                data = r.json()
                usage = data.get("usage") or {}
                cost, source = cost_with_source(model, usage)
                total_cost += cost
                sources.add(source)
                tin += usage.get("prompt_tokens") or 0
                tout += usage.get("completion_tokens") or 0
                cached += ((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
                text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                value, errors = parse_and_validate(text, schema)
                if not errors:
                    return CloudResult(output=value, cost_usd=round(total_cost, 8), input_tokens=tin,
                                       output_tokens=tout, cache_read_tokens=cached or None,
                                       duration_ms=(time.monotonic() - t0) * 1000, model=f"xai:{model}",
                                       subtype="success", raw={"id": data.get("id")},
                                       cost_source="reported" if sources == {"reported"} else "estimated")
                if total_cost >= max_budget_usd:
                    break
                messages = messages + [{"role": "assistant", "content": text[:4000]},
                                       {"role": "user", "content": repair_message(errors, schema)}]
        bad = CloudBadOutput("Grok output invalid: " + "; ".join(errors[:3]))
        bad.cost_usd = round(total_cost, 8)
        raise bad

    def state(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {"available": bool(self._available), "reason": self.reason, "key_present": api_key() is not None,
                "model": settings.get("xai_model"), "signoff_model": settings.get("xai_signoff_model"),
                "models": self.models[:40], "checked": self._available is not None, "key_info": self.key_info,
                "rate_limits": self.rate_limits,
                "rate_limits_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.rate_limits_at))
                if self.rate_limits_at else None}


def _http_reason(r: httpx.Response) -> str:
    try:
        err = r.json()
        msg = err.get("error") if isinstance(err, dict) else None
        if isinstance(msg, dict):
            msg = msg.get("message")
        msg = str(msg or err)[:200]
    except ValueError:
        msg = r.text[:200]
    low = msg.lower()
    if r.status_code == 401 or "incorrect api key" in low or "invalid api key" in low:
        return "xAI rejected the API key"
    if any(w in low for w in CREDIT_WORDS):
        return "the xAI account has no credit left"
    return f"xAI HTTP {r.status_code}: {msg}"


def key_fingerprint() -> str | None:
    """Safe to show in the UI: prefix and last 4 characters only."""
    k = api_key()
    return f"{k[:4]}…{k[-4:]}" if k and len(k) > 12 else None

