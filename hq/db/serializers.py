"""JSON shapes from CONTRACT §5, built in one place so the API, SSE events and worker events agree."""
from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime, time, timezone
from typing import Any

from hq import __version__
from hq.agents.schema import RESERVED_SIDE_EFFECTS
from hq.db import repo
from hq.db.seed import get_settings
from hq.util.timeutil import IST, now_iso, parse_iso, to_iso, today_ist, utcnow

WORKER_STALE_S = 30


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


# ── pay / opportunities ──────────────────────────────────────────────────────────────────────────────
def pay_json(o: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw": o.get("pay_raw"),
        "status": o.get("pay_status") or "unknown",
        "min": o.get("pay_min"),
        "max": o.get("pay_max"),
        "currency": o.get("pay_currency"),
        "period": o.get("pay_period"),
        "monthly_inr_min": o.get("pay_monthly_inr_min"),
        "monthly_inr_mid": o.get("pay_monthly_inr_mid"),
        "monthly_inr_max": o.get("pay_monthly_inr_max"),
        "hourly_inr_min": o.get("pay_hourly_inr_min"),
        "hourly_inr_max": o.get("pay_hourly_inr_max"),
        "fx_rate": o.get("fx_rate"),
        "fx_date": o.get("fx_date"),
        "living_cost_monthly_inr": o.get("living_cost_monthly_inr"),
        "living_cost_basis": o.get("living_cost_basis"),
        "living_cost_confidence": o.get("living_cost_confidence"),
        "ratio": o.get("pay_ratio"),
        "benefits": _loads(o.get("benefits_json"), {}),
    }


def opp_summary(o: dict[str, Any], active_agent_id: str | None = None, needs_prerit: bool = False) -> dict[str, Any]:
    return {
        "id": o["id"],
        "company_name": o["company_name"],
        "title": o["title"],
        "kind": o.get("kind"),
        "role_type": o.get("role_type"),
        "city": o.get("city"),
        "country_iso2": o.get("country_iso2"),
        "lat": o.get("lat"),
        "lon": o.get("lon"),
        "work_mode": o.get("work_mode"),
        "stage": o["stage"],
        "stage_reason": o.get("stage_reason"),
        "is_simulated": bool(o.get("is_simulated")),
        "fit_score": o.get("fit_score"),
        "eligibility_status": o.get("eligibility_status"),
        "scam_status": o.get("scam_status"),
        "deadline_at": o.get("deadline_at"),
        "deadline_confidence": o.get("deadline_confidence"),
        "pay": pay_json(o),
        "url": o.get("url"),
        "apply_channel": o.get("apply_channel"),
        "source_label": o.get("source_label"),
        "active_agent_id": active_agent_id,
        "needs_prerit": bool(needs_prerit),
        "updated_at": o["updated_at"],
        "first_seen_at": o["first_seen_at"],
    }


def opp_summaries(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = repo.active_agents_by_opp(conn)
    needs = repo.opps_with_open_needs(conn)
    return [opp_summary(o, active.get(o["id"]), o["id"] in needs) for o in rows]


def opp_summary_by_id(conn: sqlite3.Connection, opp_id: str) -> dict[str, Any] | None:
    o = repo.get_opportunity_row(conn, opp_id)
    if o is None:
        return None
    active = repo.active_agents_by_opp(conn, [opp_id]).get(opp_id)
    need = conn.execute("SELECT 1 FROM needs_prerit WHERE opportunity_id=? AND status='open' LIMIT 1",
                        (opp_id,)).fetchone()
    return opp_summary(o, active, need is not None)


def application_json(a: dict[str, Any]) -> dict[str, Any]:
    return {"id": a["id"], "channel": a["channel"], "status": a["status"], "mode": a["mode"],
            "submitted_at": a.get("submitted_at"), "created_at": a["created_at"],
            "submission_ref": a.get("submission_ref"), "doc_kind": a.get("doc_kind"),
            "approved_at": a.get("approved_at"), "message_id": a.get("message_id"),
            "answers": _loads(a.get("answers_json"), []), "reviewed_at": a.get("reviewed_at")}


def document_json(d: dict[str, Any]) -> dict[str, Any]:
    return {"id": d["id"], "kind": d["kind"], "version": d["version"], "status": d["status"],
            "author_agent": d.get("author_agent"), "author_model": d.get("author_model"),
            "content_text": d.get("content_text"), "created_at": d["created_at"],
            "subject": d.get("subject"), "parent_id": d.get("parent_id"),
            "lineage": _loads(d.get("lineage_models_json"), []),
            "file_url": f"/api/documents/{d['id']}/file" if d.get("content_path") else None}


def document_sentences(conn: sqlite3.Connection, doc_id: str) -> list[dict[str, Any]]:
    """Sentences with every fact-check verdict on them (deterministic / local checker / final sign-off)."""
    checks: dict[str | None, list[dict[str, Any]]] = {}
    for r in conn.execute("SELECT * FROM fact_checks WHERE document_id=? ORDER BY created_at", (doc_id,)):
        checks.setdefault(r["sentence_id"], []).append(
            {"layer": r["layer"], "verdict": r["verdict"], "checker_model": r["checker_model"],
             "rules": _loads(r["rule_ids_json"], []), "span": r["unsupported_span"], "explanation": r["explanation"]})
    out = [{"id": r["id"], "idx": r["idx"], "text": r["text"], "kind": r["kind"],
            "fact_ids": _loads(r["fact_ids_json"], []), "job_quote_ids": _loads(r["job_quote_ids_json"], []),
            "checks": checks.pop(r["id"], [])}
           for r in conn.execute("SELECT * FROM document_sentences WHERE document_id=? ORDER BY idx", (doc_id,))]
    if checks:  # document-level checks (quality, sign-off summary)
        out.append({"id": None, "idx": -1, "text": None, "kind": "document", "fact_ids": [], "job_quote_ids": [],
                    "checks": [c for cs in checks.values() for c in cs]})
    return out


def need_json(n: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": n["id"], "opportunity_id": n.get("opportunity_id"), "application_id": n.get("application_id"),
        "kind": n["kind"], "title": n["title"], "instructions_md": n.get("instructions_md"),
        "answers": _loads(n.get("answers_json"), []), "files": _loads(n.get("files_json"), []),
        "direct_url": n.get("direct_url"), "priority": n.get("priority"), "due_at": n.get("due_at"),
        "est_minutes": n.get("est_minutes"), "status": n["status"], "snoozed_until": n.get("snoozed_until"),
        "created_at": n["created_at"], "resolved_at": n.get("resolved_at"),
        "payload": _loads(n.get("payload_json"), {}),
    }


def opp_detail(conn: sqlite3.Connection, opp_id: str) -> dict[str, Any] | None:
    o = repo.get_opportunity_row(conn, opp_id)
    if o is None:
        return None
    base = opp_summary_by_id(conn, opp_id)
    apps = [dict(r) for r in conn.execute(
        "SELECT * FROM applications WHERE opportunity_id=? ORDER BY created_at", (opp_id,))]
    docs = [dict(r) for r in conn.execute(
        "SELECT * FROM documents WHERE opportunity_id=? ORDER BY created_at, version", (opp_id,))]
    app_ids = [a["id"] for a in apps]
    gates: list[dict[str, Any]] = []
    if app_ids:
        rows = conn.execute(
            f"SELECT * FROM gate_results WHERE application_id IN ({','.join('?' * len(app_ids))}) ORDER BY ts",
            app_ids).fetchall()
        gates = [{"id": r["id"], "application_id": r["application_id"], "document_id": r["document_id"],
                  "gate": r["gate"], "passed": bool(r["passed"]), "details": _loads(r["details_json"], {}),
                  "ts": r["ts"]} for r in rows]
    elig = [{"id": r["id"], "method": r["method"], "model_id": r["model_id"],
             "requirements": _loads(r["requirements_json"], {}), "quotes": _loads(r["quotes_json"], []),
             "verdict": r["verdict"], "confidence": r["confidence"], "created_at": r["created_at"]}
            for r in conn.execute("SELECT * FROM eligibility_checks WHERE opportunity_id=? ORDER BY created_at",
                                  (opp_id,))]
    needs = [need_json(n) for n in repo.list_need_rows(conn, status=None, opportunity_id=opp_id)]
    scams = [{"verdict": r["verdict"], "signals": _loads(r["signals_json"], []), "created_at": r["created_at"]}
             for r in conn.execute("SELECT * FROM scam_checks WHERE opportunity_id=? ORDER BY created_at", (opp_id,))]
    sources = [dict(r) for r in conn.execute(
        "SELECT os.source_id, os.external_id, os.source_url, os.first_seen, os.last_seen, s.name AS source_name "
        "FROM opportunity_sources os LEFT JOIN sources s ON s.id=os.source_id WHERE os.opportunity_id=? "
        "ORDER BY os.first_seen", (opp_id,))]
    runs = [{"id": r["id"], "task_id": r["task_id"], "capability": r["capability"], "agent_id": r["agent_id"],
             "model_id": r["model_id"], "status": r["status"], "cost_usd": r["cost_usd"],
             "duration_ms": r["duration_ms"], "parent_run_id": r["parent_run_id"],
             "escalated_from_run_id": r["escalated_from_run_id"], "error": r["error"], "started_at": r["started_at"]}
            for r in conn.execute(
                "SELECT ar.*, t.capability FROM agent_runs ar JOIN tasks t ON t.id=ar.task_id WHERE t.opportunity_id=? "
                "ORDER BY ar.started_at DESC LIMIT 200", (opp_id,))]
    quotes = _loads(o.get("job_quotes_json"), [])
    base.update(
        description_available=bool(o.get("description_path")),
        location_raw=o.get("location_raw"),
        apply_url=o.get("apply_url"),
        automation=o.get("automation"),
        posted_at=o.get("posted_at"),
        fit_breakdown=_loads(o.get("fit_breakdown_json"), {}),
        benefits=_loads(o.get("benefits_json"), {}),
        eligibility_confidence=o.get("eligibility_confidence"),
        parse=_loads(o.get("parse_json"), {}),
        requirements=_loads(o.get("requirements_json"), {}),
        job_quotes=[{"id": f"J{i + 1}", "text": q} for i, q in enumerate(quotes)],
        scam_checks=scams,
        sources=sources,
        runs=runs,
        document_sentences={d["id"]: document_sentences(conn, d["id"]) for d in docs
                            if d["kind"] in ("cover_letter", "cold_email", "research_statement")},
    )
    base.update(
        summary=o.get("summary"),
        notes_unverified=o.get("notes_unverified"),
        applications=[application_json(a) for a in apps],
        documents=[document_json(d) for d in docs],
        timeline=repo.list_events(conn, opportunity_id=opp_id, limit=300),
        gates=gates,
        eligibility_checks=elig,
        needs=needs,
    )
    return base


# ── agents ────────────────────────────────────────────────────────────────────────────────────────────
def live_json(live: dict[str, Any] | None) -> dict[str, Any] | None:
    if not live:
        return None
    return {"agent_id": live["agent_id"], "now_line": live.get("now_line"), "progress": live.get("progress"),
            "current_task_id": live.get("current_task_id"), "opportunity_id": live.get("opportunity_id"),
            "model_id": live.get("model_id"), "tok_s": live.get("tok_s"), "heartbeat_at": live.get("heartbeat_at"),
            "updated_at": live.get("updated_at")}


def worker_alive(conn: sqlite3.Connection) -> tuple[bool, str | None]:
    hb = repo.worker_heartbeat_at(conn)
    ts = parse_iso(hb)
    alive = ts is not None and (utcnow() - ts).total_seconds() <= WORKER_STALE_S
    return alive, hb


def agent_json(row: dict[str, Any], live: dict[str, Any] | None, *, alive: bool = True) -> dict[str, Any]:
    cfg = _loads(row.get("config_json"), {})
    enabled, paused = bool(row["enabled"]), bool(row["paused"])
    status = row["status"]
    if not enabled:
        status = "disabled"
    elif not alive:
        status = "offline"
    elif paused and status not in ("working",):
        status = "paused"
    caps = cfg.get("capabilities", [])
    today = today_ist().isoformat()
    fresh = row.get("counters_date") == today
    return {
        "id": row["id"],
        "name": cfg.get("name", row["id"]),
        "avatar": cfg.get("avatar", "🤖"),
        "color": cfg.get("color", "#94A3B8"),
        "role": cfg.get("role", "custom"),
        "adapter": cfg.get("adapter", "sim"),
        "model": cfg.get("model"),
        "capabilities": caps,
        "cost_tier": cfg.get("cost_tier", "local"),
        "concurrency": cfg.get("concurrency", 1),
        "schedule": cfg.get("schedule", {"mode": "on_demand"}),
        "enabled": enabled,
        "paused": paused,
        "status": status,
        "builtin": bool(cfg.get("builtin", False)),
        "side_effects": [c for c in caps if c in RESERVED_SIDE_EFFECTS],
        "tasks_today": row["tasks_today"] if fresh else 0,
        "errors_today": row["errors_today"] if fresh else 0,
        "tokens_today": row["tokens_today"] if fresh else 0,
        "restarts": row["restarts"], "probation_runs_left": row.get("probation_runs_left", 0),
        "last_error": row.get("last_error"),
        "live": live_json(live),
        "description": cfg.get("description", ""),
    }


def agents_json(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    alive, _ = worker_alive(conn)
    lives = repo.live_rows(conn)
    return [agent_json(r, lives.get(r["id"]), alive=alive) for r in repo.agent_rows(conn)]


def agent_json_by_id(conn: sqlite3.Connection, agent_id: str) -> dict[str, Any] | None:
    row = repo.agent_row(conn, agent_id)
    if row is None:
        return None
    alive, _ = worker_alive(conn)
    return agent_json(row, repo.live_row(conn, agent_id), alive=alive)


# ── stats / snapshot ─────────────────────────────────────────────────────────────────────────────────
REACHED = {
    "verified": ("verified", "drafted", "checked", "applied", "replied", "interview", "offer", "rejected"),
    "drafted": ("drafted", "checked", "applied", "replied", "interview", "offer", "rejected"),
    "applied": ("applied", "replied", "interview", "offer", "rejected"),
    "replies": ("replied", "interview", "offer", "rejected"),
}
PIPELINE_STAGES = ("found", "verified", "drafted", "checked", "applied", "replied", "interview")


def ist_midnight_utc_iso() -> str:
    return to_iso(datetime.combine(today_ist(), time.min, tzinfo=IST).astimezone(timezone.utc))


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def stats(conn: sqlite3.Connection, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or get_settings(conn)
    by_stage = {r["stage"]: r["n"] for r in conn.execute(
        "SELECT stage, COUNT(*) AS n FROM opportunities GROUP BY stage")}

    def reached(key: str) -> int:
        return sum(by_stage.get(s, 0) for s in REACHED[key])

    found = sum(by_stage.values())
    applied = reached("applied")
    interviews = by_stage.get("interview", 0)
    offers = by_stage.get("offer", 0)
    since = ist_midnight_utc_iso()
    grok = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN subtype NOT IN ('reserved','released') THEN cost_usd_est END),0) AS cost, "
        "COUNT(CASE WHEN subtype!='released' THEN 1 END) AS n FROM cloud_usage WHERE date_local=? "
        "AND COALESCE(provider,'xai')='xai'",
        (today_ist().isoformat(),)).fetchone()
    # top-level runs only (router escalation rows are children) and never Grok's tokens
    local = conn.execute(
        "SELECT COALESCE(SUM(COALESCE(prompt_tokens,0)+COALESCE(completion_tokens,0)),0) AS t FROM agent_runs "
        "WHERE started_at >= ? AND parent_run_id IS NULL AND COALESCE(model_id,'') NOT LIKE 'xai:%' "
        "AND COALESCE(model_id,'') NOT LIKE 'claude:%' AND COALESCE(model_id,'') NOT LIKE 'codex:%' "
        "AND COALESCE(model_id,'') NOT LIKE 'sim:%'",
        (since,)).fetchone()

    def mids(stages: tuple[str, ...]) -> list[float]:
        rows = conn.execute(
            f"SELECT pay_monthly_inr_mid AS v FROM opportunities WHERE stage IN ({','.join('?' * len(stages))}) "
            "AND pay_monthly_inr_mid IS NOT NULL", stages).fetchall()
        return [r["v"] for r in rows]

    pmax = conn.execute(
        f"SELECT MAX(pay_monthly_inr_max) AS m FROM opportunities WHERE stage IN "
        f"({','.join('?' * len(PIPELINE_STAGES))})", PIPELINE_STAGES).fetchone()["m"]
    best_offer = conn.execute(
        "SELECT MAX(pay_monthly_inr_mid) AS m FROM opportunities WHERE stage='offer'").fetchone()["m"]
    needs_open = conn.execute("SELECT COUNT(*) AS n FROM needs_prerit WHERE status='open'").fetchone()["n"]
    return {
        "found": found,
        "verified": reached("verified"),
        "drafted": reached("drafted"),
        "applied": applied,
        "replies": reached("replies"),
        "interviews": interviews,
        "offers": offers,
        "rejected": by_stage.get("rejected", 0),
        "filtered": by_stage.get("filtered", 0),
        "success_rate": round((interviews + offers) / applied, 4) if applied else None,
        "needs_open": needs_open,
        "cloud_cost_today_usd": round(float(grok["cost"]), 4),
        "cloud_budget_usd": float(settings.get("cloud_daily_budget_usd", 2.0)),
        "cloud_calls_today": int(grok["n"]),
        "local_tokens_today": int(local["t"]),
        "pay": {
            "pipeline_median_inr": _median(mids(PIPELINE_STAGES)),
            "pipeline_max_inr": pmax,
            "best_offer_inr": best_offer,
            "median_applied_inr": _median(mids(REACHED["applied"])),
        },
        "by_stage": by_stage,
        "sim": bool(settings.get("sim_enabled", True)),
    }


def snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    settings = get_settings(conn)
    return {
        "settings": settings,
        "agents": agents_json(conn),
        "opportunities": opp_summaries(conn, repo.list_opportunity_rows(conn, limit=500)),
        "events": repo.list_events(conn, limit=200),
        "stats": stats(conn, settings),
        "needs": [need_json(n) for n in repo.list_need_rows(conn, status="open")],
        "notifications_unacked": conn.execute("SELECT COUNT(*) FROM notifications WHERE acknowledged_at IS NULL"
                                              ).fetchone()[0],
        "server_time": now_iso(),
        "last_event_id": repo.last_event_id(conn),
    }


def health(conn: sqlite3.Connection) -> dict[str, Any]:
    alive, hb = worker_alive(conn)
    refusal = get_settings(conn).get("worker_refusal")
    return {"ok": True, "worker_alive": alive, "worker_heartbeat_at": hb, "version": __version__,
            "worker_refusal": (refusal or {}).get("reason")}
