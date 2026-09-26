"""Shared queries used by the API and the worker. Functions take a connection and never open their own
transaction, so callers can compose them inside `tx(conn)`."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from hq.db.conn import dumps, row_to_dict
from hq.util.ids import new_id
from hq.util.timeutil import now_iso

TERMINAL_STAGES = {"filtered", "rejected", "offer", "frozen", "skipped"}
STAGES = ["found", "verified", "drafted", "checked", "applied", "replied", "interview", "offer", "rejected",
          "filtered", "frozen", "skipped"]
EVENT_LEVELS = ("debug", "info", "warn", "error", "alert")


# ── events ────────────────────────────────────────────────────────────────────────────────────────────
def emit(conn: sqlite3.Connection, type_: str, message: str, *, level: str = "info", agent_id: str | None = None,
         opportunity_id: str | None = None, task_id: str | None = None, data: Any = None) -> int:
    cur = conn.execute(
        "INSERT INTO events(ts, type, level, agent_id, opportunity_id, task_id, message, data_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (now_iso(), type_, level, agent_id, opportunity_id, task_id, message, dumps(data if data is not None else {})),
    )
    return int(cur.lastrowid)


def event_json(row: sqlite3.Row | dict) -> dict[str, Any]:
    r = dict(row)
    data = r.get("data_json")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    return {"id": r["id"], "ts": r["ts"], "type": r["type"], "level": r["level"], "agent_id": r["agent_id"],
            "opportunity_id": r["opportunity_id"], "task_id": r["task_id"], "message": r["message"],
            "data": data or {}}


def list_events(conn: sqlite3.Connection, *, after: int | None = None, before: int | None = None, limit: int = 200,
                agent: str | None = None, level: str | None = None, type_: str | None = None,
                q: str | None = None, opportunity_id: str | None = None) -> list[dict[str, Any]]:
    """Events newest-last. With `after`, the oldest `limit` events after it; otherwise the newest `limit`."""
    limit = max(1, min(int(limit), 500))
    where, params = [], []
    if after is not None:
        where.append("id > ?")
        params.append(after)
    if before is not None:
        where.append("id < ?")
        params.append(before)
    if agent:
        where.append("agent_id = ?")
        params.append(agent)
    if opportunity_id:
        where.append("opportunity_id = ?")
        params.append(opportunity_id)
    if level:
        levels = [lv for lv in level.split(",") if lv in EVENT_LEVELS]
        if levels:
            where.append(f"level IN ({','.join('?' * len(levels))})")
            params.extend(levels)
    if type_:
        types = [t.strip() for t in type_.split(",") if t.strip()]
        clauses = []
        for t in types:
            if t.endswith("*") or t.endswith("."):
                clauses.append("type LIKE ?")
                params.append(t.rstrip("*") + "%")
            else:
                clauses.append("type = ?")
                params.append(t)
        if clauses:
            where.append("(" + " OR ".join(clauses) + ")")
    if q:
        where.append("message LIKE ?")
        params.append(f"%{q}%")
    sql = "SELECT * FROM events" + (" WHERE " + " AND ".join(where) if where else "")
    if after is not None:
        rows = conn.execute(sql + " ORDER BY id ASC LIMIT ?", (*params, limit)).fetchall()
    else:
        rows = list(reversed(conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()))
    return [event_json(r) for r in rows]


def last_event_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(id) AS m FROM events").fetchone()
    return int(row["m"] or 0)


# ── audit / commands ─────────────────────────────────────────────────────────────────────────────────
def audit(conn: sqlite3.Connection, actor: str, action: str, target: str | None, before: Any = None,
          after: Any = None, remote_addr: str | None = None) -> str:
    audit_id = new_id()
    conn.execute(
        "INSERT INTO audit_log(id, ts, actor, action, target, before_json, after_json, remote_addr) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (audit_id, now_iso(), actor, action, target, dumps(before), dumps(after), remote_addr),
    )
    return audit_id


def add_command(conn: sqlite3.Connection, kind: str, payload: dict | None = None) -> str:
    cmd_id = new_id()
    conn.execute("INSERT INTO commands(id, ts, kind, payload_json) VALUES (?,?,?,?)",
                 (cmd_id, now_iso(), kind, dumps(payload or {})))
    return cmd_id


def pending_commands(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM commands WHERE consumed_at IS NULL ORDER BY ts, id").fetchall()
    return [row_to_dict(r) for r in rows]


def consume_command(conn: sqlite3.Connection, cmd_id: str, result: Any = None) -> None:
    conn.execute("UPDATE commands SET consumed_at=?, result_json=? WHERE id=?", (now_iso(), dumps(result), cmd_id))


# ── opportunities ────────────────────────────────────────────────────────────────────────────────────
OPP_WRITABLE = {
    "company_name", "title", "kind", "role_type", "summary", "location_raw", "city", "country_iso2", "lat", "lon",
    "work_mode", "url", "apply_url", "apply_channel", "apply_email", "apply_email_quote", "deadline_at",
    "deadline_confidence", "posted_at", "start_date", "duration_months", "hours_per_week", "pay_raw", "pay_min",
    "pay_max", "pay_currency", "pay_period", "pay_status", "pay_monthly_local_min", "pay_monthly_local_max",
    "pay_monthly_inr_min", "pay_monthly_inr_mid", "pay_monthly_inr_max", "pay_hourly_inr_min",
    "pay_hourly_inr_max", "fx_rate", "fx_date", "benefits_json", "living_cost_monthly_inr", "living_cost_basis",
    "living_cost_confidence", "pay_ratio", "eligibility_status", "eligibility_confidence", "availability_status",
    "scam_status", "fit_score", "fit_breakdown_json", "stage", "stage_reason", "link_status", "source_label",
    "notes_unverified", "last_verified_at", "description_path", "desc_hash",
}


def _clean_values(values: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    bad = set(values) - allowed
    if bad:
        raise ValueError(f"columns not writable: {sorted(bad)}")
    return {k: (dumps(v) if k.endswith("_json") and not isinstance(v, str) else v) for k, v in values.items()}


def insert_opportunity(conn: sqlite3.Connection, values: dict[str, Any], *, is_simulated: bool) -> str:
    vals = _clean_values({k: v for k, v in values.items() if k not in ("id", "canonical_key")}, OPP_WRITABLE)
    opp_id = values.get("id") or new_id()
    now = now_iso()
    vals.update(id=opp_id, canonical_key=values["canonical_key"], is_simulated=int(is_simulated),
                first_seen_at=now, updated_at=now)
    cols = ",".join(vals)
    conn.execute(f"INSERT INTO opportunities({cols}) VALUES ({','.join('?' * len(vals))})", tuple(vals.values()))
    return opp_id


def update_opportunity(conn: sqlite3.Connection, opp_id: str, values: dict[str, Any]) -> None:
    if not values:
        return
    vals = _clean_values(values, OPP_WRITABLE)
    vals["updated_at"] = now_iso()
    sets = ",".join(f"{k}=?" for k in vals)
    conn.execute(f"UPDATE opportunities SET {sets} WHERE id=?", (*vals.values(), opp_id))


def get_opportunity_row(conn: sqlite3.Connection, opp_id: str) -> dict[str, Any] | None:
    return row_to_dict(conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone())


def list_opportunity_rows(conn: sqlite3.Connection, *, stage: str | None = None, q: str | None = None,
                          sim: int | None = None, limit: int = 500) -> list[dict[str, Any]]:
    where, params = [], []
    if stage:
        stages = [s for s in stage.split(",") if s]
        where.append(f"stage IN ({','.join('?' * len(stages))})")
        params.extend(stages)
    if q:
        where.append("(company_name LIKE ? OR title LIKE ? OR city LIKE ?)")
        params.extend([f"%{q}%"] * 3)
    if sim is not None:
        where.append("is_simulated = ?")
        params.append(int(bool(sim)))
    sql = "SELECT * FROM opportunities" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY updated_at DESC LIMIT ?"
    rows = conn.execute(sql, (*params, max(1, min(int(limit), 2000)))).fetchall()
    return [row_to_dict(r) for r in rows]


def active_agents_by_opp(conn: sqlite3.Connection, opp_ids: Iterable[str] | None = None) -> dict[str, str]:
    rows = conn.execute(
        "SELECT opportunity_id, lease_owner FROM tasks WHERE status IN ('leased','running') "
        "AND opportunity_id IS NOT NULL ORDER BY updated_at"
    ).fetchall()
    wanted = set(opp_ids) if opp_ids is not None else None
    return {r["opportunity_id"]: r["lease_owner"] for r in rows if wanted is None or r["opportunity_id"] in wanted}


def opps_with_open_needs(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT opportunity_id FROM needs_prerit WHERE status='open' AND opportunity_id IS NOT NULL"
    ).fetchall()
    return {r["opportunity_id"] for r in rows}


# ── needs ─────────────────────────────────────────────────────────────────────────────────────────────
def insert_need(conn: sqlite3.Connection, values: dict[str, Any]) -> str:
    need_id = values.get("id") or new_id()
    allowed = {"opportunity_id", "application_id", "kind", "title", "instructions_md", "answers_json", "files_json",
               "direct_url", "priority", "due_at", "est_minutes", "status"}
    vals = _clean_values({k: v for k, v in values.items() if k != "id"}, allowed)
    vals.update(id=need_id, created_at=now_iso())
    conn.execute(f"INSERT INTO needs_prerit({','.join(vals)}) VALUES ({','.join('?' * len(vals))})",
                 tuple(vals.values()))
    return need_id


def get_need_row(conn: sqlite3.Connection, need_id: str) -> dict[str, Any] | None:
    return row_to_dict(conn.execute("SELECT * FROM needs_prerit WHERE id=?", (need_id,)).fetchone())


def list_need_rows(conn: sqlite3.Connection, status: str | None = "open",
                   opportunity_id: str | None = None) -> list[dict[str, Any]]:
    where, params = [], []
    if status:
        statuses = status.split(",")
        where.append(f"status IN ({','.join('?' * len(statuses))})")
        params.extend(statuses)
    if opportunity_id:
        where.append("opportunity_id = ?")
        params.append(opportunity_id)
    sql = "SELECT * FROM needs_prerit" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY priority DESC, created_at DESC LIMIT 500"
    return [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


# ── agents ────────────────────────────────────────────────────────────────────────────────────────────
def agent_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [row_to_dict(r) for r in conn.execute("SELECT * FROM agents ORDER BY rowid").fetchall()]


def agent_row(conn: sqlite3.Connection, agent_id: str) -> dict[str, Any] | None:
    return row_to_dict(conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone())


def live_rows(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {r["agent_id"]: dict(r) for r in conn.execute("SELECT * FROM agent_live").fetchall()}


def live_row(conn: sqlite3.Connection, agent_id: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM agent_live WHERE agent_id=?", (agent_id,)).fetchone()
    return dict(r) if r else None


def set_live(conn: sqlite3.Connection, agent_id: str, **fields: Any) -> None:
    """Update agent_live fields and bump seq so the SSE tailer sends an `agent.live` update."""
    allowed = {"now_line", "progress", "current_task_id", "opportunity_id", "model_id", "tok_s", "heartbeat_at"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"agent_live columns not writable: {sorted(bad)}")
    fields["updated_at"] = now_iso()
    sets = ",".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE agent_live SET {sets}, seq=seq+1 WHERE agent_id=?", (*fields.values(), agent_id))


def worker_heartbeat_at(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT value_json FROM settings WHERE key='worker_heartbeat_at'").fetchone()
    return json.loads(row["value_json"]) if row else None
