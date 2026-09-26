"""The worker's asyncio orchestrator (CONTRACT §7): commands, pause, dispatch with atomic leases and heartbeats,
retries with backoff, watchdog, interval/cron scheduler, worker heartbeat and agent status upkeep."""
from __future__ import annotations

import asyncio
import logging
import os
import random
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from croniter import croniter

from hq import settings as paths
from hq.adapters import RunContext, RunResult, build_adapters
from hq.adapters.base import Cancelled
from hq.agents.registry import Registry
from hq.agents.schema import RESERVED_SIDE_EFFECTS, SIDE_EFFECT_OWNERS, AgentConfig, is_side_effect_family
from hq.db import repo, serializers
from hq.db.conn import connect, dumps, tx
from hq.db.migrate import migrate
from hq.db.seed import get_settings, seed_settings, set_settings
from hq.pipeline.state import next_tasks, priority_for
from hq.util.ids import new_id
from hq.util.timeutil import IST, now_iso, parse_iso, to_iso, today_ist, utcnow
from hq.worker import queue
from hq.worker.effects import apply_effects

log = logging.getLogger("hq.worker")

ERROR_STATUS_S = 30.0        # how long an agent shows `error` after a failed run
PAUSE_GRACE_S = 5.0          # cooperative-cancel grace before a hard asyncio cancel
SIM_INTERVAL_JITTER = (0.42, 1.0)  # sim scout: "every 25–60 s" for a 1-minute schedule


@dataclass
class Run:
    task: dict[str, Any]
    agent: AgentConfig
    run_id: str
    started: float = field(default_factory=time.monotonic)
    last_beat: float = field(default_factory=time.monotonic)
    aio: asyncio.Task | None = None
    hard_reason: str | None = None
    cancel_seen_at: float | None = None

    def beat(self) -> None:
        self.last_beat = time.monotonic()


class Worker:
    def __init__(self, *, conn: sqlite3.Connection | None = None, agents_dir: Path | None = None,
                 adapters: dict[str, Any] | None = None, loop_interval: float = 0.5, lease_s: float = queue.LEASE_S,
                 heartbeat_s: float = queue.HEARTBEAT_S, watchdog_s: float = 5.0, stale_agent_s: float = 60.0,
                 worker_heartbeat_s: float = 10.0, backoff: Callable[[int], float] | None = None,
                 sim_kwargs: dict[str, Any] | None = None, watch: bool = True, schedule: bool = True):
        self.conn = conn or connect()
        migrate(self.conn)
        with tx(self.conn):
            seed_settings(self.conn)
        self.registry = Registry(agents_dir or paths.AGENTS_DIR, self.conn)
        self.adapters = adapters or build_adapters(**(sim_kwargs or {}))
        self.loop_interval = loop_interval
        self.lease_s = lease_s
        self.heartbeat_s = heartbeat_s
        self.watchdog_s = watchdog_s
        self.stale_agent_s = stale_agent_s
        self.worker_heartbeat_s = worker_heartbeat_s
        self.backoff = backoff or queue.backoff_seconds
        self.watch_enabled = watch
        self.schedule_enabled = schedule
        self.settings: dict[str, Any] = get_settings(self.conn)
        self.state: dict[str, dict[str, Any]] = {}      # agent_id → {enabled, paused, status}
        self.running: dict[str, Run] = {}
        self.cancelled_tasks: set[str] = set()
        self.stuck: set[str] = set()
        self.error_until: dict[str, float] = {}
        self.interval_factor: dict[str, float] = {}
        self.cron_base: dict[str, Any] = {}
        self.stop_event = asyncio.Event()
        self.stopping = False
        self._rescan = True
        self._last_watchdog = 0.0
        self._last_heartbeat = 0.0
        self._last_retention = 0.0
        self.worker_id = f"worker-{os.getpid()}"

    # ── lifecycle ───────────────────────────────────────────────────────────────────────────────────
    def startup(self) -> None:
        with tx(self.conn):
            orphans = queue.recover_orphans(self.conn)
            self.conn.execute("UPDATE agent_live SET now_line=NULL, progress=NULL, current_task_id=NULL, "
                              "opportunity_id=NULL, tok_s=NULL, seq=seq+1, updated_at=?", (now_iso(),))
            repo.emit(self.conn, "worker.started",
                      f"Worker started (pid {os.getpid()})" + (f"; requeued {len(orphans)} orphaned task(s)"
                                                               if orphans else ""),
                      data={"pid": os.getpid(), "requeued": len(orphans)})
        self.registry.scan(self._running_counts())
        self._rescan = False
        self._refresh_state()
        self._worker_heartbeat()

    def stop(self) -> None:
        self.stop_event.set()

    async def run(self) -> None:
        self.startup()
        watcher = None
        if self.watch_enabled:
            watcher = asyncio.create_task(self.registry.watch(self._request_rescan, self.stop_event))
        try:
            while not self.stop_event.is_set():
                try:
                    await self.tick()
                except sqlite3.OperationalError as exc:  # e.g. database locked beyond busy_timeout; try again
                    log.warning("tick failed: %s", exc)
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=self.loop_interval)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.shutdown()
            if watcher:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)

    async def shutdown(self) -> None:
        self.stopping = True
        deadline = time.monotonic() + PAUSE_GRACE_S
        while self.running and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        for run in list(self.running.values()):
            run.hard_reason = run.hard_reason or "worker shutting down"
            if run.aio:
                run.aio.cancel()
        pending = [r.aio for r in self.running.values() if r.aio]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        with tx(self.conn):
            set_settings(self.conn, {"worker_heartbeat_at": None}, by="worker")
            repo.emit(self.conn, "worker.stopped", f"Worker stopped (pid {os.getpid()})", data={"pid": os.getpid()})

    def _request_rescan(self) -> None:
        self._rescan = True

    # ── the loop ────────────────────────────────────────────────────────────────────────────────────
    async def tick(self) -> None:
        self._consume_commands()
        self.settings = get_settings(self.conn)
        if self._rescan:
            self._rescan = False
            self.registry.scan(self._running_counts())
        self._refresh_state()
        self._enforce_cancellations()
        if not self.settings.get("global_pause"):
            if self.schedule_enabled:
                self._schedule()
            self._dispatch()
        now = time.monotonic()
        if now - self._last_watchdog >= self.watchdog_s:
            self._last_watchdog = now
            self._watchdog()
        if now - self._last_heartbeat >= self.worker_heartbeat_s:
            self._worker_heartbeat()
        if now - self._last_retention >= 3600:
            self._last_retention = now
            self._retention()
        self._update_statuses()

    def _consume_commands(self) -> None:
        for cmd in repo.pending_commands(self.conn):
            kind, payload = cmd["kind"], cmd.get("payload_json") or {}
            result: dict[str, Any] = {"ok": True}
            if kind == "cancel_task":
                task_id = payload.get("task_id")
                self.cancelled_tasks.add(task_id)
                with tx(self.conn):
                    if queue.cancel(self.conn, task_id, "cancelled by Prerit"):
                        result["cancelled"] = task_id
            elif kind == "sim_reset":
                live_opps = {r["id"] for r in self.conn.execute("SELECT id FROM opportunities")}
                for run in self.running.values():
                    opp = run.task.get("opportunity_id")
                    if opp and opp not in live_opps:
                        self.cancelled_tasks.add(run.task["id"])
            elif kind in ("rescan_agents", "agent_changed"):
                self._rescan = True
            elif kind not in ("pause_all", "resume_all", "freeze_outbound", "settings_changed"):
                result = {"ok": False, "ignored": kind}
            with tx(self.conn):
                repo.consume_command(self.conn, cmd["id"], result)

    def _refresh_state(self) -> None:
        self.state = {r["id"]: {"enabled": bool(r["enabled"]), "paused": bool(r["paused"]), "status": r["status"]}
                      for r in repo.agent_rows(self.conn)}

    def _running_counts(self) -> dict[str, int]:
        return dict(Counter(r.agent.id for r in self.running.values()))

    # ── cancellation ────────────────────────────────────────────────────────────────────────────────
    def cancel_reason(self, task_id: str, agent_id: str, capability: str) -> str | None:
        if self.stopping:
            return "worker shutting down"
        if self.settings.get("global_pause"):
            return "PAUSE ALL"
        st = self.state.get(agent_id)
        if st is None:
            return "agent removed"
        if not st["enabled"]:
            return "agent disabled"
        if st["paused"]:
            return "agent paused"
        if task_id in self.cancelled_tasks:
            return "task cancelled"
        if capability in RESERVED_SIDE_EFFECTS and self.settings.get("freeze_outbound"):
            return "outbound frozen"
        return None

    def _enforce_cancellations(self) -> None:
        now = time.monotonic()
        for run in list(self.running.values()):
            reason = self.cancel_reason(run.task["id"], run.agent.id, run.task["capability"])
            if reason is None:
                run.cancel_seen_at = None
                continue
            run.cancel_seen_at = run.cancel_seen_at or now
            if now - run.cancel_seen_at > PAUSE_GRACE_S and run.aio and not run.aio.done():
                run.hard_reason = reason
                run.aio.cancel()

    # ── dispatch ────────────────────────────────────────────────────────────────────────────────────
    def paused_capabilities(self) -> set[str]:
        """Side-effect capabilities parked system-wide because an owning agent is paused or disabled."""
        parked: set[str] = set()
        for agent_id, cfg in self.registry.configs.items():
            st = self.state.get(agent_id)
            if st is None or not cfg.side_effects:
                continue
            if st["paused"] or not st["enabled"]:
                parked.update(c for c in cfg.capabilities if is_side_effect_family(c))
        if self.settings.get("freeze_outbound"):
            parked.update(RESERVED_SIDE_EFFECTS)
        return parked

    def _can_take(self, cfg: AgentConfig, capability: str, load: Counter) -> bool:
        st = self.state.get(cfg.id)
        if st is None or not st["enabled"] or st["paused"] or cfg.id in self.registry.draining:
            return False
        if capability not in cfg.capabilities or load[cfg.id] >= cfg.concurrency:
            return False
        if capability in RESERVED_SIDE_EFFECTS and not (cfg.builtin and cfg.id in SIDE_EFFECT_OWNERS):
            return False  # defence in depth: the loader already rejects this
        if cfg.adapter == "sim" and not self.settings.get("sim_enabled", True):
            return False
        return cfg.adapter in self.adapters

    def _dispatch(self) -> None:
        parked = self.paused_capabilities()
        load = Counter(self._running_counts())
        for task in queue.ready_tasks(self.conn):
            cap = task["capability"]
            if cap in parked:
                continue
            candidates = [c for c in self.registry.configs.values() if self._can_take(c, cap, load)]
            if not candidates:
                continue
            pick = min(candidates, key=lambda c: (load[c.id] / c.concurrency, c.cost_tier != "local", c.id))
            if queue.try_lease(self.conn, task["id"], pick.id, self.lease_s):
                load[pick.id] += 1
                self._start(task, pick)

    def _start(self, task: dict[str, Any], cfg: AgentConfig) -> None:
        run = Run(task=task, agent=cfg, run_id=new_id())
        self.running[task["id"]] = run
        self.stuck.discard(cfg.id)
        run.aio = asyncio.create_task(self._execute(run), name=f"run:{cfg.id}:{task['capability']}")

    def likely_agent(self, capability: str) -> str | None:
        load = Counter(self._running_counts())
        options = [c for c in self.registry.configs.values()
                   if capability in c.capabilities and self.state.get(c.id, {}).get("enabled")]
        if not options:
            return None
        return min(options, key=lambda c: (self.state[c.id]["paused"], load[c.id] / c.concurrency, c.id)).id

    # ── one run ─────────────────────────────────────────────────────────────────────────────────────
    def _opp_label(self, opp_id: str | None) -> str:
        if not opp_id:
            return ""
        row = self.conn.execute("SELECT company_name, title FROM opportunities WHERE id=?", (opp_id,)).fetchone()
        return f" — {row['company_name']} · {row['title']}" if row else ""

    async def _execute(self, run: Run) -> None:
        task, cfg = run.task, run.agent
        cap, opp_id = task["capability"], task.get("opportunity_id")
        started_iso = now_iso()
        with tx(self.conn):
            queue.mark_running(self.conn, task["id"])
            self.conn.execute(
                "INSERT INTO agent_runs(id, task_id, agent_id, adapter, model_id, status, started_at, input_json) "
                "VALUES (?,?,?,?,?, 'running', ?, ?)",
                (run.run_id, task["id"], cfg.id, cfg.adapter, cfg.model, started_iso,
                 dumps({"capability": cap, "opportunity_id": opp_id, "payload": task.get("payload") or {},
                        "attempt": task["attempts"] + 1})))
            repo.emit(self.conn, "task.leased", f"{cfg.name} picked up {cap}{self._opp_label(opp_id)}",
                      agent_id=cfg.id, opportunity_id=opp_id, task_id=task["id"],
                      data={"task_id": task["id"], "capability": cap, "agent_id": cfg.id,
                            "attempt": task["attempts"] + 1})
            repo.set_live(self.conn, cfg.id, now_line=f"Starting {cap}…", progress=0.0, current_task_id=task["id"],
                          opportunity_id=opp_id, heartbeat_at=now_iso(), tok_s=None)
        ctx = RunContext(conn=self.conn, task=task, agent=cfg, run_id=run.run_id, settings=dict(self.settings),
                         cancel_reason=lambda: self.cancel_reason(task["id"], cfg.id, cap), on_heartbeat=run.beat)
        hb = asyncio.create_task(self._lease_heartbeat(task["id"]))
        t0 = time.monotonic()
        try:
            try:
                adapter = self.adapters[cfg.adapter]
                result = await adapter.run(task, ctx)
            except Cancelled as exc:
                self._on_cancelled(run, exc.reason, t0)
            except asyncio.CancelledError:
                reason = run.hard_reason or "worker shutting down"
                if reason.startswith("stuck"):
                    self._on_failed(run, reason, t0, ctx.model_id)
                else:
                    self._on_cancelled(run, reason, t0)
            except Exception as exc:  # adapter failure → retry/backoff
                self._on_failed(run, f"{type(exc).__name__}: {exc}", t0, ctx.model_id)
            else:
                try:
                    self._on_succeeded(run, result, t0)
                except Exception as exc:
                    log.exception("commit failed for %s", task["id"])
                    self._on_failed(run, f"commit failed: {type(exc).__name__}: {exc}", t0, result.model_id)
        finally:
            hb.cancel()
            self.running.pop(task["id"], None)
            self.cancelled_tasks.discard(task["id"])
            if run.hard_reason and run.hard_reason.startswith("stuck"):
                self.stuck.discard(cfg.id)  # healed: the task was cancelled and will retry; `error` shows briefly
            if not any(r.agent.id == cfg.id for r in self.running.values()):
                try:
                    repo.set_live(self.conn, cfg.id, now_line=None, progress=None, current_task_id=None,
                                  opportunity_id=None, tok_s=None)
                except sqlite3.Error:
                    pass

    async def _lease_heartbeat(self, task_id: str) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_s)
            queue.extend_lease(self.conn, task_id, self.lease_s)

    def _finish_run(self, run: Run, status: str, t0: float, *, result: RunResult | None = None,
                    error: str | None = None, model_id: str | None = None) -> None:
        r = result or RunResult()
        self.conn.execute(
            "UPDATE agent_runs SET status=?, error=?, model_id=COALESCE(?, model_id), prompt_tokens=?, "
            "completion_tokens=?, tok_s=?, ttft_ms=?, cost_usd=?, duration_ms=?, finished_at=?, output_json=? "
            "WHERE id=?",
            (status, error, r.model_id or model_id, r.prompt_tokens, r.completion_tokens, r.tok_s, r.ttft_ms,
             r.cost_usd, int((time.monotonic() - t0) * 1000), now_iso(),
             dumps(r.output) if result is not None else None, run.run_id))

    def _bump_counters(self, agent_id: str, *, tasks: int = 0, errors: int = 0, tokens: int = 0,
                       last_error: str | None = None) -> None:
        today = today_ist().isoformat()
        self.conn.execute(
            "UPDATE agents SET "
            "tasks_today = CASE WHEN counters_date=? THEN tasks_today ELSE 0 END + ?, "
            "errors_today = CASE WHEN counters_date=? THEN errors_today ELSE 0 END + ?, "
            "tokens_today = CASE WHEN counters_date=? THEN tokens_today ELSE 0 END + ?, "
            "counters_date=?, last_error=COALESCE(?, last_error), updated_at=? WHERE id=?",
            (today, tasks, today, errors, today, tokens, today, last_error, now_iso(), agent_id))

    def _on_succeeded(self, run: Run, result: RunResult, t0: float) -> None:
        task, cfg = run.task, run.agent
        cap = task["capability"]
        with tx(self.conn):
            queue.complete(self.conn, task["id"], result.output)
            outcome = apply_effects(self.conn, result.effects, agent_id=cfg.id, task_id=task["id"],
                                    run_id=run.run_id, opportunity_id=task.get("opportunity_id"))
            stage_changes: dict[str, tuple[str, str]] = {}
            if not result.output.get("noop"):
                targets = result.opp_results or (
                    [(task["opportunity_id"], result.output)] if task.get("opportunity_id") else [])
                for opp_id, res in targets:
                    self._transition(task, cfg, opp_id, res, stage_changes)
            for opp_id in outcome.created_opps:
                opp = serializers.opp_summary_by_id(self.conn, opp_id)
                if opp:
                    repo.emit(self.conn, "opp.created", f"New: {opp['company_name']} — {opp['title']} "
                              f"({opp['city']}, {opp['country_iso2']})", agent_id=cfg.id, opportunity_id=opp_id,
                              task_id=task["id"], data={"opp": opp})
            for opp_id, (old, new) in stage_changes.items():
                opp = serializers.opp_summary_by_id(self.conn, opp_id)
                if opp:
                    reason = f" ({opp['stage_reason']})" if opp.get("stage_reason") and new == "filtered" else ""
                    repo.emit(self.conn, "opp.stage", f"{opp['company_name']} — {opp['title']}: {old} → {new}{reason}",
                              level="alert" if new in ("interview", "offer") else "info", agent_id=cfg.id,
                              opportunity_id=opp_id, task_id=task["id"], data={"opp": opp, "from": old, "to": new})
            for opp_id in outcome.touched_opps - set(stage_changes) - set(outcome.created_opps):
                opp = serializers.opp_summary_by_id(self.conn, opp_id)
                if opp:
                    repo.emit(self.conn, "opp.updated", f"Updated {opp['company_name']} — {opp['title']}",
                              level="debug", agent_id=cfg.id, opportunity_id=opp_id, task_id=task["id"],
                              data={"opp": opp})
            self._finish_run(run, "succeeded", t0, result=result)
            tokens = (result.prompt_tokens or 0) + (result.completion_tokens or 0)
            self._bump_counters(cfg.id, tasks=1, tokens=tokens)
            repo.emit(self.conn, "task.succeeded", f"{cfg.name} ✓ {result.summary or cap}", agent_id=cfg.id,
                      opportunity_id=task.get("opportunity_id"), task_id=task["id"],
                      data={"task_id": task["id"], "capability": cap, "agent_id": cfg.id,
                            "attempt": task["attempts"] + 1, "model_id": result.model_id, "tok_s": result.tok_s,
                            "tokens": tokens or None, "cost_usd": result.cost_usd})
        self.error_until.pop(cfg.id, None)

    def _transition(self, task: dict[str, Any], cfg: AgentConfig, opp_id: str, res: dict[str, Any],
                    stage_changes: dict[str, tuple[str, str]]) -> None:
        opp = self.conn.execute("SELECT stage, stage_override FROM opportunities WHERE id=?", (opp_id,)).fetchone()
        if opp is None:
            return
        if opp["stage_override"]:
            repo.emit(self.conn, "log", "Stage was set by Prerit — pipeline leaves this item alone", level="debug",
                      agent_id=cfg.id, opportunity_id=opp_id, task_id=task["id"])
            return
        old = opp["stage"]
        new, specs = next_tasks(old, task["capability"], res)
        if new != old:
            values: dict[str, Any] = {"stage": new}
            if res.get("stage_reason"):
                values["stage_reason"] = res["stage_reason"]
            repo.update_opportunity(self.conn, opp_id, values)
            prev = stage_changes.get(opp_id)
            stage_changes[opp_id] = (prev[0] if prev else old, new)
        for spec in specs:
            new_task = queue.enqueue(
                self.conn, spec.capability, payload=spec.payload, opportunity_id=opp_id,
                priority=spec.effective_priority, delay_s=spec.delay_s,
                idempotency_key=f"{task['id']}:{opp_id}:{spec.capability}", parent_task_id=task["id"],
                source_agent=cfg.id)
            if not new_task:
                continue
            to_agent = self.likely_agent(spec.capability)
            if to_agent and to_agent != cfg.id:
                repo.emit(self.conn, "task.handoff", f"{cfg.name} → {to_agent}: {spec.capability}", level="debug",
                          agent_id=cfg.id, opportunity_id=opp_id, task_id=new_task,
                          data={"from_agent": cfg.id, "to_agent": to_agent, "capability": spec.capability,
                                "opportunity_id": opp_id})

    def _on_failed(self, run: Run, error: str, t0: float, model_id: str | None = None) -> None:
        task, cfg = run.task, run.agent
        with tx(self.conn):
            queue.fail(self.conn, task["id"], error, agent_id=cfg.id, backoff=self.backoff)
            self._finish_run(run, "failed", t0, error=error[:2000], model_id=model_id)
            self._bump_counters(cfg.id, errors=1, last_error=error[:500])
        self.error_until[cfg.id] = time.monotonic() + ERROR_STATUS_S

    def _on_cancelled(self, run: Run, reason: str, t0: float) -> None:
        task, cfg = run.task, run.agent
        with tx(self.conn):
            if reason == "task cancelled" or reason == "agent removed":
                queue.cancel(self.conn, task["id"], reason)
                what = "task cancelled"
            else:
                queue.requeue(self.conn, task["id"])
                what = "task requeued"
            self._finish_run(run, "cancelled", t0, error=reason)
            repo.emit(self.conn, "log", f"{cfg.name} stopped {task['capability']} ({reason}); {what}",
                      agent_id=cfg.id, opportunity_id=task.get("opportunity_id"), task_id=task["id"],
                      data={"task_id": task["id"], "reason": reason})

    # ── scheduler ───────────────────────────────────────────────────────────────────────────────────
    def _schedule(self) -> None:
        now = utcnow()
        speed = min(4.0, max(0.25, float(self.settings.get("sim_speed", 1.0) or 1.0)))
        for cfg in list(self.registry.configs.values()):
            if cfg.schedule.mode == "on_demand" or not cfg.schedulable_capabilities:
                continue
            st = self.state.get(cfg.id)
            if not st or not st["enabled"] or st["paused"] or cfg.id in self.registry.draining:
                continue
            if cfg.adapter == "sim" and not self.settings.get("sim_enabled", True):
                continue
            source = f"scheduler:{cfg.id}"
            open_ = self.conn.execute("SELECT 1 FROM tasks WHERE source_agent=? AND status IN "
                                      "('queued','leased','running') LIMIT 1", (source,)).fetchone()
            if open_:
                continue  # coalesce: never stack scheduled runs
            last_iso = self.conn.execute("SELECT MAX(created_at) AS m FROM tasks WHERE source_agent=?",
                                         (source,)).fetchone()["m"]
            last = parse_iso(last_iso)
            if not self._due(cfg, last, now, speed):
                continue
            cap = self._next_schedulable(cfg, source)
            with tx(self.conn):
                queue.enqueue(self.conn, cap, type_="scheduled", payload={"scheduled_by": cfg.id},
                              priority=priority_for(cap), source_agent=source)
            self.interval_factor.pop(cfg.id, None)

    def _due(self, cfg: AgentConfig, last, now, speed: float) -> bool:
        if cfg.schedule.mode == "interval":
            if last is None:
                return True
            seconds = float(cfg.schedule.minutes or 1) * 60
            if cfg.adapter == "sim":
                factor = self.interval_factor.setdefault(cfg.id, random.uniform(*SIM_INTERVAL_JITTER))
                seconds = seconds * factor / speed
            return (now - last).total_seconds() >= seconds
        base = last or self.cron_base.setdefault(cfg.id, now)
        nxt = croniter(cfg.schedule.cron, base.astimezone(IST)).get_next(type(now))
        return nxt <= now

    def _next_schedulable(self, cfg: AgentConfig, source: str) -> str:
        """Round-robin across the agent's schedulable capabilities (the oldest-scheduled goes next)."""
        caps = cfg.schedulable_capabilities
        if len(caps) == 1:
            return caps[0]
        rows = {r["capability"]: r["m"] for r in self.conn.execute(
            "SELECT capability, MAX(created_at) AS m FROM tasks WHERE source_agent=? GROUP BY capability", (source,))}
        return min(caps, key=lambda c: (rows.get(c) or "", caps.index(c)))

    # ── watchdog / heartbeat / upkeep ───────────────────────────────────────────────────────────────
    def _watchdog(self) -> None:
        with tx(self.conn):
            for t in queue.expired_leases(self.conn):
                if t["id"] in self.running:
                    queue.extend_lease(self.conn, t["id"], self.lease_s)
                    continue
                queue.fail(self.conn, t["id"], "lease expired (worker lost the task)", agent_id=t["lease_owner"],
                           backoff=self.backoff)
            for need in self.conn.execute("SELECT id FROM needs_prerit WHERE status='snoozed' AND snoozed_until "
                                          "IS NOT NULL AND snoozed_until <= ?", (now_iso(),)).fetchall():
                self.conn.execute("UPDATE needs_prerit SET status='open', snoozed_until=NULL WHERE id=?", (need["id"],))
                n = serializers.need_json(repo.get_need_row(self.conn, need["id"]))
                repo.emit(self.conn, "needs.updated", f"Snooze over: {n['title']}", opportunity_id=n["opportunity_id"],
                          data={"need": n})
        now = time.monotonic()
        for run in list(self.running.values()):
            if now - run.last_beat > self.stale_agent_s and run.aio and not run.aio.done() and not run.hard_reason:
                run.hard_reason = f"stuck: no heartbeat for {int(now - run.last_beat)} s"
                self.stuck.add(run.agent.id)
                with tx(self.conn):
                    self.conn.execute("UPDATE agents SET restarts=restarts+1, updated_at=? WHERE id=?",
                                      (now_iso(), run.agent.id))
                    repo.emit(self.conn, "log", f"{run.agent.name} is stuck ({run.hard_reason}) — cancelling and "
                              "retrying", level="warn", agent_id=run.agent.id, task_id=run.task["id"],
                              opportunity_id=run.task.get("opportunity_id"), data={"reason": run.hard_reason})
                run.aio.cancel()

    def _worker_heartbeat(self) -> None:
        self._last_heartbeat = time.monotonic()
        counts = queue.counts(self.conn)
        with tx(self.conn):
            set_settings(self.conn, {"worker_heartbeat_at": now_iso()}, by="worker")
            repo.emit(self.conn, "worker.heartbeat", "worker alive", level="debug",
                      data={"pid": os.getpid(), "running": len(self.running), "queued": counts.get("queued", 0)})

    def _retention(self) -> None:
        with tx(self.conn):
            self.conn.execute("DELETE FROM events WHERE level='debug' AND ts < ?",
                              (to_iso(utcnow() - timedelta(days=1)),))
            self.conn.execute("DELETE FROM events WHERE ts < ?", (to_iso(utcnow() - timedelta(days=60)),))
            self.conn.execute("DELETE FROM commands WHERE consumed_at IS NOT NULL AND consumed_at < ?",
                              (to_iso(utcnow() - timedelta(days=2)),))

    def _update_statuses(self) -> None:
        running = Counter(self._running_counts())
        now = time.monotonic()
        paused_all = bool(self.settings.get("global_pause"))
        changes = []
        for agent_id, st in self.state.items():
            if not st["enabled"]:
                desired = "disabled"
            elif st["paused"] or paused_all:
                desired = "paused"
            elif agent_id in self.stuck:
                desired = "stuck"
            elif running[agent_id]:
                desired = "working"
            elif self.error_until.get(agent_id, 0) > now:
                desired = "error"
            else:
                desired = "idle"
            if desired != st["status"]:
                changes.append((agent_id, desired))
        if not changes:
            return
        with tx(self.conn):
            for agent_id, desired in changes:
                self.conn.execute("UPDATE agents SET status=?, updated_at=? WHERE id=?", (desired, now_iso(), agent_id))
                self.state[agent_id]["status"] = desired
                cfg = self.registry.configs.get(agent_id)
                name = cfg.name if cfg else agent_id
                repo.emit(self.conn, "agent.status", f"{name}: {desired}",
                          level="warn" if desired in ("error", "stuck") else "debug", agent_id=agent_id,
                          data={"status": desired})
