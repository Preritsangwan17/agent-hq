"""Adapter registry: sim, openai_compatible, cloud (Grok), script, http (browser arrives with the mock ATS)."""
from __future__ import annotations

from typing import Any

from hq.adapters.base import Adapter, Cancelled, Deferred, RunContext, RunResult, Services, TransientError

__all__ = ["Adapter", "Cancelled", "Deferred", "RunContext", "RunResult", "Services", "TransientError", "UnavailableAdapter",
           "build_adapters"]


class UnavailableAdapter:
    """Placeholder for adapters that arrive in later phases; tasks routed here fail (and retry) loudly."""

    def __init__(self, name: str, phase: str):
        self.name = name
        self.phase = phase

    async def health(self) -> dict[str, Any]:
        return {"ok": False, "reason": f"{self.name} adapter arrives in phase {self.phase}"}

    async def run(self, task: dict[str, Any], ctx: RunContext) -> RunResult:
        raise TransientError(f"{self.name} adapter is not available yet (phase {self.phase})")


def build_adapters(**sim_kwargs: Any) -> dict[str, Any]:
    from hq.adapters.cloud import CloudAdapter
    from hq.adapters.http import HttpAdapter
    from hq.adapters.openai_compatible import OpenAICompatibleAdapter
    from hq.adapters.script import ScriptAdapter
    from hq.adapters.sim import SimAdapter

    return {
        "sim": SimAdapter(**sim_kwargs),
        "openai_compatible": OpenAICompatibleAdapter(),
        "cloud": CloudAdapter(),
        "script": ScriptAdapter(),
        "http": HttpAdapter(),
        "browser": UnavailableAdapter("browser", "c"),
    }
