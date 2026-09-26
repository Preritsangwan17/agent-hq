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


class Deferred(Exception):
    """The task can't run now and should wait without burning an attempt: over the Grok budget or a CLI's window
    (status deferred_budget until midnight IST), waiting for memory (waiting_memory) or rate-limited (queued)."""

    def __init__(self, status: str, until_iso: str, reason: str):
        super().__init__(reason)
        self.status, self.until_iso, self.reason = status, until_iso, reason


@dataclass
class Services:
    """Worker-owned LLM plumbing handed to adapters through the RunContext."""
    router: Any = None      # hq.llm.router.Router
    cloud: Any = None       # hq.llm.cloud.CloudRunner (Claude CLI, Codex CLI, Grok)
    manager: Any = None     # hq.models.manager.ModelManager
    sim: Any = None         # hq.adapters.sim.SimAdapter (simulated opportunities)
    fetcher: Any = None     # hq.pipeline.discover.fetch.Fetcher (polite GETs)
    gmail: Any = None       # hq.gmail.client.GmailClient (or the test fake); None until Gmail is connected


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
                 on_heartbeat: Callable[[], None] | None = None, services: Services | None = None):
        self.services = services or Services()
        self.cost_usd = 0.0
        self.tokens = 0
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

    # ── LLM helpers (phase b) ─────────────────────────────────────────────────────────────────────────
    async def llm(self, role: str, messages: list[dict[str, str]], schema: dict[str, Any] | None, *,
                  now_line: str | None = None, **kw: Any) -> Any:
        """Route to the role's model (local → a different local model → a cloud model when hq.llm.policy allows it).
        Updates the live row with model + tok/s."""
        router = self.services.router
        if router is None:
            raise TransientError("no model router in this worker")
        line = now_line or self._last_line or f"{role}…"

        def on_progress(model_id: str, tok_s: float | None, _: str | None) -> None:
            self.progress(None, line, tok_s=round(tok_s, 1) if tok_s else None, model_id=model_id)

        self.check_cancel()
        res = await router.route(role, messages, schema, agent_id=self.agent.id, task_id=self.task["id"],
                                 parent_run_id=self.run_id, on_progress=on_progress, **kw)
        self.model_id = res.model_id
        self.cost_usd += res.cost_usd or 0.0
        self.tokens += (res.prompt_tokens or 0) + (res.completion_tokens or 0)
        self.progress(None, line, tok_s=res.tok_s, model_id=res.model_id)
        self.check_cancel()
        return res

    async def cloud(self, task_type: str, prompt: str, schema: dict[str, Any], *, system_prompt: str,
                    model: str | None = None, tier: str = "fast", lineage: set[str] | None = None) -> Any:
        """One cloud call: the given model, or the first suitable provider (hq.llm.cloud order: subscription CLIs,
        then Grok). Cloud switched off / nothing reachable → Deferred; Grok over its $ limit → Deferred until
        midnight IST."""
        from hq.llm import cloud, policy
        from hq.llm.errors import CloudError, CloudRateLimited, CloudUnavailable
        from hq.util.timeutil import iso_in
        from hq.worker import budget

        s = self.settings
        if not policy.cloud_on(s):
            raise Deferred("queued", iso_in(3600), "cloud models are switched off (Settings › AI & budget)")
        runner = self.services.cloud
        m = cloud.tag(model) if model else await cloud.pick(runner, s, tier, lineage or set(), conn=self.conn)
        if m is None or runner is None or not await cloud.is_available(runner, m):
            raise Deferred("queued", iso_in(600), "no cloud model reachable right now "
                                                  f"({getattr(runner, 'reason', None) or 'none switched on'})")
        prov = cloud.provider_of(m) or "xai"
        r = budget.reserve(self.conn, task_type, s, run_id=self.run_id, provider=prov)
        if r is None:
            if prov in cloud.SUBSCRIPTIONS:
                raise Deferred("queued", iso_in(1800), f"{cloud.label(m)}: HQ's share of this 5-hour window is used")
            raise Deferred("deferred_budget", budget.to_iso(budget.next_midnight_ist()),
                           "Grok daily budget or call cap reached")
        self.progress(None, f"Asking {cloud.label(m)} ({m.split(':', 1)[-1]})…", model_id=m)
        try:
            res = await runner.run(prompt, schema=schema, system_prompt=system_prompt, model=m,
                                   max_budget_usd=float(s.get("cloud_per_call_cap_usd", 0.5)))
        except CloudError as exc:
            cost = getattr(exc, "cost_usd", None)
            if cost is not None:
                budget.commit(self.conn, r, cost_usd=cost, model=m, subtype=exc.kind)
                self.cost_usd += cost
            else:
                budget.release(self.conn, r)
            if isinstance(exc, CloudRateLimited):
                raise Deferred("queued", iso_in(600 if prov in cloud.SUBSCRIPTIONS else 3600), str(exc)) from exc
            if isinstance(exc, CloudUnavailable):
                raise Deferred("queued", iso_in(600), str(exc)) from exc
            raise
        budget.commit(self.conn, r, cost_usd=res.cost_usd, model=m, input_tokens=res.input_tokens,
                      output_tokens=res.output_tokens, cache_read_tokens=res.cache_read_tokens,
                      cost_source=getattr(res, "cost_source", None),
                      notional_usd=(getattr(res, "raw", None) or {}).get("notional_usd"))
        self.model_id = m
        self.cost_usd += res.cost_usd or 0.0
        return res

    @property
    def _last_line(self) -> str | None:
        row = self.conn.execute("SELECT now_line FROM agent_live WHERE agent_id=?", (self.agent.id,)).fetchone()
        return row["now_line"] if row else None
