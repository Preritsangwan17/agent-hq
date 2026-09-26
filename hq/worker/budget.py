"""Claude budget (PLAN "Orchestrator › Budget", CONTRACT_B §2).

Before a call: reserve the EMA cost of that task type and check
    spent_today + reserved + estimate ≤ claude_daily_budget_usd   and   calls_today < claude_daily_call_cap.
Reservations are `claude_usage` rows with subtype 'reserved'; `commit()` turns one into the real cost,
`release()` drops it (a call that never happened is not counted). The day boundary is midnight IST. Over the cap
the caller defers the task to the next IST midnight (`deferred_budget`) and local work continues.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from hq import settings as paths
from hq.db import repo
from hq.db.conn import tx
from hq.db.seed import get_settings
from hq.util.ids import new_id
from hq.util.timeutil import IST, now_iso, to_iso, today_ist, utcnow

EMA_ALPHA = 0.3


@dataclass
class Reservation:
    id: str
    task_type: str
    estimate_usd: float
    date_ist: str


@lru_cache(maxsize=2)
def _prices(path: str, mtime: float) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text()) or {}


def seed_price(task_type: str) -> float:
    p = paths.CONFIG_DIR / "claude_prices.yaml"
    data = _prices(str(p), p.stat().st_mtime) if p.exists() else {}
    return float((data.get("task_types") or {}).get(task_type, data.get("default", 0.08)))


def ema_cost(conn: sqlite3.Connection, task_type: str) -> float:
    ema = seed_price(task_type)
    rows = conn.execute(
        "SELECT cost_usd_est FROM claude_usage WHERE task_type=? AND cost_usd_est IS NOT NULL "
        "AND subtype NOT IN ('reserved','released') ORDER BY created_at DESC LIMIT 50", (task_type,)).fetchall()
    for r in reversed(rows):
        ema = EMA_ALPHA * float(r[0]) + (1 - EMA_ALPHA) * ema
    return round(ema, 4)


def next_midnight_ist(now: datetime | None = None) -> datetime:
    now = (now or utcnow()).astimezone(IST)
    return datetime.combine(now.date() + timedelta(days=1), time(0, 0), IST)


def usage_today(conn: sqlite3.Connection, date_ist: str | None = None) -> dict[str, Any]:
    day = date_ist or today_ist().isoformat()
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN subtype NOT IN ('reserved','released') THEN cost_usd_est END),0) AS spent, "
        "COALESCE(SUM(CASE WHEN subtype='reserved' THEN reserved_usd END),0) AS reserved, "
        "COUNT(CASE WHEN subtype!='released' THEN 1 END) AS calls FROM claude_usage WHERE date_local=?",
        (day,)).fetchone()
    by_task = {r["task_type"]: {"calls": r["n"], "spent_usd": round(r["s"] or 0, 4)} for r in conn.execute(
        "SELECT task_type, COUNT(*) AS n, SUM(cost_usd_est) AS s FROM claude_usage WHERE date_local=? "
        "AND subtype NOT IN ('released') GROUP BY task_type", (day,))}
    return {"date_ist": day, "spent_usd": round(row["spent"], 4), "reserved_usd": round(row["reserved"], 4),
            "calls": row["calls"], "by_task": by_task}


def reserve(conn: sqlite3.Connection, task_type: str, settings: dict[str, Any] | None = None, *,
            run_id: str | None = None) -> Reservation | None:
    """Reserve the estimate, or None when today's budget/call cap would be exceeded. Own transaction."""
    s = settings or get_settings(conn)
    budget = float(s.get("claude_daily_budget_usd", 5.0))
    cap = int(s.get("claude_daily_call_cap", 40))
    est = ema_cost(conn, task_type)
    with tx(conn):
        u = usage_today(conn)
        if u["calls"] >= cap or u["spent_usd"] + u["reserved_usd"] + est > budget + 1e-9:
            return None
        rid = new_id()
        conn.execute(
            "INSERT INTO claude_usage(id, run_id, task_type, date_local, reserved_usd, subtype, created_at) "
            "VALUES (?,?,?,?,?, 'reserved', ?)", (rid, run_id, task_type, u["date_ist"], est, now_iso()))
    return Reservation(rid, task_type, est, u["date_ist"])


def commit(conn: sqlite3.Connection, r: Reservation, *, cost_usd: float | None, model: str | None = None,
           input_tokens: int | None = None, output_tokens: int | None = None, cache_read_tokens: int | None = None,
           subtype: str = "success") -> None:
    """Record the real (client-estimated) cost; a missing cost keeps the reservation estimate."""
    cost = r.estimate_usd if cost_usd is None else float(cost_usd)
    with tx(conn):
        conn.execute(
            "UPDATE claude_usage SET cost_usd_est=?, model=?, input_tokens=?, output_tokens=?, cache_read_tokens=?, "
            "subtype=? WHERE id=?", (cost, model, input_tokens, output_tokens, cache_read_tokens, subtype, r.id))
        repo.emit(conn, "budget.updated", f"Claude {r.task_type}: ${cost:.3f}", level="debug",
                  data=budget_state(conn))


def release(conn: sqlite3.Connection, r: Reservation) -> None:
    with tx(conn):
        conn.execute("UPDATE claude_usage SET subtype='released', reserved_usd=0 WHERE id=?", (r.id,))


def defer_task(conn: sqlite3.Connection, task_id: str, reason: str = "Claude daily budget reached") -> str:
    """Park a task until the next IST midnight. Caller owns the transaction."""
    until = to_iso(next_midnight_ist())
    conn.execute("UPDATE tasks SET status='deferred_budget', not_before=?, lease_owner=NULL, lease_expires_at=NULL, "
                 "last_error=?, updated_at=? WHERE id=?", (until, reason, now_iso(), task_id))
    repo.emit(conn, "budget.capped", f"{reason} — task waits until midnight IST", level="warn", task_id=task_id,
              data={"task_id": task_id, "until": until})
    return until


def revive_deferred(conn: sqlite3.Connection) -> int:
    """Called by the watchdog: deferred tasks whose time has come go back to the queue. Caller owns the tx."""
    return conn.execute("UPDATE tasks SET status='queued', updated_at=? WHERE status='deferred_budget' "
                        "AND not_before <= ?", (now_iso(), now_iso())).rowcount


def cloud_provider(s: dict[str, Any]) -> str | None:
    """From the settings as they are now (the worker's provider snapshot can be up to one loop old)."""
    from hq.llm import cloud

    return cloud.provider(s)


def _still_on(s: dict[str, Any], claude: dict[str, Any] | None) -> str | None:
    """The provider the worker last found usable, unless it has been switched off since."""
    using = (claude or {}).get("using")
    return using if using and s.get(f"llm_{using}_enabled", True) is not False else None


def budget_state(conn: sqlite3.Connection, settings: dict[str, Any] | None = None,
                 claude: dict[str, Any] | None = None) -> dict[str, Any]:
    s = settings or get_settings(conn)
    u = usage_today(conn)
    deferred = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='deferred_budget'").fetchone()[0]
    last_err = conn.execute("SELECT subtype FROM claude_usage WHERE subtype NOT IN ('success','reserved','released') "
                            "ORDER BY created_at DESC LIMIT 1").fetchone()
    return {**u, "budget_usd": float(s.get("claude_daily_budget_usd", 5.0)),
            "call_cap": int(s.get("claude_daily_call_cap", 40)), "deferred_tasks": deferred,
            "claude_available": (claude or {}).get("available"), "provider": cloud_provider(s),
            "cloud_model": (claude or {}).get("model"), "cloud_reason": (claude or {}).get("reason"),
            "xai": ((claude or {}).get("providers") or {}).get("xai"),
            "codex": ((claude or {}).get("providers") or {}).get("codex"),
            "claude": ((claude or {}).get("providers") or {}).get("claude"), "using": _still_on(s, claude),
            "last_error": last_err[0] if last_err else None,
            "resets_at": to_iso(next_midnight_ist())}
