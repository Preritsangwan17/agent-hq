"""Adapter protocol and the RunContext every adapter receives (CONTRACT §6/§7).

Adapters are side-effect free with respect to domain tables: they describe the rows to write as `effects` in
their RunResult, and the worker applies them in the same transaction as task success and the pipeline transition.
They may only touch the DB through RunContext helpers (events, live progress, read queries)."""
from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from hq.agents.schema import AgentConfig
from hq.db import repo
from hq.util.timeutil import now_iso


class Cancelled(Exception):
    """Raised by ctx.check_cancel(): global pause, agent pause/disable, task cancelled, outbound frozen, shutdown."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class TransientError(Exception):
    """A failure worth retrying with backoff (network blip, 503, model server restart)."""


@dataclass
class RunResult:
    output: dict[str, Any] = field(default_factory=dict)       # summary; also the input to pipeline.state
    effects: list[dict[str, Any]] = field(default_factory=list)
    opp_results: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # multi-opportunity tasks
    summary: str | None = None                                  # one human line for the task.succeeded event
    model_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tok_s: float | None = None
    ttft_ms: float | None = None
    cost_usd: float | None = None


@runtime_checkable
class Adapter(Protocol):
    name: str

    async def health(self) -> dict[str, Any]: ...

    async def run(self, task: dict[str, Any], ctx: "RunContext") -> RunResult: ...


class RunContext:
    def __init__(self, *, conn: sqlite3.Connection, task: dict[str, Any], agent: AgentConfig, run_id: str,
                 settings: dict[str, Any], cancel_reason: Callable[[], str | None],
                 on_heartbeat: Callable[[], None] | None = None):
        self.conn = conn
        self.task = task
        self.agent = agent
        self.run_id = run_id
        self.settings = settings
        self._cancel_reason = cancel_reason
        self._on_heartbeat = on_heartbeat
        self._last_live = 0.0
        self.model_id: str | None = None

    @property
    def opportunity_id(self) -> str | None:
        return self.task.get("opportunity_id")

    def emit(self, type_: str, message: str, *, level: str = "info", data: Any = None,
             opportunity_id: str | None = None) -> int:
        return repo.emit(self.conn, type_, message, level=level, agent_id=self.agent.id,
                         opportunity_id=opportunity_id or self.opportunity_id, task_id=self.task["id"], data=data)

    def progress(self, pct: float | None, now_line: str | None, *, tok_s: float | None = None,
                 model_id: str | None = None, opportunity_id: str | None = None) -> None:
        """Update the agent's live row (bumps seq → SSE `agent.live`). Also counts as a heartbeat."""
        if model_id:
            self.model_id = model_id
        fields: dict[str, Any] = {
            "now_line": now_line, "progress": None if pct is None else max(0.0, min(1.0, float(pct))),
            "tok_s": tok_s, "heartbeat_at": now_iso(), "current_task_id": self.task["id"],
            "opportunity_id": opportunity_id or self.opportunity_id,
        }
        if self.model_id:
            fields["model_id"] = self.model_id
        repo.set_live(self.conn, self.agent.id, **fields)
        self._last_live = time.monotonic()
        if self._on_heartbeat:
            self._on_heartbeat()

    def heartbeat(self) -> None:
        self.conn.execute("UPDATE agent_live SET heartbeat_at=? WHERE agent_id=?", (now_iso(), self.agent.id))
        if self._on_heartbeat:
            self._on_heartbeat()

    def check_cancel(self) -> None:
        reason = self._cancel_reason()
        if reason:
            raise Cancelled(reason)

    async def sleep(self, seconds: float, step: float = 0.2) -> None:
        """Cooperative sleep: checks for cancellation at least every `step` seconds."""
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            self.check_cancel()
            left = deadline - time.monotonic()
            if left <= 0:
                return
            await asyncio.sleep(min(step, left))

    def query(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        """Read-only helper for adapters."""
        if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
            raise ValueError("RunContext.query is read-only")
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]
