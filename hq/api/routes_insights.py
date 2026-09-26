"""Strategist reports and analytics (phase e). Read-only; the Strategist agent writes `strategy_reports`."""
from __future__ import annotations

import sqlite3
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from hq.api import auth
from hq.api.routes import Conn
from hq.db.serializers import _loads

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
