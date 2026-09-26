"""Strategist reports and analytics (phase e). The Strategist agent writes `strategy_reports`; the only write here is
"Run review now", which queues one `strategy.daily_review` task (never two at once)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request

from hq import insights
from hq.api import auth
from hq.api.auth import ApiError
from hq.api.routes import Conn, _addr
from hq.db import repo
from hq.db.conn import tx
from hq.db.serializers import _loads
from hq.pipeline.state import priority_for
from hq.worker import queue

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_session)])
IST = ZoneInfo("Asia/Kolkata")
REPORT_TIME_IST = time(7, 30)


def next_report_at(now: datetime | None = None) -> str:
    now = (now or datetime.now(IST)).astimezone(IST)
    at = datetime.combine(now.date(), REPORT_TIME_IST, IST)
    if at <= now:
        at += timedelta(days=1)
    return at.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def report_json(row: dict[str, Any]) -> dict[str, Any]:
    return {"date": row["date"], "report_md": row["report_md"],
            "proposed_actions": _loads(row["proposed_actions_json"], []),
            "applied_actions": _loads(row["applied_actions_json"], []), "created_at": row["created_at"]}


@router.get("/strategy/latest")
def strategy_latest(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM strategy_reports ORDER BY date DESC LIMIT 1").fetchone()
    return {"report": report_json(dict(row)) if row else None, "next_run_at": next_report_at()}


@router.get("/strategy/reports")
def strategy_reports(conn: sqlite3.Connection = Conn, limit: int = 30) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM strategy_reports ORDER BY date DESC LIMIT ?", (max(1, min(limit, 365)),))
    return {"items": [report_json(dict(r)) for r in rows]}


@router.post("/strategy/run")
def strategy_run(request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    agent = conn.execute("SELECT enabled, paused FROM agents WHERE id='strategist'").fetchone()
    if agent is None or not agent["enabled"]:
        raise ApiError(409, "the Strategist agent is turned off (Agents page)")
    with tx(conn):
        open_ = conn.execute("SELECT id FROM tasks WHERE capability='strategy.daily_review' AND status IN "
                             "('queued','leased','running','deferred_budget') LIMIT 1").fetchone()
        if open_:
            return {"queued": False, "task_id": open_["id"], "detail": "a review is already queued or running"}
        task_id = queue.enqueue(conn, "strategy.daily_review", payload={"requested_by": "prerit"},
                                priority=priority_for("strategy.daily_review") + 40, source_agent="prerit")
        repo.audit(conn, "prerit", "strategy.run", None, remote_addr=_addr(request))
    return {"queued": True, "task_id": task_id, "paused": bool(agent["paused"])}


@router.get("/analytics")
def analytics(conn: sqlite3.Connection = Conn, scope: str = Query("all", pattern="^(all|real|sim)$"),
              days: int = Query(30, ge=7, le=180)) -> dict[str, Any]:
    return insights.analytics(conn, scope=scope, days=days)
