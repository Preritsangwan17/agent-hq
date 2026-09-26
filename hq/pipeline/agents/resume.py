"""Résumé Builder (build.resume): approved bullets only, one page, post-checked; then the approval gate.

Picks the approved summary and project order for the role, renders the HTML résumé to PDF (Chrome/Chromium) and a
compact fpdf version, checks that the PDF is one page and that every word on it is approved text. In approve-first
mode it opens an `approve` item bound to the sha256 of the exact letter + résumé; any rewrite invalidates it."""
from __future__ import annotations

import hashlib
from typing import Any

from hq import settings as paths
from hq.adapters.base import RunContext, RunResult
from hq.pipeline.agents.common import label, load_opp, need_effect, sim_or_none
from hq.pipeline.agents.writer import application_for, latest_doc
from hq.pipeline.apply.guard import approval_sha
from hq.resume.builder import build
from hq.resume.compact import build_compact
from hq.resume.builder import check_pdf
from hq.resume.content import content, focus_for, project_order
from hq.util import netguard
from hq.util.ids import new_id

MOCK_ATS_PORT = 8799


def apply_route(opp: dict[str, Any]) -> str:
    url = opp.get("apply_url") or opp.get("url") or ""
    if netguard.host_of(url) in ("127.0.0.1", "localhost") and f":{MOCK_ATS_PORT}" in url:
        return "mock_ats"
    if opp.get("apply_channel") == "email" and opp.get("apply_email") and opp.get("automation") != "manual_lane":
        return "email"
    return "pack"


async def run(task: dict[str, Any], ctx: RunContext) -> RunResult:
    sim = await sim_or_none(task, ctx)
    if sim is not None:
        return sim
    opp = load_opp(ctx)
    if opp is None:
        return RunResult(output={"ok": False, "noop": True}, summary="opportunity gone")
    doc = latest_doc(ctx, opp["id"])
    app = application_for(ctx, opp["id"])
    if doc is None or doc["status"] != "passed" or app is None:
        return RunResult(output={"ok": False, "noop": True}, summary=f"{label(opp)}: no approved letter yet")
    summary = content()["summaries"][focus_for(opp.get("role_type"))]
    order = project_order(opp.get("role_type"), opp.get("title", ""))
    out_dir = paths.ARTIFACTS / "applications" / opp["id"] / f"v{doc['version']}"
    ctx.progress(0.3, f"Rendering résumé for {label(opp)}…")
    html_path, pdf, chk, renderer = await build(out_dir, summary=summary, order=order)
    compact = build_compact(out_dir / "Prerit_Sangwan_Resume_compact.pdf", summary=summary, order=order)
    compact_chk = check_pdf(compact, summary)
    chosen, chosen_chk = (pdf, chk) if chk.ok else (compact, compact_chk)
    effects: list[dict[str, Any]] = []
    if not chosen_chk.ok:
        effects.append(need_effect(opp, kind="review_letter", title=f"Résumé check failed for {label(opp)}",
                                   instructions=f"The rendered résumé is {chosen_chk.pages} page(s) and contains "
                                                f"unapproved words: {', '.join(chosen_chk.unapproved[:12])}. "
                                                f"Check `{out_dir}`.", application_id=app["id"], priority=55))
        return RunResult(output={"ok": False, "stage_reason": "résumé check failed"}, effects=effects,
                         summary=f"{label(opp)}: résumé failed its check")
    sha = hashlib.sha256(chosen.read_bytes()).hexdigest()
    rid = new_id()
    effects.append({"op": "document.create", "values": {
        "id": rid, "application_id": app["id"], "opportunity_id": opp["id"], "kind": "resume_pdf", "version": doc["version"],
        "content_path": str(chosen), "sha256": sha, "author_agent": ctx.agent.id, "author_model": renderer,
        "status": "passed", "content_text": summary}})
    effects.append({"op": "application.update", "id": app["id"], "values": {"resume_doc_id": rid}})
    route = apply_route(opp)
    letter_path = out_dir / ("email.txt" if doc["kind"] == "cold_email" else "cover_letter.txt")
    letter_path.write_text(doc["content_text"] or "")
    output: dict[str, Any] = {"ok": True, "apply_channel": route, "resume_path": str(chosen)}
    if ctx.settings.get("autonomy") == "approve_first":
        digest = approval_sha(doc["content_text"] or "", sha, None)
        preview = (f"**{label(opp)}** — {route.replace('_', ' ')} application, ready to go.\n\n"
                   f"Letter v{doc['version']} (fact-checked and signed off):\n\n---\n\n{doc['content_text']}\n\n---\n\n"
                   "Approving binds to this exact letter and résumé; any rewrite needs a new approval.")
        effects.append(need_effect(opp, kind="approve", title=f"Approve: {label(opp)}", instructions=preview,
                                   priority=65, est_minutes=1, application_id=app["id"],
                                   files=[{"name": chosen.name, "path": str(chosen)},
                                          {"name": letter_path.name, "path": str(letter_path)}],
                                   payload={"sha256": digest, "route": route, "document_id": doc["id"]}))
        effects.append({"op": "application.update", "id": app["id"], "values": {"status": "awaiting_approval"}})
        output["approval_required"] = True
    return RunResult(output=output, effects=effects,
                     summary=f"Résumé for {label(opp)}: 1 page via {renderer if chosen == pdf else 'fpdf'}"
                             + (" — waiting for your approval" if output.get("approval_required") else f", next: {route}"),
                     model_id=renderer)
