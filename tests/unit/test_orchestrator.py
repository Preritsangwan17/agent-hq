"""Worker/orchestrator behaviour: atomic leases, retries, pause, side-effect capability rules, scheduler,
watchdog, and the pure pipeline state machine."""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest
from conftest import drive, write_agent

from hq.adapters.base import RunContext, RunResult
from hq.agents.schema import AgentConfig
from hq.db.conn import connect, tx
from hq.db.seed import set_settings
from hq.pipeline.state import TaskSpec, next_tasks
from hq.util.timeutil import parse_iso, utcnow
from hq.worker import queue
from hq.worker.orchestrator import Worker


class FakeAdapter:
    """Configurable adapter: sleeps cooperatively, optionally fails, records what it ran."""

    name = "sim"

    def __init__(self, seconds: float = 0.05, fail: bool = False, cooperative: bool = True):
        self.seconds = seconds
        self.fail = fail
        self.cooperative = cooperative
        self.started: list[tuple[str, str]] = []
        self.cancelled_at: float | None = None

    async def health(self) -> dict[str, Any]:
        return {"ok": True}

    async def run(self, task: dict[str, Any], ctx: RunContext) -> RunResult:
        self.started.append((ctx.agent.id, task["capability"]))
        ctx.progress(0.1, f"working on {task['capability']}")
        try:
            if self.cooperative:
                await ctx.sleep(self.seconds, step=0.05)
            else:
                await asyncio.sleep(self.seconds)
        except BaseException:
            self.cancelled_at = time.monotonic()
            raise
        if self.fail:
            raise RuntimeError("boom (test)")
        return RunResult(output={"ok": True}, summary="done", model_id="sim:test", prompt_tokens=10,
                         completion_tokens=5)


def make_worker(adapter: FakeAdapter, **kw: Any) -> Worker:
    kw.setdefault("loop_interval", 0.05)
    kw.setdefault("watch", False)
    kw.setdefault("schedule", False)
    return Worker(adapters={"sim": adapter}, **kw)


def statuses(conn, ids):
    return {r["id"]: r["status"] for r in conn.execute(
        f"SELECT id, status FROM tasks WHERE id IN ({','.join('?' * len(ids))})", ids)}


# ── leases ───────────────────────────────────────────────────────────────────────────────────────────
def test_leases_are_atomic_under_concurrent_dispatch(db):
    with tx(db):
        ids = [queue.enqueue(db, "verify.link", emit_event=False) for _ in range(60)]
    barrier = threading.Barrier(8)
    leased: list[list[str]] = []
    lock = threading.Lock()

    def dispatcher(n: int) -> None:
        conn = connect()
        barrier.wait()
        mine = [tid for tid in ids if queue.try_lease(conn, tid, f"agent{n}")]
        conn.close()
        with lock:
            leased.append(mine)

    threads = [threading.Thread(target=dispatcher, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    flat = [tid for batch in leased for tid in batch]
    assert len(flat) == len(ids) == len(set(flat))
    owners = {r["lease_owner"] for r in db.execute("SELECT lease_owner FROM tasks")}
    assert all(o and o.startswith("agent") for o in owners)
    assert {r["status"] for r in db.execute("SELECT status FROM tasks")} == {"leased"}


def test_idempotency_key_prevents_duplicates(db):
    with tx(db):
        a = queue.enqueue(db, "parse.job", idempotency_key="k1")
        b = queue.enqueue(db, "parse.job", idempotency_key="k1")
    assert a and b is None


# ── retries ──────────────────────────────────────────────────────────────────────────────────────────
def test_fail_backs_off_then_goes_dead(db):
    with tx(db):
        tid = queue.enqueue(db, "verify.pay", max_attempts=3)
    delays = []
    for expected in ("retry", "retry", "dead"):
        before = utcnow()
        with tx(db):
            assert queue.fail(db, tid, "HTTP 503", agent_id="verifier") == expected
        row = db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if expected == "retry":
            delays.append((parse_iso(row["not_before"]) - before).total_seconds())
            assert row["status"] == "queued"
    assert 9.5 <= delays[0] <= 12.5 and 19.5 <= delays[1] <= 24.5  # 2^n·5 s + ≤20 % jitter
    row = db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "dead" and row["attempts"] == 3
    types = [(r["type"], r["level"]) for r in db.execute("SELECT type, level FROM events WHERE task_id=? ORDER BY id",
                                                        (tid,))]
    assert types.count(("task.retry", "warn")) == 2 and ("task.dead", "error") in types


def test_backoff_is_capped_at_one_hour():
    assert queue.backoff_seconds(30) == 3600


async def test_worker_retries_failed_runs_until_dead(hq_env, db):
    write_agent(hq_env.agents, "checker", capabilities=["verify.link"])
    adapter = FakeAdapter(fail=True)
    w = make_worker(adapter, backoff=lambda attempts: 0.0)
    w.startup()
    with tx(db):
        tid = queue.enqueue(db, "verify.link")
    assert await drive(w, lambda: statuses(db, [tid])[tid] == "dead", timeout=10)
    await w.shutdown()
    runs = db.execute("SELECT status FROM agent_runs WHERE task_id=?", (tid,)).fetchall()
    assert [r["status"] for r in runs] == ["failed"] * 4
    agent = db.execute("SELECT errors_today, last_error FROM agents WHERE id='checker'").fetchone()
    assert agent["errors_today"] == 4 and "boom" in agent["last_error"]


async def test_success_records_run_and_counters(hq_env, db):
    write_agent(hq_env.agents, "checker", capabilities=["verify.link"])
    w = make_worker(FakeAdapter())
    w.startup()
    with tx(db):
        tid = queue.enqueue(db, "verify.link")
    assert await drive(w, lambda: statuses(db, [tid])[tid] == "succeeded")
    await w.shutdown()
    run = db.execute("SELECT * FROM agent_runs WHERE task_id=?", (tid,)).fetchone()
    assert run["status"] == "succeeded" and run["model_id"] == "sim:test" and run["duration_ms"] >= 0
    assert run["input_json"] and run["output_json"]
    agent = db.execute("SELECT tasks_today, tokens_today FROM agents WHERE id='checker'").fetchone()
    assert agent["tasks_today"] == 1 and agent["tokens_today"] == 15
    types = [r["type"] for r in db.execute("SELECT type FROM events WHERE task_id=?", (tid,))]
    assert "task.leased" in types and "task.succeeded" in types


# ── pause ────────────────────────────────────────────────────────────────────────────────────────────
async def test_global_pause_stops_leasing_and_cancels_running_within_a_second(hq_env, db):
    write_agent(hq_env.agents, "slowpoke", capabilities=["verify.link"], concurrency=2)
    adapter = FakeAdapter(seconds=30)
    w = make_worker(adapter, loop_interval=0.1)
    w.startup()
    with tx(db):
        tid = queue.enqueue(db, "verify.link")
    assert await drive(w, lambda: statuses(db, [tid])[tid] == "running", timeout=5)

    other = connect()  # the API process's connection
    with tx(other):
        set_settings(other, {"global_pause": True}, by="prerit")
        later = queue.enqueue(other, "verify.link")
    paused_at = time.monotonic()
    assert await drive(w, lambda: statuses(db, [tid])[tid] == "queued" and not w.running, timeout=3)
    assert adapter.cancelled_at is not None and adapter.cancelled_at - paused_at < 1.0
    run = db.execute("SELECT status, error FROM agent_runs WHERE task_id=?", (tid,)).fetchone()
    assert run["status"] == "cancelled" and run["error"] == "PAUSE ALL"

    leased_before = db.execute("SELECT COUNT(*) FROM events WHERE type='task.leased'").fetchone()[0]
    for _ in range(10):
        await w.tick()
        await asyncio.sleep(0.02)
    assert db.execute("SELECT COUNT(*) FROM events WHERE type='task.leased'").fetchone()[0] == leased_before
    assert statuses(db, [tid, later]) == {tid: "queued", later: "queued"}
    assert db.execute("SELECT status FROM agents WHERE id='slowpoke'").fetchone()[0] == "paused"

    with tx(other):
        set_settings(other, {"global_pause": False}, by="prerit")
    adapter.seconds = 0.05
    assert await drive(w, lambda: set(statuses(db, [tid, later]).values()) == {"succeeded"}, timeout=5)
    await w.shutdown()
    other.close()


async def test_pausing_an_agent_cancels_its_run_and_requeues(hq_env, db):
    write_agent(hq_env.agents, "slowpoke", capabilities=["verify.link"])
    adapter = FakeAdapter(seconds=30)
    w = make_worker(adapter)
    w.startup()
    with tx(db):
        tid = queue.enqueue(db, "verify.link")
    assert await drive(w, lambda: statuses(db, [tid])[tid] == "running")
    db.execute("UPDATE agents SET paused=1 WHERE id='slowpoke'")
    assert await drive(w, lambda: statuses(db, [tid])[tid] == "queued" and not w.running, timeout=3)
    await w.shutdown()


# ── side effects ─────────────────────────────────────────────────────────────────────────────────────
async def test_pausing_applicant_parks_apply_capabilities_system_wide(hq_env, db):
    write_agent(hq_env.agents, "applicant", builtin=True, capabilities=["apply.email_send", "apply.manual_pack"])
    write_agent(hq_env.agents, "helper", capabilities=["apply.manual_pack", "summarize"])
    adapter = FakeAdapter()
    w = make_worker(adapter)
    w.startup()
    db.execute("UPDATE agents SET paused=1 WHERE id='applicant'")
    with tx(db):
        pack = queue.enqueue(db, "apply.manual_pack")
        send = queue.enqueue(db, "apply.email_send")
        other = queue.enqueue(db, "summarize")
    assert await drive(w, lambda: statuses(db, [other])[other] == "succeeded")
    for _ in range(5):
        await w.tick()
    assert statuses(db, [pack, send]) == {pack: "queued", send: "queued"}  # waiting, never rerouted to helper
    assert "apply.manual_pack" in w.paused_capabilities() and "apply.email_send" in w.paused_capabilities()
    assert all(agent != "helper" or cap != "apply.manual_pack" for agent, cap in adapter.started)

    db.execute("UPDATE agents SET paused=0 WHERE id='applicant'")
    assert await drive(w, lambda: set(statuses(db, [pack, send]).values()) == {"succeeded"})
    assert ("applicant", "apply.email_send") in adapter.started
    await w.shutdown()


async def test_freeze_outbound_holds_reserved_capabilities(hq_env, db):
    write_agent(hq_env.agents, "applicant", builtin=True, capabilities=["apply.email_send", "apply.manual_pack"])
    w = make_worker(FakeAdapter())
    w.startup()
    with tx(db):
        set_settings(db, {"freeze_outbound": True})
        send = queue.enqueue(db, "apply.email_send")
        pack = queue.enqueue(db, "apply.manual_pack")
    assert await drive(w, lambda: statuses(db, [pack])[pack] == "succeeded")
    assert statuses(db, [send])[send] == "queued"
    await w.shutdown()


async def test_dispatcher_never_routes_reserved_caps_to_non_builtin_agents(hq_env, db):
    """Defence in depth: even a config that slipped past the loader cannot take a reserved capability."""
    write_agent(hq_env.agents, "rogue", capabilities=["summarize"])
    adapter = FakeAdapter()
    w = make_worker(adapter)
    w.startup()
    w.registry.configs["rogue"] = AgentConfig.model_construct(
        **{**w.registry.configs["rogue"].model_dump(), "capabilities": ["apply.email_send"]})
    with tx(db):
        send = queue.enqueue(db, "apply.email_send")
    for _ in range(5):
        await w.tick()
        await asyncio.sleep(0.01)
    assert statuses(db, [send])[send] == "queued" and not adapter.started
    await w.shutdown()


# ── scheduler / watchdog ─────────────────────────────────────────────────────────────────────────────
async def test_scheduler_creates_one_coalesced_task_per_interval(hq_env, db):
    write_agent(hq_env.agents, "scout", adapter="sim", capabilities=["discover.ats", "discover.program_page"],
                schedule={"mode": "interval", "minutes": 60})
    adapter = FakeAdapter(seconds=30)
    w = make_worker(adapter, schedule=True)
    w.startup()
    for _ in range(6):
        await w.tick()
        await asyncio.sleep(0.02)
    rows = db.execute("SELECT capability, status FROM tasks WHERE source_agent='scheduler:scout'").fetchall()
    assert len(rows) == 1 and rows[0]["capability"] == "discover.ats"
    await w.shutdown()


async def test_sim_disabled_stops_sim_agents(hq_env, db):
    write_agent(hq_env.agents, "checker", capabilities=["verify.link"])
    adapter = FakeAdapter()
    w = make_worker(adapter)
    w.startup()
    with tx(db):
        set_settings(db, {"sim_enabled": False})
        tid = queue.enqueue(db, "verify.link")
    for _ in range(5):
        await w.tick()
    assert statuses(db, [tid])[tid] == "queued" and not adapter.started
    await w.shutdown()


async def test_startup_requeues_orphaned_leases(hq_env, db):
    write_agent(hq_env.agents, "checker", capabilities=["verify.link"])
    with tx(db):
        tid = queue.enqueue(db, "verify.link")
    assert queue.try_lease(db, tid, "checker")  # a worker that was kill -9'd
    w = make_worker(FakeAdapter())
    w.startup()
    assert statuses(db, [tid])[tid] == "queued"
    assert await drive(w, lambda: statuses(db, [tid])[tid] == "succeeded")
    await w.shutdown()


async def test_watchdog_cancels_stuck_run(hq_env, db):
    write_agent(hq_env.agents, "sleepy", capabilities=["verify.link"])
    adapter = FakeAdapter(seconds=30, cooperative=False)  # never heartbeats
    w = make_worker(adapter, stale_agent_s=0.3, watchdog_s=0.1, backoff=lambda attempts: 60.0)
    w.startup()
    with tx(db):
        tid = queue.enqueue(db, "verify.link")
    assert await drive(w, lambda: statuses(db, [tid])[tid] == "queued"
                       and db.execute("SELECT attempts FROM tasks WHERE id=?", (tid,)).fetchone()[0] == 1, timeout=5)
    assert db.execute("SELECT restarts FROM agents WHERE id='sleepy'").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM events WHERE message LIKE '%stuck%'").fetchone()[0] >= 1
    await w.shutdown()


async def test_worker_heartbeat_and_shutdown(hq_env, db):
    w = make_worker(FakeAdapter())
    w.startup()
    hb = db.execute("SELECT value_json FROM settings WHERE key='worker_heartbeat_at'").fetchone()
    assert hb and hb[0] != "null"
    await w.shutdown()
    types = [r[0] for r in db.execute("SELECT type FROM events ORDER BY id")]
    assert "worker.started" in types and "worker.heartbeat" in types and types[-1] == "worker.stopped"


# ── state machine (pure) ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("stage,cap,result,expected_stage,expected_caps", [
    ("found", "discover.ats", {"created": True}, "found", ["parse.job"]),
    ("found", "parse.job", {}, "found", ["verify.link"]),
    ("found", "verify.link", {"ok": True}, "found", ["verify.eligibility"]),
    ("found", "verify.eligibility", {"ok": False, "stage_reason": "ineligible"}, "filtered", []),
    ("found", "verify.scam", {"ok": True}, "found", ["verify.pay"]),
    ("found", "verify.pay", {"ok": True}, "found", ["score.fit"]),
    ("found", "score.fit", {"ok": True, "advance": True}, "verified", ["draft.cover_letter"]),
    ("found", "score.fit", {"ok": True, "advance": False}, "verified", []),
    ("verified", "draft.cover_letter", {"version": 1}, "drafted", ["factcheck.deterministic"]),
    ("drafted", "factcheck.deterministic", {"ok": False, "version": 1}, "drafted", ["draft.cover_letter"]),
    ("drafted", "factcheck.deterministic", {"ok": False, "version": 3}, "drafted", []),
    ("drafted", "factcheck.sentence", {"ok": True}, "drafted", ["check.quality"]),
    ("drafted", "check.quality", {"ok": True}, "drafted", ["factcheck.signoff"]),
    ("drafted", "factcheck.signoff", {"ok": True}, "checked", ["build.resume"]),
    ("checked", "build.resume", {"apply_channel": "email"}, "checked", ["apply.email_send"]),
    ("checked", "build.resume", {"apply_channel": "ats_form"}, "checked", ["apply.manual_pack"]),
    ("checked", "build.resume", {"apply_channel": "email", "approval_required": True}, "checked", []),
    ("checked", "apply.email_send", {"ok": True}, "applied", ["followup.schedule"]),
    ("checked", "apply.manual_pack", {"ok": True}, "checked", []),
    ("applied", "inbox.poll", {"reply": True}, "replied", ["inbox.classify"]),
    ("replied", "inbox.classify", {"classification": "interview"}, "interview", []),
    ("replied", "inbox.classify", {"classification": "rejection"}, "rejected", []),
    ("replied", "inbox.classify", {"classification": "offer"}, "offer", []),
    ("replied", "inbox.classify", {"classification": "auto_ack"}, "replied", []),
    ("filtered", "verify.pay", {"ok": True}, "filtered", []),       # terminal: nothing moves
    ("applied", "verify.link", {"ok": False}, "applied", []),       # stale verify can't regress a stage
])
def test_next_tasks(stage, cap, result, expected_stage, expected_caps):
    new_stage, specs = next_tasks(stage, cap, result)
    assert new_stage == expected_stage
    assert [s.capability for s in specs] == expected_caps
    assert all(isinstance(s, TaskSpec) for s in specs)


def test_redraft_carries_feedback_and_version():
    _, specs = next_tasks("drafted", "factcheck.deterministic", {"ok": False, "version": 1, "feedback": "x"})
    assert specs[0].payload == {"version": 2, "loop": 2, "feedback": "x"}


def test_after_three_loops_the_real_pipeline_polishes_once_then_stops():
    res = {"ok": False, "version": 3, "loop": 3, "feedback": "f", "polish_allowed": True}
    _, specs = next_tasks("drafted", "factcheck.sentence", res)
    assert [s.capability for s in specs] == ["polish.final"]
    _, specs = next_tasks("drafted", "factcheck.sentence", {**res, "polished": True})
    assert specs == []
    _, specs = next_tasks("drafted", "factcheck.sentence", {"ok": False, "version": 3})  # the sim: no polish
    assert specs == []
    stage, specs = next_tasks("drafted", "check.quality", {"ok": True, "version": 1, "polish": True})
    assert [s.capability for s in specs] == ["polish.final"]
    _, specs = next_tasks("drafted", "polish.final", {"ok": True, "version": 2, "loop": 1})
    assert specs[0].capability == "factcheck.deterministic" and specs[0].payload["polished"] is True


# ── probation ────────────────────────────────────────────────────────────────────────────────────────
class EffectAdapter(FakeAdapter):
    async def run(self, task: dict[str, Any], ctx: RunContext) -> RunResult:
        await super().run(task, ctx)
        return RunResult(output={"ok": True}, summary="made a note",
                         effects=[{"op": "event", "type": "log", "message": "probation effect applied"}])


async def test_probation_holds_output_until_prerit_approves(db, hq_env):
    from hq.api.routes import _need_followups
    from hq.db import repo

    write_agent(hq_env.agents, "newbie", capabilities=["summarize"])
    worker = make_worker(EffectAdapter(seconds=0.01))
    worker.startup()
    with tx(db):
        db.execute("UPDATE agents SET probation_runs_left=2 WHERE id='newbie'")
        tid = queue.enqueue(db, "summarize", emit_event=False)
    assert await drive(worker, lambda: queue.get_task(db, tid)["status"] == "succeeded")
    task = queue.get_task(db, tid)
    assert task["result_json"]["probation_hold"] is True
    need = db.execute("SELECT * FROM needs_prerit WHERE kind='approve'").fetchone()
    assert need and "newbie" in need["title"].lower()
    assert db.execute("SELECT probation_runs_left FROM agents WHERE id='newbie'").fetchone()[0] == 1
    assert not db.execute("SELECT 1 FROM events WHERE message='probation effect applied'").fetchone()

    with tx(db):
        db.execute("UPDATE needs_prerit SET status='done' WHERE id=?", (need["id"],))
        assert _need_followups(db, repo.get_need_row(db, need["id"]), "done") == ["probation:approved"]
    await worker.tick()
    assert queue.get_task(db, tid)["result_json"]["approved"] is True
    assert db.execute("SELECT 1 FROM events WHERE message='probation effect applied'").fetchone()
