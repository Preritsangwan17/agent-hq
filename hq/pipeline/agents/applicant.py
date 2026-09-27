"""Applicant (apply.email_send, apply.manual_pack, apply.ats_submit) — DRY RUN.

Before anything goes out: a pre-submit recheck (pause, freeze, scam, eligibility, and the link/deadline again when
last verified more than 24 h ago). Email goes only through apply/guard.py (mock mailbox in dry run). ATS forms and
manual-lane sites become a pre-filled Needs Prerit pack: direct link, copy-able answers (unconfirmed profile values
are left for Prerit and flagged), the letter, the résumé, pay and deadline — built to take under two minutes.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from hq.adapters.base import Deferred, RunContext, RunResult
from hq.pipeline.agents.common import label, load_opp, need_effect, sim_or_none
from hq.pipeline.agents.writer import application_for, latest_doc
from hq.pipeline.apply import guard
from hq.pipeline.apply.answers import DEFAULT_QUESTIONS, answer_all
from hq.pipeline.discover.fetch import FetchBlocked
from hq.pipeline.verify.link import check_link, deadline_state
from hq.util.timeutil import iso_in, parse_iso, to_iso
from hq.worker.budget import next_midnight_ist


async def run(task: dict[str, Any], ctx: RunContext) -> RunResult:
    sim = await sim_or_none(task, ctx)
    if sim is not None:
        return sim
    opp = load_opp(ctx)
    if opp is None:
        return RunResult(output={"ok": False, "noop": True}, summary="opportunity gone")
    app = application_for(ctx, opp["id"])
    doc = latest_doc(ctx, opp["id"])
    if app is None or doc is None or doc["status"] != "passed":
        return RunResult(output={"ok": False, "noop": True}, summary=f"{label(opp)}: nothing approved to send")
    cap = task["capability"]
    if cap == "apply.manual_pack":
        return await manual_pack(task, ctx, opp, app, doc)
    blocked = await recheck(ctx, opp)
    if blocked:
        return blocked
    if cap == "apply.email_send":
        return await email(task, ctx, opp, app, doc)
    if cap == "apply.ats_submit":
        from hq.pipeline.apply.browser import submit_mock_ats

        return await submit_mock_ats(task, ctx, opp, app, doc)
    return RunResult(output={"ok": True, "noop": True}, summary=f"{cap}: nothing to do")


async def recheck(ctx: RunContext, opp: dict[str, Any]) -> RunResult | None:
    reasons = guard.precheck(ctx.conn, opp, ctx.settings)
    if any(r in ("PAUSE ALL is on", "outbound is frozen") for r in reasons):
        raise Deferred("queued", iso_in(600), reasons[0])
    last = parse_iso(opp.get("last_verified_at"))
    if not last or datetime.now(timezone.utc) - last > timedelta(hours=24):
        ctx.progress(0.2, f"Re-checking {label(opp)} is still open…")
        if ctx.services.fetcher is None:
            reasons.append("posting could not be re-verified (fetcher unavailable)")
        else:
            try:
                lk = await check_link(ctx.services.fetcher, canonical_key=opp["canonical_key"], url=opp.get("url"))
                if lk.status != "live":
                    reasons.append(f"posting not verified open ({lk.reason})")
            except (FetchBlocked, LookupError, ValueError) as exc:
                reasons.append(f"posting could not be re-verified ({type(exc).__name__})")
    elif opp.get("link_status") != "live":
        reasons.append("posting is not verified open")
    state, why = deadline_state(opp.get("deadline_at"))
    if state == "expired":
        reasons.append(why)
    if reasons:
        return RunResult(output={"ok": False, "stage_reason": "; ".join(reasons)},
                         effects=[{"op": "opp.update", "id": opp["id"], "values": {"stage_reason": "Not sent: " + "; ".join(reasons)}}],
                         summary=f"{label(opp)}: not sent — {'; '.join(reasons)}")
    return None


def _resume(ctx: RunContext, app: dict[str, Any]) -> dict[str, Any] | None:
    if not app.get("resume_doc_id"):
        return None
    rows = ctx.query("SELECT * FROM documents WHERE id=?", (app["resume_doc_id"],))
    return rows[0] if rows else None


async def email(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any], app: dict[str, Any],
                doc: dict[str, Any]) -> RunResult:
    resume = _resume(ctx, app)
    sha = guard.approval_sha(doc["content_text"] or "", resume["sha256"] if resume else None, None)
    subject = doc.get("subject") or f"Application: {opp['title']} — Prerit Sangwan"
    attachments = [{"name": Path(resume["content_path"]).name, "path": resume["content_path"]}] if resume else []
    try:
        res = await guard.send(ctx.conn, ctx.services.gmail, kind="application", to_addr=opp["apply_email"],
                               subject=subject, body=doc["content_text"] or "", attachments=attachments,
                               content_sha=sha, application_id=app["id"], agent_id=ctx.agent.id, task_id=task["id"])
    except guard.GuardBlocked as exc:
        if exc.kind == "paused":
            raise Deferred("queued", iso_in(600), exc.reason) from exc
        if exc.kind == "cap":
            raise Deferred("queued", to_iso(next_midnight_ist()), exc.reason) from exc
        if exc.kind in ("recipient", "failed"):
            return RunResult(output={"ok": False, "fallback_pack": True, "stage_reason": exc.reason},
                             summary=f"{label(opp)}: not emailing ({exc.reason}) — building a pack instead")
        if exc.kind == "ambiguous":
            return RunResult(output={"ok": False, "stage_reason": "send unconfirmed — check Sent (Needs Prerit)"},
                             summary=f"{label(opp)}: {exc.reason}")
        return RunResult(output={"ok": False, "stage_reason": exc.reason}, summary=f"{label(opp)}: {exc.reason}")
    return RunResult(output={"ok": True, "message_id": res.message_id, "status": res.status},
                     effects=[{"op": "document.update", "id": doc["id"], "values": {"status": "sent"}}],
                     summary=f"{label(opp)}: " + ("sent to the mock mailbox (dry run)" if res.mode == "dry_run"
                                                  else f"sent via Gmail ({res.mode})")
                             + (" — already sent before" if res.status == "duplicate" else ""))


async def greenhouse_questions(ctx: RunContext, opp: dict[str, Any]) -> list[dict[str, Any]] | None:
    kind, _, rest = opp["canonical_key"].partition(":")
    if kind != "greenhouse" or ctx.services.fetcher is None:
        return None
    slug, _, jid = rest.partition(":")
    from hq.pipeline.discover.ats import MOCK_BASE

    base = (f"{MOCK_BASE}/boards-api" if (opp.get("url") or "").startswith(MOCK_BASE)
            else "https://boards-api.greenhouse.io")
    try:
        res = await ctx.services.fetcher.get(f"{base}/v1/boards/{slug}/jobs/{jid}?questions=true", kind="api")
        data = res.json() if res.status == 200 else {}
    except Exception:
        return None
    out = []
    for q in data.get("questions") or []:
        fields = q.get("fields") or [{}]
        ftype = fields[0].get("type", "")
        options = [v.get("label") for f in fields for v in f.get("values") or [] if isinstance(v, dict)]
        out.append({"label": q.get("label", "").strip(), "required": bool(q.get("required")),
                    "type": "file" if ftype == "input_file" else "text", "options": options or None})
    return out or None


async def manual_pack(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any], app: dict[str, Any],
                      doc: dict[str, Any]) -> RunResult:
    questions = await greenhouse_questions(ctx, opp) or DEFAULT_QUESTIONS
    answers = answer_all(ctx.conn, questions)
    resume = _resume(ctx, app)
    files = []
    if resume:
        files.append({"name": Path(resume["content_path"]).name, "path": resume["content_path"]})
    letter = Path(resume["content_path"]).parent / "cover_letter.txt" if resume else None
    if letter and letter.exists():
        files.append({"name": letter.name, "path": str(letter)})
    missing = [a for a in answers if a.status == "needs_prerit"]
    never = [a for a in answers if a.status == "never"]
    rows = [{"label": a.label, "value": a.value or ("— you decide —" if a.status == "never" else "— missing —"),
             "copy": a.status == "filled", "status": a.status, "note": a.note, "required": a.required} for a in answers
            if a.status != "file"]
    rows.insert(0, {"label": "Cover letter", "value": doc["content_text"] or "", "copy": True, "status": "filled"})
    pay = f"₹{opp['pay_monthly_inr_min']:,.0f}/month" if opp.get("pay_monthly_inr_min") else (opp.get("pay_raw") or "not stated")
    due = opp.get("deadline_at")
    flags = "".join(f"\n- ⚠️ **{a.label}** — {a.note or 'fill this in yourself'}" for a in missing + never)
    instructions = (f"1. Open the form: {opp.get('apply_url') or opp.get('url')}\n"
                    "2. Paste the answers below (copy buttons) and upload the files.\n"
                    "3. Submit, then press **I submitted it** here.\n\n"
                    f"**Pay:** {pay} · **Deadline:** {due[:10] if due else 'rolling'} · "
                    f"**Channel:** {'manual-lane site (HQ never automates it)' if opp.get('automation') == 'manual_lane' else 'ATS form'}"
                    + (f"\n\n**Needs you:**{flags}" if flags else ""))
    est = round(min(10.0, 1.0 + 0.1 * len(rows) + 0.5 * len(missing)), 1)
    need = need_effect(opp, kind="submit_form", title=f"Submit: {label(opp)}", instructions=instructions,
                       answers=rows, files=files, direct_url=opp.get("apply_url") or opp.get("url"), due_at=due,
                       priority=70 if due else 60, est_minutes=est, application_id=app["id"],
                       payload={"missing": [a.label for a in missing], "never": [a.label for a in never]})
    effects = [need, {"op": "application.update", "id": app["id"],
                      "values": {"status": "needs_prerit", "pack_need_id": need["values"]["id"],
                                 "answers_json": [a.as_dict() for a in answers]}}]
    return RunResult(output={"ok": True, "pack": True, "missing": len(missing)}, effects=effects,
                     summary=f"Pack ready for {label(opp)} ({len(rows)} answers, {len(missing)} for you)")


def content_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
