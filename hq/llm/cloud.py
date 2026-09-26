"""The paid cloud model: Grok, through xAI's API. Local models on the Mac are always tried first (hq.llm.policy).

Model ids carry their provider ("xai:<model>"). Two tiers, both editable in Settings › AI & budget:
  fast   — `xai_model` (default grok-4-fast): cheap; escalations, polish, eligibility third opinion
  strong — `xai_signoff_model` (default grok-4): expensive; final sign-off on important applications only
Every call goes through the same daily budget, per-call cap and redaction.
Independence: a sign-off model is never one that wrote any version of the text (`signoff_model`).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from hq.llm.errors import CloudResult
from hq.llm.xai import XaiRunner, api_key

XAI_DEFAULT = "grok-4-fast"
XAI_SIGNOFF_DEFAULT = "grok-4"
PROVIDER = "xai"
LABEL = "Grok"


def provider(s: dict[str, Any] | None = None) -> str:
    return PROVIDER


def configured() -> bool:
    """A key is in .env (it may still be out of credit — `CloudRunner.available()` says)."""
    return api_key() is not None


def tag(model: str) -> str:
    return model if model.startswith("xai:") else f"xai:{model}"


def is_cloud(model_id: str | None) -> bool:
    return bool(model_id) and model_id.startswith("xai:")  # type: ignore[union-attr]


def label(model: str | None = None) -> str:
    return LABEL


def fast_model(s: dict[str, Any]) -> str:
    return f"xai:{s.get('xai_model') or XAI_DEFAULT}"


def strong_model(s: dict[str, Any]) -> str:
    return f"xai:{s.get('xai_signoff_model') or XAI_SIGNOFF_DEFAULT}"


def main_model(s: dict[str, Any]) -> str:
    return fast_model(s)


def signoff_candidates(s: dict[str, Any], *, strong_first: bool = True) -> list[str]:
    ordered = [strong_model(s), fast_model(s)] if strong_first else [fast_model(s), strong_model(s)]
    return list(dict.fromkeys(ordered))


class CloudRunner:
    """`available`, `run`, `state`, `reason` for the Grok API. Kept as a thin wrapper so tests can swap it."""

    def __init__(self, conn: sqlite3.Connection | None, xai: XaiRunner | None = None):
        self.conn = conn
        self.xai = xai or XaiRunner(conn)

    @property
    def reason(self) -> str | None:
        return self.xai.reason

    async def available(self, force: bool = False, model: str | None = None) -> bool:
        self.xai.nag = configured()   # no key = local-only by choice: no "fix access" Needs item
        return await self.xai.available(force=force)

    async def available_for(self, model: str) -> bool:
        return await self.available(model=model)

    def mark_unavailable(self, reason: str) -> None:
        self.xai.mark_unavailable(reason)

    async def run(self, prompt: str, *, schema: dict[str, Any], system_prompt: str, model: str | None = None,
                  max_budget_usd: float = 0.5, **kw: Any) -> CloudResult:
        m = model or fast_model(self._settings())
        return await self.xai.run(prompt, schema=schema, system_prompt=system_prompt, model=m,
                                  max_budget_usd=max_budget_usd, **kw)

    def _settings(self) -> dict[str, Any]:
        if self.conn is None:
            return {}
        from hq.db.seed import get_settings

        return get_settings(self.conn)

    def state(self, settings: dict[str, Any]) -> dict[str, Any]:
        st = self.xai.state(settings)
        return {**st, "provider": PROVIDER, "label": LABEL, "model": fast_model(settings),
                "strong_model": strong_model(settings)}


async def is_available(runner: Any, model: str) -> bool:
    """Works for CloudRunner and for plain runners/fakes that only know `available()`."""
    fn = getattr(runner, "available_for", None)
    return await (fn(model) if fn else runner.available())


async def signoff_model(runner: Any, s: dict[str, Any], lineage: set[str], *, strong_first: bool = True) -> str | None:
    """First Grok sign-off candidate that wrote nothing in this document's lineage and is reachable now."""
    for m in signoff_candidates(s, strong_first=strong_first):
        if tag(m) not in lineage and await is_available(runner, m):
            return m
    return None
