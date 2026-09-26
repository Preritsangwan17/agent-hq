"""Helpers shared by the built-in agent modules."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hq.adapters.base import Deferred, RunContext, RunResult
from hq.db.conn import dumps
from hq.util.ids import new_id
from hq.util.timeutil import iso_in


def load_opp(ctx: RunContext) -> dict[str, Any] | None:
    if not ctx.opportunity_id:
        return None
    rows = ctx.query("SELECT * FROM opportunities WHERE id=?", (ctx.opportunity_id,))
    return rows[0] if rows else None


async def sim_or_none(task: dict[str, Any], ctx: RunContext) -> RunResult | None:
    """Simulated opportunities keep flowing through the simulator (and wait while the sim is switched off)."""
    opp = load_opp(ctx)
    if opp is None or not opp["is_simulated"]:
        return None
    if not ctx.settings.get("sim_enabled", True):
        raise Deferred("queued", iso_in(60), "simulation is switched off")
    if ctx.services.sim is None:
        raise Deferred("queued", iso_in(60), "no simulator in this worker")
    return await ctx.services.sim.run(task, ctx)


def noop(reason: str) -> RunResult:
    return RunResult(output={"ok": False, "noop": True, "reason": reason}, summary=f"Skipped: {reason}")


def posting_text(opp: dict[str, Any]) -> str:
    p = opp.get("description_path")
    if p and Path(p).exists():
        return Path(p).read_text(errors="replace")
    return ""


def loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def label(opp: dict[str, Any]) -> str:
    return f"{opp['company_name']} — {opp['title']}"


def need_effect(opp: dict[str, Any] | None, *, kind: str, title: str, instructions: str, priority: int = 50,
                est_minutes: float = 1, payload: dict[str, Any] | None = None, answers: list[dict] | None = None,
                files: list[dict] | None = None, direct_url: str | None = None, due_at: str | None = None,
                application_id: str | None = None, need_id: str | None = None) -> dict[str, Any]:
    return {"op": "need.create", "values": {
        "id": need_id or new_id(), "opportunity_id": opp["id"] if opp else None, "application_id": application_id,
        "kind": kind, "title": title, "instructions_md": instructions, "priority": priority, "est_minutes": est_minutes,
        "payload_json": dumps(payload or {}), "answers_json": dumps(answers or []), "files_json": dumps(files or []),
        "direct_url": direct_url, "due_at": due_at}}


def open_decision(ctx: RunContext, opp_id: str, decision: str) -> dict[str, Any] | None:
    rows = ctx.query("SELECT * FROM needs_prerit WHERE opportunity_id=? AND kind='decision' AND "
                     "json_extract(payload_json, '$.decision')=? ORDER BY created_at DESC LIMIT 1", (opp_id, decision))
    return rows[0] if rows else None


def decision_choice(ctx: RunContext, opp_id: str, decision: str) -> str | None:
    """Prerit's answer to a decision item ('keep'/'drop'), or None while it is open/absent. Dismissing = drop."""
    row = open_decision(ctx, opp_id, decision)
    if row and row["status"] in ("done", "dismissed"):
        return loads(row["payload_json"], {}).get("choice") or ("drop" if row["status"] == "dismissed" else None)
    return None


def decision_effect(opp: dict[str, Any], decision: str, title: str, instructions: str, *,
                    keep_label: str = "Keep going", drop_label: str = "Drop it", priority: int = 55) -> dict[str, Any]:
    return need_effect(opp, kind="decision", title=title, instructions=instructions, priority=priority, est_minutes=0.5,
                       payload={"decision": decision, "options": [{"value": "keep", "label": keep_label},
                                                                   {"value": "drop", "label": drop_label}]})


def confirmed(ctx: RunContext) -> dict[str, str]:
    from hq.profile.fields import confirmed_fields

    return confirmed_fields(ctx.conn, outbound=True)


def has_role_model(ctx: RunContext, role: str) -> bool:
    """A local model is assigned to the role and local models are switched on (Settings › Budget)."""
    if ctx.settings.get("llm_local_enabled", True) is False:
        return False
    return bool(ctx.query("SELECT 1 FROM role_assignments WHERE role=? LIMIT 1", (role,)))
