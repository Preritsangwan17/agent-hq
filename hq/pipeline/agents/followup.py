"""Follow-up agent (followup.schedule, followup.send) — CONTRACT_D §4. Scheduling happens right after an email
application goes out; sending runs on the agent's interval and only touches follow-ups that are due."""
from __future__ import annotations

from typing import Any

from hq.adapters.base import RunContext, RunResult
from hq.pipeline import followup as fu
from hq.pipeline.agents.common import label, load_opp, sim_or_none
from hq.pipeline.agents.writer import application_for


async def run(task: dict[str, Any], ctx: RunContext) -> RunResult:
    if not ctx.settings.get("auto_followup_enabled", True):
        return RunResult(output={"ok": True, "noop": True}, summary="Automatic follow-ups are off")
    if task["capability"] == "followup.send":
        results = await fu.run_due(ctx.conn, ctx.services.gmail, task_id=task["id"])
        if not results:
            return RunResult(output={"ok": True, "noop": True}, summary="No follow-ups due")
        counts: dict[str, int] = {}
        for status, _ in results:
            counts[status] = counts.get(status, 0) + 1
        return RunResult(output={"ok": True, **counts},
                         summary="Follow-ups: " + ", ".join(f"{n} {k}" for k, n in counts.items()))
    sim = await sim_or_none(task, ctx)
    if sim is not None:
        return sim
    opp = load_opp(ctx)
    app = application_for(ctx, opp["id"]) if opp else None
    if opp is None or app is None:
        return RunResult(output={"ok": False, "noop": True}, summary="nothing to follow up")
    values, why = fu.schedule_values(ctx.conn, app, opp)
    if values is None:
        return RunResult(output={"ok": True, "scheduled": False, "reason": why}, summary=f"{label(opp)}: {why}")
    return RunResult(output={"ok": True, "scheduled": True, "due_at": values["due_at"]},
                     effects=[{"op": "followup.create", "values": values},
                              {"op": "application.update", "id": app["id"], "values": {"followup_due_at":
                                                                                          values["due_at"]}}],
                     summary=f"{label(opp)}: one follow-up scheduled for {values['due_at'][:10]} (only if no reply)")
