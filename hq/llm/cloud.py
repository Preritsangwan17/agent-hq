"""Cloud models behind one runner. Local models on the Mac are always tried first (hq.llm.policy); when a task needs
a cloud model, HQ uses the providers Prerit switched on, in this order by default:

  claude — the Claude CLI on his subscription      (flat fee: uses plan usage windows, $0 per call to HQ)
  codex  — ChatGPT's Codex CLI on his subscription (flat fee: uses plan usage windows, $0 per call to HQ)
  xai    — Grok through xAI's API                  (paid per token: HQ's daily $ limit applies)

Subscriptions come before the pay-per-token API because they cost nothing extra until a window runs out
(`prefer_subscriptions`, default on). Each provider has a fast and a strong model; model ids carry the provider
("claude:sonnet", "codex:default", "xai:grok-4-fast"). A sign-off model is never one that wrote any version of the
text (`signoff_model`), and HQ stops using a subscription CLI in a 5-hour window once it has made
`<provider>_window_calls` calls there, leaving the rest of the plan to Prerit.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from hq.llm.claude_cli import ClaudeCliRunner
from hq.llm.codex_cli import CodexCliRunner
from hq.llm.errors import CloudResult, CloudUnavailable
from hq.llm.xai import XaiRunner, api_key

XAI_DEFAULT = "grok-4-fast"
XAI_SIGNOFF_DEFAULT = "grok-4"
PROVIDERS: dict[str, dict[str, Any]] = {
    "claude": {"label": "Claude (CLI)", "kind": "subscription", "switch": "claude_cli_enabled", "default": False},
    "codex": {"label": "ChatGPT (Codex CLI)", "kind": "subscription", "switch": "codex_cli_enabled", "default": False},
    "xai": {"label": "Grok", "kind": "api", "switch": "grok_enabled", "default": True},
}
SUBSCRIPTIONS = ("claude", "codex")
WINDOW_HOURS = 5
DEFAULT_WINDOW_CALLS = 30


def provider_of(model_id: str | None) -> str | None:
    if not model_id or ":" not in model_id:
        return None
    p = model_id.split(":", 1)[0]
    return p if p in PROVIDERS else None


def provider(s: dict[str, Any] | None = None) -> str:
    """The first provider in preference order that is switched on (for display)."""
    on = enabled_providers(s or {})
    return on[0] if on else "xai"


def configured() -> bool:
    return api_key() is not None


def tag(model: str) -> str:
    return model if provider_of(model) else f"xai:{model}"


def is_cloud(model_id: str | None) -> bool:
    return provider_of(model_id) is not None


def label(model: str | None = None) -> str:
    p = provider_of(model) or "xai"
    return PROVIDERS[p]["label"]


def switched_on(s: dict[str, Any], p: str) -> bool:
    return bool(s.get(PROVIDERS[p]["switch"], PROVIDERS[p]["default"]))


def order(s: dict[str, Any]) -> list[str]:
    return ["claude", "codex", "xai"] if s.get("prefer_subscriptions", True) else ["xai", "claude", "codex"]


def enabled_providers(s: dict[str, Any]) -> list[str]:
    if not s.get("cloud_ai_enabled", True):
        return []
    return [p for p in order(s) if switched_on(s, p)]


def models_for(s: dict[str, Any], p: str) -> tuple[str, str]:
    if p == "claude":
        return f"claude:{s.get('claude_cli_model') or 'sonnet'}", f"claude:{s.get('claude_cli_strong_model') or 'opus'}"
    if p == "codex":
        m = f"codex:{s.get('codex_model') or 'default'}"
        return m, m
    return f"xai:{s.get('xai_model') or XAI_DEFAULT}", f"xai:{s.get('xai_signoff_model') or XAI_SIGNOFF_DEFAULT}"


def fast_model(s: dict[str, Any]) -> str:
    """Grok's fast model (display / legacy callers). Runtime choices go through `pick`."""
    return models_for(s, "xai")[0]


def strong_model(s: dict[str, Any]) -> str:
    return models_for(s, "xai")[1]


def main_model(s: dict[str, Any]) -> str:
    return fast_model(s)


def window_calls(conn: sqlite3.Connection, p: str, hours: int = WINDOW_HOURS) -> int:
    from hq.util.timeutil import to_iso, utcnow
    from datetime import timedelta

    since = to_iso(utcnow() - timedelta(hours=hours))
    return conn.execute("SELECT COUNT(*) FROM cloud_usage WHERE provider=? AND subtype!='released' AND created_at>=?",
                        (p, since)).fetchone()[0]


def window_cap(s: dict[str, Any], p: str) -> int:
    return int(s.get(f"{p}_window_calls", DEFAULT_WINDOW_CALLS))


def window_ok(conn: sqlite3.Connection | None, s: dict[str, Any], p: str) -> bool:
    if p not in SUBSCRIPTIONS or conn is None:
        return True
    return window_calls(conn, p) < window_cap(s, p)


def candidates(s: dict[str, Any], tier: str = "fast") -> list[str]:
    ps = enabled_providers(s)
    fast = [models_for(s, p)[0] for p in ps]
    strong = [models_for(s, p)[1] for p in ps]
    return list(dict.fromkeys(strong + fast if tier == "strong" else fast + strong))


def signoff_candidates(s: dict[str, Any], *, strong_first: bool = True) -> list[str]:
    return candidates(s, "strong" if strong_first else "fast")


async def is_available(runner: Any, model: str) -> bool:
    """Works for CloudRunner and for plain runners/fakes that only know `available()`."""
    fn = getattr(runner, "available_for", None)
    return await (fn(model) if fn else runner.available())


async def pick(runner: Any, s: dict[str, Any], tier: str = "fast", lineage: set[str] | None = None, *,
               conn: sqlite3.Connection | None = None, skip: set[str] | None = None) -> str | None:
    """First switched-on, reachable cloud model (in preference order) that wrote nothing in this lineage and whose
    subscription window still has room."""
    lineage, skip = lineage or set(), skip or set()
    if runner is None:
        return None
    for m in candidates(s, tier):
        p = provider_of(m)
        if tag(m) in lineage or p in skip or not window_ok(conn, s, p or ""):
            continue
        if await is_available(runner, m):
            return m
    return None


async def signoff_model(runner: Any, s: dict[str, Any], lineage: set[str], *, strong_first: bool = True,
                        conn: sqlite3.Connection | None = None) -> str | None:
    return await pick(runner, s, "strong" if strong_first else "fast", lineage, conn=conn)


class CloudRunner:
    """`available`, `run`, `state`, `reason` across Grok, the Claude CLI and the Codex CLI (by model id)."""

    def __init__(self, conn: sqlite3.Connection | None, xai: XaiRunner | None = None,
                 claude: ClaudeCliRunner | None = None, codex: CodexCliRunner | None = None):
        self.conn = conn
        self.runners: dict[str, Any] = {"xai": xai or XaiRunner(conn), "claude": claude or ClaudeCliRunner(conn),
                                        "codex": codex or CodexCliRunner(conn)}
        self._last = self.runners["xai"]

    @property
    def xai(self) -> XaiRunner:
        return self.runners["xai"]

    def _settings(self) -> dict[str, Any]:
        if self.conn is None:
            return {}
        from hq.db.seed import get_settings

        return get_settings(self.conn)

    def _runner(self, model: str) -> tuple[str, Any]:
        p = provider_of(tag(model)) or "xai"
        s = self._settings()
        on = p in enabled_providers(s)
        r = self.runners[p]
        r.nag = on and (configured() if p == "xai" else True)   # "fix access" Needs items only for providers in use
        self._last = r
        return p, r

    @property
    def reason(self) -> str | None:
        return self._last.reason

    async def available(self, force: bool = False, model: str | None = None) -> bool:
        if model:
            return await self.available_for(model, force=force)
        s = self._settings()
        ok = False
        for p in enabled_providers(s):
            ok = await self.available_for(models_for(s, p)[0], force=force) or ok
        return ok

    async def available_for(self, model: str, force: bool = False) -> bool:
        p, r = self._runner(model)
        if p not in enabled_providers(self._settings()):
            return False
        return await r.available(force=force)

    async def check_all(self) -> None:
        """Worker upkeep: re-check every provider (switched-off ones too, so the page can show what's installed)."""
        s = self._settings()
        for p, r in self.runners.items():
            r.nag = p in enabled_providers(s) and (configured() if p == "xai" else True)
            await r.available(force=True)

    def mark_unavailable(self, reason: str) -> None:
        self._last.mark_unavailable(reason)

    async def run(self, prompt: str, *, schema: dict[str, Any], system_prompt: str, model: str | None = None,
                  max_budget_usd: float = 0.5, **kw: Any) -> CloudResult:
        m = tag(model) if model else fast_model(self._settings())
        p, r = self._runner(m)
        if p not in enabled_providers(self._settings()):
            raise CloudUnavailable(f"{PROVIDERS[p]['label']} is switched off")
        return await r.run(prompt, schema=schema, system_prompt=system_prompt, model=m,
                           max_budget_usd=max_budget_usd, **kw)

    def state(self, settings: dict[str, Any]) -> dict[str, Any]:
        on = enabled_providers(settings)
        providers = {}
        for p, meta in PROVIDERS.items():
            st = self.runners[p].state(settings)
            fast, strong = models_for(settings, p)
            providers[p] = {**st, "label": meta["label"], "kind": meta["kind"], "enabled": p in on,
                            "switched_on": switched_on(settings, p), "fast_model": fast, "strong_model": strong}
        x = providers["xai"]
        return {"available": any(v["available"] for k, v in providers.items() if k in on),
                "reason": x.get("reason"), "key_present": x.get("key_present"), "key_info": x.get("key_info"),
                "rate_limits": x.get("rate_limits"), "rate_limits_at": x.get("rate_limits_at"),
                "model": fast_model(settings), "strong_model": strong_model(settings), "order": on,
                "provider": on[0] if on else None, "providers": providers}
