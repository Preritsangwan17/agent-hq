"""Cloud models behind one runner: the Claude CLI and xAI's API.

Model ids carry their provider — Claude aliases are bare ("sonnet", tagged "claude:sonnet") and xAI models are
"xai:<model>". The `cloud_llm` setting picks the default provider: auto (xAI when HQ_XAI_API_KEY is in .env,
otherwise Claude), claude, or xai. Every call still goes through the same daily budget, per-call cap and redaction.
Independence: a sign-off model is never one that wrote any version of the text (`signoff_model`).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from hq.llm.claude import ClaudeResult, ClaudeRunner
from hq.llm.xai import XaiRunner, api_key

CLAUDE_OTHER = {"opus": "sonnet", "sonnet": "opus", "haiku": "sonnet"}
XAI_DEFAULT = "grok-4-fast"
XAI_SIGNOFF_DEFAULT = "grok-4"


def provider(s: dict[str, Any]) -> str:
    v = s.get("cloud_llm", "auto")
    if v == "auto":
        return "xai" if api_key() else "claude"
    return v


def tag(model: str) -> str:
    return model if ":" in model else f"claude:{model}"


def is_cloud(model_id: str | None) -> bool:
    return bool(model_id) and model_id.startswith(("claude:", "xai:"))  # type: ignore[union-attr]


def label(model: str) -> str:
    return "xAI" if tag(model).startswith("xai:") else "Claude"


def main_model(s: dict[str, Any]) -> str:
    if provider(s) == "xai":
        return f"xai:{s.get('xai_model') or XAI_DEFAULT}"
    return s.get("claude_model", "sonnet")


def signoff_candidates(s: dict[str, Any]) -> list[str]:
    cs = s.get("claude_signoff_model", "opus")
    claude = [cs, CLAUDE_OTHER.get(cs, "sonnet"), "haiku"]
    xai = [f"xai:{s.get('xai_signoff_model') or XAI_SIGNOFF_DEFAULT}", f"xai:{s.get('xai_model') or XAI_DEFAULT}"]
    ordered = xai + claude if provider(s) == "xai" else claude + (xai if api_key() else [])
    return list(dict.fromkeys(ordered))


class CloudRunner:
    """Drop-in for ClaudeRunner (`available`, `run`, `state`, `reason`) that dispatches on the model id."""

    def __init__(self, conn: sqlite3.Connection | None, claude: ClaudeRunner | None = None,
                 xai: XaiRunner | None = None):
        self.conn = conn
        self.claude = claude or ClaudeRunner(conn)
        self.xai = xai or XaiRunner(conn)
        self._last = self.claude

    def _settings(self) -> dict[str, Any]:
        if self.conn is None:
            return {}
        from hq.db.seed import get_settings

        return get_settings(self.conn)

    def _pick(self, model: str | None) -> tuple[Any, str]:
        s = self._settings()
        active = provider(s)
        self.claude.nag = active == "claude"   # only the provider in use raises "fix access" Needs items
        self.xai.nag = active == "xai"
        m = model or main_model(s)
        runner = self.xai if tag(m).startswith("xai:") else self.claude
        self._last = runner
        return runner, m

    @property
    def reason(self) -> str | None:
        return self._last.reason

    async def available(self, force: bool = False, model: str | None = None) -> bool:
        runner, _ = self._pick(model)
        return await runner.available(force=force)

    async def available_for(self, model: str) -> bool:
        return await self.available(model=model)

    def mark_unavailable(self, reason: str) -> None:
        self._last.mark_unavailable(reason)

    async def run(self, prompt: str, *, schema: dict[str, Any], system_prompt: str, model: str | None = None,
                  max_budget_usd: float = 0.5, **kw: Any) -> ClaudeResult:
        runner, m = self._pick(model)
        if runner is self.xai:
            return await self.xai.run(prompt, schema=schema, system_prompt=system_prompt, model=m,
                                      max_budget_usd=max_budget_usd, **kw)
        return await self.claude.run(prompt, schema=schema, system_prompt=system_prompt,
                                     model=m.removeprefix("claude:"), max_budget_usd=max_budget_usd, **kw)

    def state(self, settings: dict[str, Any]) -> dict[str, Any]:
        active = provider(settings)
        main = self.xai if active == "xai" else self.claude
        st = main.state(settings)
        return {**st, "provider": active, "model": main_model(settings),
                "providers": {"claude": self.claude.state(settings), "xai": self.xai.state(settings)}}


async def is_available(runner: Any, model: str) -> bool:
    """Works for CloudRunner and for plain runners/fakes that only know `available()`."""
    fn = getattr(runner, "available_for", None)
    return await (fn(model) if fn else runner.available())


async def signoff_model(runner: Any, s: dict[str, Any], lineage: set[str]) -> str | None:
    """First sign-off candidate that wrote nothing in this document's lineage and is reachable now."""
    for m in signoff_candidates(s):
        if tag(m) not in lineage and await is_available(runner, m):
            return m
    return None
