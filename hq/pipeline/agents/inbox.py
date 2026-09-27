"""Inbox Watcher (inbox.poll, inbox.classify, reply.send) — CONTRACT_D §2.

poll: every run hands simulated work to the simulator; every `gmail_poll_minutes` it syncs Gmail from the stored
historyId, keeps only in-scope mail, stores it and requests one classification per new message.
classify: deterministic rules first (a rule lock is final), then the classifier model; locks raise an alert, a macOS
notification and a Needs Prerit item, and nothing is ever sent on that thread. Job alerts become opportunities.
Info requests get a gated draft (auto-sent only when every condition in the contract holds).
reply.send: sends an approved reply through the guard.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hq.adapters.base import Deferred, RunContext, RunResult, TransientError
from hq.db.conn import tx
from hq.gmail.api import GmailAuthError, GmailError, GmailTransient
from hq.gmail.sender import reply_subject
from hq.llm.prompts import load_prompt, load_schema
from hq.llm.router import EscalationExhausted
from hq.pipeline.agents.common import label as opp_label, load_opp, need_effect, sim_or_none
from hq.pipeline.apply import guard
from hq.pipeline.discover.dedupe import find_duplicate
from hq.pipeline.discover.postings import opportunity_values
from hq.pipeline.inbox import alerts, ats_resolve, career, replies, rules as rules_mod, sync
from hq.pipeline.verify.link import check_link
from hq.util import timeutil
from hq.util.ids import new_id

MAX_PER_POLL = 40
LOCK_TITLES = {"interview": "Interview request", "assessment": "Assessment invite", "offer": "Offer",
               "legal": "Legal / documents", "money": "Money request", "missing_info": "Personal details requested"}


async def run(task: dict[str, Any], ctx: RunContext) -> RunResult:
    cap = task["capability"]
    if cap == "inbox.poll":
        return await poll(task, ctx)
    if cap == "reply.send":
        return await send_reply(task, ctx)
    sim = await sim_or_none(task, ctx)
    if sim is not None:
        return sim
    return await classify(task, ctx)


# ── poll ─────────────────────────────────────────────────────────────────────────────────────────────
def _gmail_due(ctx: RunContext) -> bool:
    st = ctx.settings.get("gmail_state") or {}
    last = timeutil.parse_iso(st.get("last_poll_at"))
    every = float(ctx.settings.get("gmail_poll_minutes", 3)) * 60
    return last is None or (timeutil.utcnow() - last).total_seconds() >= every - 5


async def poll(task: dict[str, Any], ctx: RunContext) -> RunResult:
    effects: list[dict[str, Any]] = []
    opp_results: list[tuple[str, dict[str, Any]]] = []
    lines: list[str] = []
    model_id, tok_s = None, None
    if ctx.settings.get("sim_enabled", True) and ctx.services.sim is not None:
        sim = await ctx.services.sim.run(task, ctx)
        effects += sim.effects
        opp_results += sim.opp_results
        model_id, tok_s = sim.model_id, sim.tok_s
        lines.append(sim.summary)
    gmail = ctx.services.gmail
    new = 0
    if gmail is not None and ctx.settings.get("read_job_emails", True) and _gmail_due(ctx):
        try:
            got, info = await sync_gmail(ctx, gmail)
            effects += got
            new = sum(1 for e in got if e["op"] == "email.store")
            lines.append(f"Gmail: {new} new in-scope message{'s' if new != 1 else ''}" + (f" ({info})" if info else ""))
        except GmailAuthError as exc:
            effects += _reconnect_effects(str(exc))
            lines.append(f"Gmail: {exc}")
        except (GmailTransient, GmailError) as exc:
            lines.append(f"Gmail unreachable ({exc}) — will retry")
    return RunResult(output={"ok": True, "new_messages": new}, effects=effects, opp_results=opp_results,
                     summary=" · ".join(x for x in lines if x) or "Inbox: nothing new", model_id=model_id, tok_s=tok_s)


def _reconnect_effects(reason: str) -> list[dict[str, Any]]:
    return [{"op": "gmail.state", "values": {"error": reason, "healthy": False}},
            {"op": "notification", "values": {"severity": "warn", "title": "Gmail needs reconnecting",
                                              "body": reason[:200], "url": "/settings?tab=gmail"}}]


async def sync_gmail(ctx: RunContext, gmail: Any) -> tuple[list[dict[str, Any]], str]:
    conn = ctx.conn
    state = ctx.settings.get("gmail_state") or {}
    ctx.progress(0.2, "Checking Gmail for new mail…")
    ids, latest, full = await sync.new_message_ids(gmail, state.get("history_id"))
    known = {r["gmail_message_id"] for r in ctx.query(
        f"SELECT gmail_message_id FROM email_messages WHERE gmail_message_id IN ({','.join('?' * len(ids))})",
        tuple(ids))} if ids else set()
    sc = sync.scope(conn)
    effects: list[dict[str, Any]] = []
    looked = 0
    truncated = False
    for gid in ids:
        if gid in known:
            continue
        if looked >= MAX_PER_POLL:
            truncated = True
            break
        looked += 1
        ctx.check_cancel()
        meta = await gmail.get_metadata(gid)
        why = sync.in_scope(meta, sc)
        if why is None:
            continue  # out of scope: body was never fetched, stored, or logged
        msg = await gmail.get_message(gid)
        opp_id, app_id, thread_row = sync.link(conn, msg, sc)
        thread_id = thread_row or (sc.thread_ids.get(msg.thread_id) or {}).get("id") or new_id()
        sc.thread_ids.setdefault(msg.thread_id, {"id": thread_id, "opportunity_id": opp_id, "application_id": app_id})
        msg_id = new_id()
        effects.append({"op": "email.store", "thread": {
            "id": thread_id, "gmail_thread_id": msg.thread_id, "opportunity_id": opp_id, "application_id": app_id,
            "subject": msg.subject[:300], "counterpart_domain": rules_mod.sender_parts(msg.from_addr)[1],
            "counterpart_addr": msg.from_addr},
            "message": {"id": msg_id, "gmail_message_id": msg.id, "direction": "inbound", "from_addr": msg.from_addr,
                        "to_addr": ", ".join(msg.to_addrs)[:300], "date": msg.internal_date or timeutil.now_iso(),
                        "subject": msg.subject[:300], "snippet": msg.snippet[:300], "body_path": sync.save_body(msg),
                        "rfc822_message_id": msg.rfc822_id, "in_reply_to": msg.in_reply_to,
                        "auth_results": (msg.headers.get("authentication-results") or "")[:1000],
                        "sender_name": msg.from_name[:200]}})
        if ctx.settings.get("classify_job_emails", True):
            effects.append({"op": "task.request", "capability": "inbox.classify", "payload": {"message_id": msg_id},
                            "opportunity_id": opp_id, "key": f"classify:{msg.id}"})
    now = timeutil.now_iso()
    effects.append({"op": "gmail.state", "values": {
        "history_id": state.get("history_id") if truncated else latest,
        "last_poll_at": now, "healthy": True, "error": None,
        **({"last_full_sync_at": now} if full else {})}})
    return effects, ("full sync of the last 30 days" if full else "")


# ── classify ─────────────────────────────────────────────────────────────────────────────────────────
def _load_message(ctx: RunContext, message_id: str | None) -> dict[str, Any] | None:
    if not message_id:
        return None
    rows = ctx.query("SELECT m.*, t.id AS t_id, t.gmail_thread_id, t.opportunity_id, t.application_id, "
                     "t.notify_only_lock, t.counterpart_addr, t.subject AS t_subject FROM email_messages m "
                     "JOIN email_threads t ON t.id=m.thread_id WHERE m.id=?", (message_id,))
    return rows[0] if rows else None


async def _model_opinion(ctx: RunContext, msg: dict[str, Any], body: str) -> dict[str, Any] | None:
    prior = ctx.query("SELECT id, direction, from_addr, subject, snippet, body_path, body_text FROM email_messages "
                      "WHERE thread_id=? AND id<>? ORDER BY COALESCE(date,'') DESC LIMIT 8",
                      (msg["t_id"], msg["id"]))
    context = []
    for old in reversed(prior):
        earlier = old.get("body_text") or ""
        if not earlier and old.get("body_path") and Path(old["body_path"]).exists():
            earlier = Path(old["body_path"]).read_text(errors="replace")
        context.append(f"{old['direction']} from {old['from_addr']}: {old['subject']}\n"
                       f"{(earlier or old.get('snippet') or '')[:650]}")
    msgs = [{"role": "system", "content": load_prompt("classify_email")},
            {"role": "user", "content": "PREVIOUS THREAD (context only; classify the latest message):\n"
             + ("\n---\n".join(context) if context else "None")
             + f"\n\nLATEST MESSAGE\nFROM: {msg['from_addr']}\nSUBJECT: {msg['subject']}\n\n{body[:6000]}"}]
    try:
        res = await ctx.llm("classifier", msgs, load_schema("email_class"), max_tokens=200, task_type="inbox.classify",
                            now_line=f"Classifying “{(msg['subject'] or '')[:40]}”…")
    except (EscalationExhausted, Deferred, TransientError):
        return None  # rules alone still lock; the model is a second opinion
    out = res.output if isinstance(res.output, dict) else {}
    if out.get("label") not in rules_mod.LABELS:
        return None
    return {"label": out["label"], "lock": bool(out.get("lock")), "confidence": float(out.get("confidence") or 0),
            "reason": out.get("reason"), "model_id": res.model_id}


async def _model_facts(ctx: RunContext, body: str, message_id: str, occurred_at: str,
                       verification: str) -> tuple[dict[str, Any], str | None]:
    """Optional active-mode extraction. Reject every fact without an exact supporting span in the email."""
    try:
        res = await ctx.llm("classifier", [{"role": "system", "content": load_prompt("extract_career")},
                                            {"role": "user", "content": body[:12_000]}],
                            load_schema("career_extract"), max_tokens=700, task_type="inbox.extract",
                            now_line="Extracting source-backed offer details…")
    except (EscalationExhausted, Deferred, TransientError):
        return {}, None
    data = res.output if isinstance(res.output, dict) else {}
    facts: dict[str, Any] = {}
    for field in (data.get("fields") or [])[:20]:
        if not isinstance(field, dict):
            continue
        key, value, evidence = field.get("key"), field.get("value"), field.get("evidence")
        if key not in career.FIELD_LABELS or not isinstance(value, str) or not isinstance(evidence, str):
            continue
        if len(value) > 300 or len(evidence) > 500 or value.casefold() not in evidence.casefold() or \
                evidence.casefold() not in body.casefold():
            continue
        is_link = key.endswith("_link") or key == "employee_portal"
        if is_link and (not value.startswith("https://") or not career._host(value)):
            continue
        facts[key] = {"value": value, "source_message_id": message_id, "source_date": occurred_at,
                      "evidence": evidence, "official": verification == "Verified Company" and not is_link}
    return facts, res.model_id


def merge(rule: rules_mod.RuleResult, model: dict[str, Any] | None) -> tuple[str, bool, float, str]:
    """(label, lock, confidence, reason). Lock = rules OR model. A confident model decides the label unless the
    rules saw something the model missed that matters more (a lock kind)."""
    lock = rule.lock or bool(model and model["lock"])
    if rule.label in ("scam", "rejection", "selected", "offer"):
        return rule.label, lock, 0.9 if rule.lock else 0.75, "rules: " + ", ".join(rule.reasons[:3])
    if model and model["confidence"] >= 0.6 and not (rule.label and rule.lock and not model["lock"]):
        return model["label"], lock, model["confidence"], f"model {model['model_id']}: {model.get('reason') or ''}"
    if rule.label:
        return rule.label, lock, 0.9 if rule.lock else 0.75, "rules: " + ", ".join(rule.reasons[:3])
    if model:
        return model["label"], lock, model["confidence"], f"model (low confidence): {model.get('reason') or ''}"
    return "other", lock, 0.3, "no rule matched and no classifier model is available"


def _gmail_link(gmail_thread_id: str | None) -> str | None:
    if not gmail_thread_id or gmail_thread_id.startswith(("mock-", "sim-")):
        return None
    return f"https://mail.google.com/mail/u/0/#all/{gmail_thread_id}"


async def _refresh_public_posting(ctx: RunContext, opp: dict[str, Any] | None) -> tuple[dict[str, Any] | None,
                                                                                         dict[str, str] | None]:
    """Recheck the stored public posting, never a link supplied by the new email."""
    if not opp or not opp.get("url") or ctx.services.fetcher is None:
        return opp, None
    last = timeutil.parse_iso(opp.get("last_verified_at"))
    if last and timeutil.utcnow() - last < timedelta(days=3):
        return opp, None
    try:
        result = await check_link(ctx.services.fetcher, canonical_key=opp["canonical_key"], url=opp["url"])
    except Exception as exc:  # research failure must not discard the received email
        return opp, {"status": "unavailable", "reason": f"Public posting check failed: {type(exc).__name__}"}
    return {**opp, "link_status": result.status, "last_verified_at": timeutil.now_iso()}, \
        {"status": result.status, "reason": result.reason}


async def classify(task: dict[str, Any], ctx: RunContext) -> RunResult:
    if not ctx.settings.get("classify_job_emails", True):
        return RunResult(output={"ok": True, "noop": True}, summary="email classification is off")
    msg = _load_message(ctx, (task.get("payload") or {}).get("message_id"))
    if msg is None:
        return RunResult(output={"ok": False, "noop": True}, summary="message gone")
    body = Path(msg["body_path"]).read_text(errors="replace") if msg.get("body_path") and \
        Path(msg["body_path"]).exists() else (msg.get("snippet") or "")
    rule = rules_mod.classify(msg["subject"] or "", body, msg["from_addr"] or "")
    opp = load_opp(ctx)
    current = ctx.query("SELECT communication_stage FROM career_profiles WHERE opportunity_id=?",
                        (opp["id"],)) if opp else []
    current_stage = current[0]["communication_stage"] if current else None
    if (task.get("payload") or {}).get("backfill"):
        if not opp:
            return RunResult(output={"ok": True, "noop": True}, summary="historical email has no linked application")
        label = msg.get("classification") or rule.label or "other"
        verification = career.assess(SimpleNamespace(from_addr=msg["from_addr"] or "",
                                                     subject=msg["subject"] or "", body_text=body,
                                                     headers={"authentication-results": msg.get("auth_results") or ""}), opp)
        stage = career.stage_for(label, body, current_stage)
        facts, checklist = career.extract(body, msg["id"], msg.get("date") or timeutil.now_iso(),
                                           verification["verification"]) if stage else ({}, [])
        if stage not in ("Assessment", "Interview", "Selected", "Offer", "Accepted", "Joining/Onboarding"):
            checklist = []
        return RunResult(output={"ok": True, "backfilled": True}, effects=[{
            "op": "career.update", "opportunity_id": opp["id"], "application_id": msg.get("application_id"),
            "message_id": msg["id"], "occurred_at": msg.get("date") or timeutil.now_iso(), "stage": stage,
            "verification": verification, "recruiter_name": msg.get("sender_name"),
            "recruiter_email": msg.get("from_addr"), "facts": facts, "checklist": checklist,
            "model_id": None, "research": None}], summary="Historical company email added to career timeline")
    who = opp_label(opp) if opp else msg["from_addr"]
    if rule.label == "job_alert":
        return await _job_alert(task, ctx, msg, body)
    model = await _model_opinion(ctx, msg, body)
    label, lock, conf, reason = merge(rule, model)
    opp, research = await _refresh_public_posting(ctx, opp)
    verification = career.assess(SimpleNamespace(from_addr=msg["from_addr"] or "", subject=msg["subject"] or "",
                                                 body_text=body, headers={"authentication-results":
                                                 msg.get("auth_results") or ""}), opp)
    if verification["verification"] == "Potentially Suspicious":
        lock = True
    lock_kind = rule.lock_kind or ({"interview_invite": "interview", "assessment": "assessment", "offer": "offer",
                                    "selected": "offer",
                                    "legal": "legal", "scam": "money"}.get(label) if lock else None) or \
        ("suspicious" if lock else None)
    effects: list[dict[str, Any]] = [{"op": "email.classify", "message_id": msg["id"], "thread_id": msg["t_id"],
                                      "classification": label, "confidence": round(conf, 3), "lock": lock,
                                      "lock_reason": lock_kind, "lock_terms": rule.lock_terms[:6],
                                      "reason": reason[:300], "verification": verification}]
    if research and opp:
        if research["status"] != "unavailable":
            effects.append({"op": "opp.update", "id": opp["id"], "values": {
                "link_status": research["status"], "last_verified_at": opp["last_verified_at"]}})
        verification["reasons"].append("Public posting check: " + research["reason"])
    output: dict[str, Any] = {"ok": True, "classification": label, "lock": lock, "confidence": round(conf, 3)}
    extract_model = None
    if opp:
        stage = career.stage_for(label, body, current_stage)
        facts, checklist = career.extract(body, msg["id"], msg.get("date") or timeutil.now_iso(),
                                           verification["verification"]) if stage else ({}, [])
        if stage not in ("Assessment", "Interview", "Selected", "Offer", "Accepted", "Joining/Onboarding"):
            checklist = []
        if stage in ("Offer", "Joining/Onboarding"):
            model_facts, extract_model = await _model_facts(ctx, body, msg["id"],
                                                            msg.get("date") or timeutil.now_iso(),
                                                            verification["verification"])
            facts = {**model_facts, **facts}  # explicit labeled lines win over model interpretation
        effects.append({"op": "career.update", "opportunity_id": opp["id"], "application_id": msg.get("application_id"),
                        "message_id": msg["id"], "occurred_at": msg.get("date") or timeutil.now_iso(),
                        "stage": stage, "verification": verification, "recruiter_name": msg.get("sender_name"),
                        "recruiter_email": msg.get("from_addr"), "facts": facts, "checklist": checklist,
                        "model_id": extract_model or (model or {}).get("model_id"), "research": research})
    if lock and not msg["notify_only_lock"]:
        need_kind = rules_mod.need_kind_for(lock_kind, label)
        title = f"{LOCK_TITLES.get(need_kind, 'Reply needed')}: {who}"
        terms = ", ".join(f"“{t}”" for t in rule.lock_terms[:4])
        link = _gmail_link(msg["gmail_thread_id"])
        instructions = (f"**Notify-only lock.** HQ will never write on this thread — reply yourself.\n\n"
                        f"From **{msg['from_addr']}** · “{msg['subject']}”\n\n> {(msg['snippet'] or '')[:280]}\n\n"
                        + (f"Why it's locked: {terms}\n\n" if terms else "")
                        + (f"[Open the thread in Gmail]({link})" if link else ""))
        effects.append(need_effect(opp, kind=need_kind, title=title, instructions=instructions,
                                   priority=99 if need_kind in ("offer", "money") else 95, est_minutes=5,
                                   direct_url=link, application_id=msg.get("application_id"),
                                   payload={"thread_id": msg["t_id"], "lock": lock_kind}))
        effects.append({"op": "notification", "values": {
            "severity": "alert", "title": title, "body": f"{msg['subject'] or ''} — reply yourself; HQ is locked out.",
            "url": f"/inbox?thread={msg['t_id']}"}})
        if opp:
            effects.append({"op": "opp.update", "id": opp["id"], "values": {
                "stage_reason": f"{LOCK_TITLES.get(need_kind, 'reply')} — notify-only, reply yourself"}})
        if verification["verification"] != "Potentially Suspicious" and ctx.settings.get("generate_email_replies", True):
            kind = label if label in ("interview_invite", "assessment", "offer") else \
                ("joining" if stage == "Joining/Onboarding" else None) if opp else None
            if kind and opp:
                effects += _approval_draft(msg, opp, kind)
    elif not lock and label == "info_request":
        effects += await _info_request(task, ctx, msg, rule, conf, model, opp,
                                       verification["verification"])
    elif opp and label in ("rejection", "auto_ack"):
        effects.append({"op": "opp.update", "id": opp["id"], "values": {
            "stage_reason": "rejection email" if label == "rejection" else "automatic acknowledgement"}})
    return RunResult(output=output, effects=effects,
                     summary=f"{who}: {label.replace('_', ' ')} ({conf:.2f})" + (" — notify-only lock" if lock else ""),
                     model_id=extract_model or (model or {}).get("model_id"))


def _approval_draft(msg: dict[str, Any], opp: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    sentences = replies.acknowledgement_sentences(kind, recipient=replies.recipient_name(msg.get("sender_name")),
                                                   company=opp["company_name"], role=opp["title"])
    ok, _ = replies.gate(sentences, doc_kind="reply", org=opp["company_name"])
    if not ok:
        return []
    body = replies.assemble(sentences)
    doc_id = new_id()
    return [{"op": "document.create", "values": {
        "id": doc_id, "application_id": msg.get("application_id"), "opportunity_id": opp["id"],
        "kind": "reply", "version": 1, "content_text": body, "sha256": hashlib.sha256(body.encode()).hexdigest(),
        "author_agent": "inbox", "author_model": "template", "status": "draft",
        "subject": reply_subject(msg["subject"]), "email_thread_id": msg["t_id"]}, "sentences": sentences},
        need_effect(opp, kind="approve_reply", title=f"Review {kind.replace('_', ' ')} reply: {opp['company_name']}",
                    instructions=("An acknowledgement draft is ready in the Inbox. It makes no offer decision or "
                                  "availability commitment. Review the source email and company verification, then "
                                  "edit the text if needed. This thread remains notify-only locked until you "
                                  "explicitly unlock and approve the reply."), priority=90, est_minutes=2,
                    application_id=msg.get("application_id"),
                    payload={"thread_id": msg["t_id"], "document_id": doc_id})]


async def _info_request(task: dict[str, Any], ctx: RunContext, msg: dict[str, Any], rule: rules_mod.RuleResult,
                        conf: float, model: dict[str, Any] | None, opp: dict[str, Any] | None,
                        verification: str) -> list[dict[str, Any]]:
    """Answer only the allowed items; auto-send only when rules AND model agree (≥ 0.9), every gate passes, auto
    replies are on and HQ has been live for 14 days. Otherwise: a draft + a Needs Prerit item."""
    s = ctx.settings
    if not s.get("generate_email_replies", True):
        return []
    allowed = rule.only_allowed_items()
    who = opp_label(opp) if opp else msg["from_addr"]
    if not allowed:
        asked = ", ".join(rule.requested) or "something HQ can't answer"
        return [need_effect(opp, kind="missing_info", title=f"They asked for {asked}: {who}",
                            instructions=(f"**{msg['from_addr']}** asked for {asked}. HQ only answers résumé, GitHub, "
                                          f"LinkedIn and repository requests on its own — reply yourself.\n\n> "
                                          f"{(msg['snippet'] or '')[:280]}"),
                            priority=80, est_minutes=3, direct_url=_gmail_link(msg["gmail_thread_id"]),
                            application_id=msg.get("application_id"), payload={"thread_id": msg["t_id"]})]
    company = opp["company_name"] if opp else None
    role = opp["title"] if opp else None
    sentences = replies.reply_sentences(rule.requested, recipient=replies.recipient_name(None), company=company,
                                        role=role)
    ok, problems = replies.gate(sentences, doc_kind="reply", org=company)
    text = replies.assemble(sentences)
    doc_id = new_id()
    live_since = timeutil.parse_iso(s.get("live_since"))
    auto_enabled = bool(s.get("auto_send_routine_replies") or s.get("auto_reply_enabled"))
    auto = (ok and auto_enabled and not s.get("ask_before_sending", True)
            and verification == "Verified Company" and guard.effective_mode(s) == "live" and live_since is not None
            and timeutil.utcnow() - live_since >= timedelta(days=14) and rule.label == "info_request"
            and model is not None and model["label"] == "info_request" and model["confidence"] >= 0.9 and conf >= 0.9)
    attach = "resume" in rule.requested
    effects: list[dict[str, Any]] = [{"op": "document.create", "values": {
        "id": doc_id, "application_id": msg.get("application_id"), "opportunity_id": (opp or {}).get("id"),
        "kind": "reply", "version": 1, "content_text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "author_agent": "inbox", "author_model": "template", "status": "approved" if auto else "draft",
        "subject": reply_subject(msg["subject"]), "email_thread_id": msg["t_id"]},
        "sentences": sentences}]
    if auto:
        effects.append({"op": "task.request", "capability": "reply.send", "payload": {"document_id": doc_id,
                                                                                     "attach_resume": attach},
                        "opportunity_id": (opp or {}).get("id"), "key": f"reply:{doc_id}"})
        return effects
    why = "auto-replies are off" if not auto_enabled else (
        "the gates flagged it: " + "; ".join(problems) if not ok else "not confident enough to send on its own")
    effects.append(need_effect(opp, kind="approve_reply", title=f"Reply draft for {who}",
                               instructions=(f"**{msg['from_addr']}** asked for: {', '.join(rule.requested)}. HQ "
                                             f"drafted this reply ({why}).\n\n---\n\n{text}\n---\n\nSend it as is, or "
                                             "edit it in the Inbox first." + (" The résumé PDF is attached."
                                                                              if attach else "")),
                               priority=70, est_minutes=1, application_id=msg.get("application_id"),
                               payload={"thread_id": msg["t_id"], "document_id": doc_id, "attach_resume": attach}))
    return effects


async def _job_alert(task: dict[str, Any], ctx: RunContext, msg: dict[str, Any], body: str) -> RunResult:
    found = alerts.postings(msg["subject"] or "", body, msg["from_addr"] or "")
    effects: list[dict[str, Any]] = [{"op": "email.classify", "message_id": msg["id"], "thread_id": msg["t_id"],
                                      "classification": "job_alert", "confidence": 0.95, "lock": False,
                                      "lock_reason": None, "lock_terms": [], "reason": f"{len(found)} roles parsed"}]
    opp_results: list[tuple[str, dict[str, Any]]] = []
    resolved = 0
    for p in found:
        ctx.check_cancel()
        ats = await ats_resolve.resolve(ctx.services.fetcher, ctx.conn, p.company, p.title)
        posting = ats or p
        dup = find_duplicate(ctx.conn, posting)
        if dup:
            continue
        label = f"Job alert → {posting.source_kind.title()}" if ats else f"Job alert · {p.extra.get('alert_sender')}"
        values = opportunity_values(posting, source_label=label)
        if not ats:
            values["apply_channel"] = "manual"
        resolved += bool(ats)
        effects.append({"op": "opp.create", "values": values, "is_simulated": False})
        effects.append({"op": "opp.source", "values": {"opportunity_id": values["id"], "source_id": p.source_id,
                                                        "external_id": p.external_id, "source_url": p.url or None}})
        opp_results.append((values["id"], {"created": True}))
    return RunResult(output={"ok": True, "classification": "job_alert", "created": len(opp_results)},
                     effects=effects, opp_results=opp_results,
                     summary=f"Job alert from {msg['from_addr']}: {len(found)} target role(s), {len(opp_results)} new"
                             + (f", {resolved} found on the company's own ATS" if resolved else ""))


# ── reply.send ───────────────────────────────────────────────────────────────────────────────────────
async def send_reply(task: dict[str, Any], ctx: RunContext) -> RunResult:
    p = task.get("payload") or {}
    rows = ctx.query("SELECT d.*, t.counterpart_addr, t.notify_only_lock, t.id AS t_id FROM documents d JOIN "
                     "email_threads t ON t.id=d.email_thread_id WHERE d.id=?", (p.get("document_id"),))
    if not rows:
        return RunResult(output={"ok": False, "noop": True}, summary="reply draft gone")
    doc = rows[0]
    if doc["status"] == "sent":
        return RunResult(output={"ok": True, "noop": True}, summary="reply already sent")
    if doc["status"] != "approved":
        return RunResult(output={"ok": False, "noop": True}, summary="reply not approved")
    sents = ctx.query("SELECT text, kind, fact_ids_json FROM document_sentences WHERE document_id=? ORDER BY idx",
                      (doc["id"],))
    if sents:
        import json

        entries = [{"text": r["text"], "kind": r["kind"], "fact_ids": json.loads(r["fact_ids_json"] or "[]"),
                    "job_quote_ids": []} for r in sents]
        opp = load_opp(ctx)
        ok, problems = replies.gate(entries, doc_kind="reply", org=(opp or {}).get("company_name"))
        if not ok:
            with tx(ctx.conn):
                ctx.conn.execute("UPDATE documents SET status='failed' WHERE id=?", (doc["id"],))
            return RunResult(output={"ok": False}, summary="reply blocked by the gates: " + "; ".join(problems)[:200])
    attachments = []
    if p.get("attach_resume"):
        attachments = _resume_attachment(ctx, doc.get("application_id"))
    try:
        res = await guard.send(ctx.conn, ctx.services.gmail, kind="reply", to_addr=doc["counterpart_addr"] or "",
                               subject=doc["subject"] or "Re:", body=doc["content_text"] or "", attachments=attachments,
                               content_sha=doc["sha256"] or hashlib.sha256((doc["content_text"] or "").encode())
                               .hexdigest(), application_id=doc.get("application_id"), thread_id=doc["t_id"],
                               agent_id="inbox", task_id=task["id"])
    except guard.GuardBlocked as exc:
        if exc.kind in ("paused",):
            raise Deferred("queued", timeutil.iso_in(600), exc.reason) from exc
        if exc.kind == "cap":
            from hq.worker.budget import next_midnight_ist

            raise Deferred("queued", timeutil.to_iso(next_midnight_ist()), exc.reason) from exc
        with tx(ctx.conn):
            ctx.conn.execute("UPDATE documents SET status='failed' WHERE id=?", (doc["id"],))
        return RunResult(output={"ok": False, "reason": exc.kind}, summary=f"Reply not sent: {exc.reason}")
    with tx(ctx.conn):
        ctx.conn.execute("UPDATE documents SET status='sent' WHERE id=?", (doc["id"],))
    return RunResult(output={"ok": True, "status": res.status}, summary=f"Reply sent to {doc['counterpart_addr']} "
                                                                        f"({res.mode})")


def _resume_attachment(ctx: RunContext, application_id: str | None) -> list[dict[str, str]]:
    if application_id:
        rows = ctx.query("SELECT d.content_path FROM applications a JOIN documents d ON d.id=a.resume_doc_id WHERE "
                         "a.id=?", (application_id,))
        if rows and rows[0]["content_path"] and Path(rows[0]["content_path"]).exists():
            return [{"name": "Prerit_Sangwan_Resume.pdf", "path": rows[0]["content_path"]}]
    from hq import settings as paths
    from hq.resume.compact import build_compact
    from hq.resume.content import content, focus_for, project_order

    out = paths.ARTIFACTS / "replies" / "Prerit_Sangwan_Resume.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    build_compact(out, summary=content()["summaries"][focus_for(None)], order=project_order(None, ""))
    return [{"name": out.name, "path": str(out)}]
