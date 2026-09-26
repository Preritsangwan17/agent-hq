"""Task queue primitives on the `tasks` table (CONTRACT §7). All state changes are single atomic statements or
run inside the caller's transaction; leasing is `UPDATE … WHERE id=? AND status='queued'` so concurrent
dispatchers can never lease the same task twice."""
from __future__ import annotations

import random
import sqlite3
from typing import Any, Callable

from hq.db import repo
from hq.db.conn import dumps, row_to_dict
from hq.util.ids import new_id
from hq.util.timeutil import iso_in, now_iso

LEASE_S = 90
HEARTBEAT_S = 15
MAX_BACKOFF_S = 3600


def backoff_seconds(attempts: int, rng: random.Random | None = None) -> float:
    """min(2^attempts · 5 s + jitter, 1 h), jitter up to 20 % of the base."""
    base = (2 ** max(1, attempts)) * 5.0
    jitter = (rng or random).uniform(0, base * 0.2)
    return min(base + jitter, MAX_BACKOFF_S)


def enqueue(conn: sqlite3.Connection, capability: str, *, type_: str = "pipeline", payload: dict | None = None,
            opportunity_id: str | None = None, application_id: str | None = None, priority: int = 50,
            delay_s: float = 0.0, idempotency_key: str | None = None, parent_task_id: str | None = None,
            source_agent: str | None = None, max_attempts: int = 4, emit_event: bool = True) -> str | None:
    """Insert a queued task. Returns its id, or None when the idempotency key already exists."""
    task_id = new_id()
    now = now_iso()
    cur = conn.execute(
        "INSERT OR IGNORE INTO tasks(id, type, capability, payload_json, opportunity_id, application_id, priority, "
        "status, max_attempts, not_before, idempotency_key, parent_task_id, source_agent, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?, 'queued', ?,?,?,?,?,?,?)",
        (task_id, type_, capability, dumps(payload or {}), opportunity_id, application_id, priority, max_attempts,
         iso_in(delay_s) if delay_s > 0 else None, idempotency_key, parent_task_id, source_agent, now, now),
    )
    if not cur.rowcount:
        return None
    if emit_event:
        repo.emit(conn, "task.created", f"Queued {capability}", level="debug", opportunity_id=opportunity_id,
                  task_id=task_id, data={"task_id": task_id, "capability": capability, "agent_id": None})
    return task_id


def get_task(conn: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    task = row_to_dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    if task is not None:
        task["payload"] = task.pop("payload_json", {}) or {}
    return task


def ready_tasks(conn: sqlite3.Connection, now: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    now = now or now_iso()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status='queued' AND (not_before IS NULL OR not_before <= ?) "
        "ORDER BY priority DESC, created_at LIMIT ?", (now, limit)).fetchall()
    out = []
    for r in rows:
        t = row_to_dict(r)
        t["payload"] = t.pop("payload_json", {}) or {}
        out.append(t)
    return out


def try_lease(conn: sqlite3.Connection, task_id: str, owner: str, lease_s: float = LEASE_S) -> bool:
    now = now_iso()
    cur = conn.execute(
        "UPDATE tasks SET status='leased', lease_owner=?, lease_expires_at=?, heartbeat_at=?, updated_at=? "
        "WHERE id=? AND status='queued'", (owner, iso_in(lease_s), now, now, task_id))
    return cur.rowcount == 1


def mark_running(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute("UPDATE tasks SET status='running', updated_at=? WHERE id=? AND status='leased'",
                 (now_iso(), task_id))


def extend_lease(conn: sqlite3.Connection, task_id: str, lease_s: float = LEASE_S) -> bool:
    now = now_iso()
    cur = conn.execute(
        "UPDATE tasks SET lease_expires_at=?, heartbeat_at=?, updated_at=? WHERE id=? AND status IN ('leased','running')",
        (iso_in(lease_s), now, now, task_id))
    return cur.rowcount == 1


def complete(conn: sqlite3.Connection, task_id: str, result: Any) -> None:
    now = now_iso()
    conn.execute(
        "UPDATE tasks SET status='succeeded', result_json=?, finished_at=?, updated_at=?, lease_expires_at=NULL "
        "WHERE id=?", (dumps(result), now, now, task_id))


def _signature(error: str) -> str:
    return "".join(ch for ch in error.lower() if not ch.isdigit())[:120]


def fail(conn: sqlite3.Connection, task_id: str, error: str, *, agent_id: str | None = None,
         backoff: Callable[[int], float] = backoff_seconds) -> str:
    """Record a failure: requeue with backoff (`task.retry`) or mark dead (`task.dead`). Returns 'retry'|'dead'."""
    task = get_task(conn, task_id)
    if task is None:
        return "dead"
    attempts = task["attempts"] + 1
    now = now_iso()
    data = {"task_id": task_id, "capability": task["capability"], "agent_id": agent_id, "attempt": attempts,
            "error": error[:500]}
    if attempts < task["max_attempts"]:
        delay = backoff(attempts)
        conn.execute(
            "UPDATE tasks SET status='queued', attempts=?, not_before=?, last_error=?, error_signature=?, "
            "lease_owner=NULL, lease_expires_at=NULL, updated_at=? WHERE id=?",
            (attempts, iso_in(delay), error[:2000], _signature(error), now, task_id))
        data["retry_in_s"] = round(delay, 1)
        repo.emit(conn, "task.retry", f"{task['capability']} failed ({error[:120]}); retry {attempts}/"
                  f"{task['max_attempts'] - 1} in {delay:.0f}s", level="warn", agent_id=agent_id,
                  opportunity_id=task["opportunity_id"], task_id=task_id, data=data)
        return "retry"
    conn.execute(
        "UPDATE tasks SET status='dead', attempts=?, last_error=?, error_signature=?, lease_owner=NULL, "
        "lease_expires_at=NULL, finished_at=?, updated_at=? WHERE id=?",
        (attempts, error[:2000], _signature(error), now, now, task_id))
    repo.emit(conn, "task.dead", f"{task['capability']} gave up after {attempts} attempts: {error[:160]}",
              level="error", agent_id=agent_id, opportunity_id=task["opportunity_id"], task_id=task_id, data=data)
    return "dead"


def requeue(conn: sqlite3.Connection, task_id: str) -> None:
    """Put a leased/running task back without an attempt penalty (pause, shutdown, crash recovery)."""
    conn.execute(
        "UPDATE tasks SET status='queued', lease_owner=NULL, lease_expires_at=NULL, updated_at=? "
        "WHERE id=? AND status IN ('leased','running')", (now_iso(), task_id))


def cancel(conn: sqlite3.Connection, task_id: str, reason: str) -> bool:
    now = now_iso()
    cur = conn.execute(
        "UPDATE tasks SET status='cancelled', last_error=?, lease_owner=NULL, lease_expires_at=NULL, finished_at=?, "
        "updated_at=? WHERE id=? AND status IN ('queued','leased','running','deferred_budget','waiting_memory')",
        (reason, now, now, task_id))
    return cur.rowcount == 1


def expired_leases(conn: sqlite3.Connection, now: str | None = None) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id, capability, lease_owner FROM tasks WHERE status IN ('leased','running') "
                        "AND lease_expires_at < ?", (now or now_iso(),)).fetchall()
    return [dict(r) for r in rows]


def recover_orphans(conn: sqlite3.Connection) -> list[str]:
    """At worker start every leased/running task belongs to a dead worker: requeue them all."""
    ids = [r["id"] for r in conn.execute("SELECT id FROM tasks WHERE status IN ('leased','running')").fetchall()]
    for task_id in ids:
        requeue(conn, task_id)
    return ids


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status")}
