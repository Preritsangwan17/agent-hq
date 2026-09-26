"""Cloud models behind one runner: the Claude CLI, xAI's API (Grok) and ChatGPT through the Codex CLI.

Model ids carry their provider — Claude aliases are bare ("sonnet", tagged "claude:sonnet"), xAI models are
"xai:<model>" and Codex models "codex:<model>" ("codex:default" = Codex's own default). Every source has an on/off
switch (`llm_local_enabled`, `llm_claude_enabled`, `llm_xai_enabled`, `llm_codex_enabled`): a source that is off is
never called, not even for a login/key check. `cloud_llm` names the preferred cloud provider (auto = xAI when
HQ_XAI_API_KEY is in .env, otherwise Claude, then ChatGPT); when it can't be reached, the next switched-on provider
is used. Every call still goes through the same daily budget, per-call cap and redaction.

Limits are not spent twice: a provider that reports a usage/rate limit rests for REST_S (no calls at all) while the
others carry on. Independence: a sign-off model is never one that wrote any version of the text (`signoff_model`).
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from hq.llm import modes, policy
from hq.llm.claude import ClaudeRateLimited, ClaudeResult, ClaudeRunner, ClaudeUnavailable
from hq.llm.codex import CodexRunner
from hq.llm.xai import XaiRunner, api_key

PROVIDERS = ("claude", "xai", "codex")
LABELS = {"claude": "Claude", "xai": "xAI", "codex": "ChatGPT", "local": "Local models"}
SWITCH = {"local": "llm_local_enabled", "claude": "llm_claude_enabled", "xai": "llm_xai_enabled",
          "codex": "llm_codex_enabled"}
CLAUDE_OTHER = {"opus": "sonnet", "sonnet": "opus", "haiku": "sonnet"}
XAI_DEFAULT = "grok-4-fast"
XAI_SIGNOFF_DEFAULT = "grok-4"
CODEX_DEFAULT = "default"
REST_S = 3600
ALL_OFF = "every cloud model is switched off (Settings › Budget › Models on/off)"


def enabled(s: dict[str, Any], source: str) -> bool:
    return modes.enabled(s, source)


def local_enabled(s: dict[str, Any]) -> bool:
    return enabled(s, "local")


def order(s: dict[str, Any], task_type: str = "") -> list[str]:
    """Enabled providers ranked by task capability, with metered API last for routine work."""
    return policy.cloud_order(s, task_type)


def provider(s: dict[str, Any]) -> str | None:
    """The provider in use: the preferred one if it is switched on, else the next one; None when all are off."""
    o = order(s)
    return o[0] if o else None


def tag(model: str) -> str:
    return model if ":" in model else f"claude:{model}"


def provider_of(model: str) -> str:
    return tag(model).split(":", 1)[0]


def is_cloud(model_id: str | None) -> bool:
    return bool(model_id) and model_id.startswith(tuple(f"{p}:" for p in PROVIDERS))  # type: ignore[union-attr]


def label(model: str) -> str:
    return LABELS.get(provider_of(model), "Claude")


def model_for(s: dict[str, Any], p: str) -> str:
    if p == "xai":
        return f"xai:{s.get('xai_model') or XAI_DEFAULT}"
    if p == "codex":
        return f"codex:{s.get('codex_model') or CODEX_DEFAULT}"
    return s.get("claude_model", "sonnet")


def main_model(s: dict[str, Any]) -> str | None:
    p = provider(s)
    return model_for(s, p) if p else None


def signoff_candidates(s: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for p in order(s):
        if p == "claude":
            cs = s.get("claude_signoff_model", "opus")
            out += [cs, CLAUDE_OTHER.get(cs, "sonnet"), "haiku"]
        elif p == "xai":
            out += [f"xai:{s.get('xai_signoff_model') or XAI_SIGNOFF_DEFAULT}", model_for(s, "xai")]
        else:
            out += [f"codex:{s.get('codex_signoff_model') or CODEX_DEFAULT}", model_for(s, "codex")]
    return list(dict.fromkeys(out))


class CloudRunner:
    """Drop-in for ClaudeRunner (`available`, `run`, `state`, `reason`) that dispatches on the model id."""

    def __init__(self, conn: sqlite3.Connection | None, claude: ClaudeRunner | None = None,
                 xai: XaiRunner | None = None, codex: CodexRunner | None = None):
        self.conn = conn
        self.claude = claude or ClaudeRunner(conn)
        self.xai = xai or XaiRunner(conn)
        self.codex = codex or CodexRunner(conn)
        self.runners: dict[str, Any] = {"claude": self.claude, "xai": self.xai, "codex": self.codex}
        self.resting: dict[str, tuple[float, str]] = {}   # provider → (monotonic until, why)
        self._last: Any = self.claude
        self._why: str | None = None                        # set when the pick itself failed (off / resting)

    def _settings(self) -> dict[str, Any]:
        if self.conn is None:
            return {}
        from hq.db.seed import get_settings

        return get_settings(self.conn)

    def _nag(self, s: dict[str, Any]) -> None:
        active = provider(s)
        for name, r in self.runners.items():   # only the provider in use raises "fix access" Needs items
            r.nag = name == active

    def rest_reason(self, p: str) -> str | None:
        until, why = self.resting.get(p, (0.0, ""))
        if time.monotonic() >= until:
            self.resting.pop(p, None)
            return None
        mins = max(1, round((until - time.monotonic()) / 60))
        return f"{LABELS[p]} hit its usage limit ({why[:120]}); resting {mins} min so no calls are wasted"

    def rest(self, p: str, why: str, seconds: float = REST_S) -> None:
        self.resting[p] = (time.monotonic() + seconds, why)

    def _pick(self, model: str | None) -> tuple[Any, str | None]:
        s = self._settings()
        self._nag(s)
        m = model or main_model(s)
        if m is None:
            self._why = ALL_OFF
            return None, None
        p = provider_of(m)
        if p not in self.runners or not enabled(s, p):
            self._why = f"{LABELS.get(p, p)} is switched off in Settings"
            return None, m
        self._why = self.rest_reason(p)
        if self._why:
            return None, m
        self._last = self.runners[p]
        return self._last, m

    @property
    def reason(self) -> str | None:
        return self._why or self._last.reason

    async def available(self, force: bool = False, model: str | None = None) -> bool:
        runner, _ = self._pick(model)
        return False if runner is None else await runner.available(force=force)

    async def available_for(self, model: str) -> bool:
        return await self.available(model=model)

    async def check_all(self, force: bool = True) -> None:
        """Worker upkeep: refresh login/key status of the switched-on providers (free — no model is called)."""
        s = self._settings()
        self._nag(s)
        for p in order(s):
            if not self.rest_reason(p):
                await self.runners[p].available(force=force)

    def mark_unavailable(self, reason: str) -> None:
        self._last.mark_unavailable(reason)

    async def run(self, prompt: str, *, schema: dict[str, Any], system_prompt: str, model: str | None = None,
                  max_budget_usd: float = 0.5, **kw: Any) -> ClaudeResult:
        runner, m = self._pick(model)
        if runner is None or m is None:
            raise ClaudeUnavailable(self._why or ALL_OFF)
        if runner is self.claude:
            m = m.removeprefix("claude:")
        try:
            return await runner.run(prompt, schema=schema, system_prompt=system_prompt, model=m,
                                    max_budget_usd=max_budget_usd, **kw)
        except ClaudeRateLimited as exc:
            self.rest(provider_of(m), str(exc))
            raise

    def state(self, settings: dict[str, Any]) -> dict[str, Any]:
        """`available` is true when any switched-on provider can take a call; `using` names the first such one."""
        active = provider(settings)
        provs: dict[str, Any] = {}
        for name, r in self.runners.items():
            st = {**r.state(settings), "enabled": enabled(settings, name)}
            resting = self.rest_reason(name)
            if resting:
                st.update(available=False, reason=resting, resting=True)
            provs[name] = st
        usable = [p for p in order(settings) if provs[p]["available"]]
        main = provs[active] if active else {}
        reason = None if usable else (main.get("reason") if main else ALL_OFF)
        return {**main, "available": bool(usable), "reason": reason, "provider": active, "using": usable[0] if usable
                else None, "model": main_model(settings), "providers": provs,
                "local_enabled": True, "ai_mode": modes.current(settings)}


async def is_available(runner: Any, model: str) -> bool:
    """Works for CloudRunner and for plain runners/fakes that only know `available()`."""
    fn = getattr(runner, "available_for", None)
    return await (fn(model) if fn else runner.available())


async def pick(runner: Any, s: dict[str, Any], exclude: set[str] | frozenset[str] = frozenset(), *, task_type: str = "") -> str | None:
    """The first switched-on provider's model (preferred first) that is reachable now and not in `exclude`."""
    if runner is None:
        return None
    for p in order(s, task_type):
        m = model_for(s, p)
        if tag(m) not in exclude and await is_available(runner, m):
            return m
    return None


def why_none(runner: Any, s: dict[str, Any]) -> str:
    """Why `pick` found nothing, for Deferred / EscalationExhausted messages."""
    if not order(s):
        return ALL_OFF
    return f"no switched-on cloud model is reachable ({getattr(runner, 'reason', None) or 'not checked yet'})"


async def signoff_model(runner: Any, s: dict[str, Any], lineage: set[str]) -> str | None:
    """First sign-off candidate that wrote nothing in this document's lineage and is reachable now."""
    for m in signoff_candidates(s):
        if tag(m) not in lineage and await is_available(runner, m):
            return m
    return None
