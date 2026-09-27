"""Read-only AI control telemetry. Settings mutations use the validated settings API."""
from dataclasses import asdict
from datetime import datetime, time
import sqlite3

from fastapi import APIRouter, Depends, Query

from hq.api import auth
from hq.api.routes import Conn
from hq.api.routes_models import models
from hq.db.seed import get_settings
from hq.llm import cloud, modes, policy
from hq.llm.providers import REGISTRY
from hq.util.timeutil import IST, now_iso, today_ist, to_iso
from hq.worker.budget import budget_state

router = APIRouter(prefix="/api/ai", dependencies=[Depends(auth.require_session)])


def usage(conn, since, until):
    rows = conn.execute(
        "SELECT model, COUNT(*) calls, COALESCE(SUM(cost_usd_est),0) cost, "
        "COALESCE(SUM(input_tokens),0) input_tokens, COALESCE(SUM(output_tokens),0) output_tokens "
        "FROM claude_usage WHERE date_local>=? AND date_local<=? AND subtype NOT IN ('reserved','released') GROUP BY model",
        (since, until))
    result = {p: {"calls": 0, "estimated_cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0} for p in cloud.PROVIDERS}
    for row in rows:
        p = cloud.provider_of(row["model"]) if row["model"] else "unknown"
        item = result.setdefault(p, {"calls": 0, "estimated_cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0})
        for key, column in (("calls", "calls"), ("estimated_cost_usd", "cost"), ("input_tokens", "input_tokens"), ("output_tokens", "output_tokens")):
            item[key] += row[column]
    for item in result.values():
        item["estimated_cost_usd"] = round(item["estimated_cost_usd"], 6)
    return result


@router.get("/control")
def control(conn: sqlite3.Connection = Conn):
    s = get_settings(conn)
    model_state = models(conn)
    day = today_ist().isoformat()
    today, month = usage(conn, day, day), usage(conn, day[:7] + "-01", day)
    since = to_iso(datetime.combine(today_ist(), time(), IST))
    counts = [dict(r) for r in conn.execute(
        "SELECT execution, COUNT(*) attempts, SUM(status='succeeded') succeeded, SUM(status='failed') failed, "
        "SUM(escalated_from_run_id IS NOT NULL) fallbacks, AVG(duration_ms) response_ms "
        "FROM agent_runs WHERE route_reason IS NOT NULL AND started_at>=? GROUP BY execution", (since,))]
    states = (s.get("claude_state") or {}).get("providers") or {}
    providers = []
    for p, meta in REGISTRY.items():
        st = dict(states.get(p) or {})
        enabled = modes.enabled(s, p)
        st["enabled"] = enabled
        if not enabled:
            st.update(available=False, reason="Disabled in the current mode")
        timings = conn.execute(
            "SELECT AVG(duration_ms) latency, COUNT(*) attempts, SUM(status='succeeded') succeeded, SUM(status='failed') failed "
            "FROM agent_runs WHERE route_reason IS NOT NULL AND started_at>=? AND " +
            ("execution='local'" if p == "local" else "model_id LIKE ?"),
            (since,) if p == "local" else (since, p + ":%" )).fetchone()
        providers.append({**asdict(meta), "enabled": enabled, "required": p == "local", "status": st,
                          "today": today.get(p), "month": month.get(p), "performance": dict(timings),
                          "account_quota": None, "quota_note": "Account-wide remaining quota is not reported by this integration."})
    last = conn.execute("SELECT model_id FROM agent_runs WHERE execution='local' ORDER BY rowid DESC LIMIT 1").fetchone()
    return {"at": now_iso(), "current_mode": modes.current(s), "modes": list(modes.MODES.values()),
            "recommendation": policy.recommendation(s), "providers": providers,
            "current_local_model": last[0] if last else None, "models": model_state["models"],
            "roles": model_state["roles"], "memory": model_state["memory"], "servers": model_state["servers"],
            "budget": budget_state(conn, s, s.get("claude_state")), "today": today, "month": month,
            "execution_today": counts, "signoff_required": bool(s.get("require_claude_signoff", True)),
            "usage_note": "HQ usage only, by IST day/month. Dollar values are estimates, not provider invoices or subscription quota."}


@router.get("/runs")
def runs(conn: sqlite3.Connection = Conn, limit: int = Query(50, ge=1, le=200),
         offset: int = Query(0, ge=0), task_id: str | None = None):
    where, args = "r.route_reason IS NOT NULL", []
    if task_id:
        where += " AND r.task_id=?"
        args.append(task_id)
    total = conn.execute("SELECT COUNT(*) FROM agent_runs r WHERE " + where, args).fetchone()[0]
    rows = conn.execute(
        "SELECT r.id, r.task_id, r.parent_run_id, r.escalated_from_run_id, r.agent_id, r.model_id, r.ai_mode, "
        "r.task_type, r.route_reason, r.execution, r.status, r.error, r.duration_ms, r.prompt_tokens, "
        "r.completion_tokens, r.cost_usd, r.started_at, t.capability, t.opportunity_id, "
        "u.cost_usd_est AS estimated_cost_usd FROM agent_runs r LEFT JOIN tasks t ON t.id=r.task_id "
        "LEFT JOIN claude_usage u ON u.run_id=r.id AND u.subtype NOT IN ('reserved','released') "
        "WHERE " + where + " ORDER BY r.rowid DESC LIMIT ? OFFSET ?", [*args, limit, offset])
    return {"items": [dict(r) for r in rows], "total": total}


@router.get("/plan")
def plan(conn: sqlite3.Connection = Conn, workflow: str = Query("job_search", pattern="^(job_search|coding)$")):
    return {"workflow": workflow, "preview": True, "steps": policy.plan(conn, get_settings(conn), workflow)}
