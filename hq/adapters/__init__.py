"""Adapter registry. Phase (a) ships only the `sim` adapter; others report themselves unavailable."""
from __future__ import annotations

from typing import Any

from hq.adapters.base import Adapter, Cancelled, RunContext, RunResult, TransientError

__all__ = ["Adapter", "Cancelled", "RunContext", "RunResult", "TransientError", "UnavailableAdapter",
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
    from hq.adapters.sim import SimAdapter

    return {
        "sim": SimAdapter(**sim_kwargs),
        "openai_compatible": UnavailableAdapter("openai_compatible", "b"),
        "claude_code": UnavailableAdapter("claude_code", "b"),
        "script": UnavailableAdapter("script", "b"),
        "http": UnavailableAdapter("http", "e"),
        "browser": UnavailableAdapter("browser", "c"),
    }
