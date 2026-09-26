"""Writer (draft.cover_letter; also cold emails for email-channel research roles) and polish.final (Claude).

Inputs are verified facts with ids, the posting's verified quotes (J1…), the document rules and two gold exemplars;
never legacy `angle` notes or unconfirmed profile values. Output is one entry per sentence with its citations,
stored as a versioned document whose lineage records every model that wrote any version."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from hq.adapters.base import Deferred, RunContext, RunResult
from hq.llm import cloud
from hq.llm.prompts import load_schema
from hq.llm.router import EscalationExhausted
from hq.pipeline.agents.common import label, load_opp, loads, sim_or_none
from hq.pipeline.draft.writer_input import doc_config, doc_rules, writer_messages
from hq.profile.facts import load_facts
from hq.util.ids import new_id
from hq.util.timeutil import iso_in

MAIN_KINDS = ("cover_letter", "cold_email", "research_statement")


def doc_kind_for(opp: dict[str, Any]) -> str:
    if opp.get("apply_channel") == "email" and (opp.get("role_type") == "research" or
                                                 opp.get("kind") in ("research_internship", "program")):
        return "cold_email"
    return "cover_letter"


def latest_doc(ctx: RunContext, opp_id: str) -> dict[str, Any] | None:
    rows = ctx.query("SELECT * FROM documents WHERE opportunity_id=? AND kind IN ('cover_letter','cold_email',"
                     "'research_statement') AND status!='historical' ORDER BY version DESC, created_at DESC LIMIT 1",
                     (opp_id,))
    return rows[0] if rows else None


def application_for(ctx: RunContext, opp_id: str) -> dict[str, Any] | None:
    rows = ctx.query("SELECT * FROM applications WHERE opportunity_id=? AND status NOT IN ('historical_frozen',"
                     "'withdrawn') ORDER BY created_at DESC LIMIT 1", (opp_id,))
    return rows[0] if rows else None


def job_quotes(opp: dict[str, Any]) -> dict[str, str]:
    return {f"J{i + 1}": q for i, q in enumerate(loads(opp.get("job_quotes_json"), []))}


def clean_sentences(raw: Any, quotes: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for s in (raw or {}).get("sentences", []) if isinstance(raw, dict) else []:
        if not isinstance(s, dict) or not str(s.get("text", "")).strip():
            continue
        text = " ".join(str(s["text"]).split())
        out.append({"idx": len(out), "text": text, "kind": s.get("kind") or "claim",
                    "fact_ids": [f for f in s.get("fact_ids") or [] if isinstance(f, str)],
                    "job_quote_ids": [q for q in s.get("job_quote_ids") or [] if q in quotes],
                    "paragraph": s.get("paragraph")})
    return out


def assemble(sentences: list[dict[str, Any]], doc_kind: str) -> str:
    """Salutation on its own line, body paragraphs (writer's `paragraph` or grouped by kind), closing, sign-off."""
    rules = doc_rules(doc_kind)
    cfg = doc_config()
    paras: list[list[str]] = []
    key_prev = None
    for s in sentences:
        key = ("salutation" if s["kind"] == "salutation" else "closing" if s["kind"] == "closing"
               else f"p{s.get('paragraph')}" if s.get("paragraph") is not None else
               "motivation" if s["kind"] in ("motivation", "job_reference") else "claim")
        if key != key_prev or key == "salutation":
            paras.append([])
            key_prev = key
        paras[-1].append(s["text"])
    body = "\n\n".join(" ".join(p) for p in paras)
    if rules.signoff:
        signoff = cfg.get("signoff") or "Best regards,\nPrerit Sangwan"
        body += "\n\n" + signoff + "\n" + (cfg.get("contact_line") or "")
    return body.strip() + "\n"


def lineage_of(doc: dict[str, Any] | None) -> list[str]:
    return list(loads(doc.get("lineage_models_json"), [])) if doc else []


async def run(task: dict[str, Any], ctx: RunContext) -> RunResult:
    sim = await sim_or_none(task, ctx)
    if sim is not None:
        return sim
    opp = load_opp(ctx)
    if opp is None:
        return RunResult(output={"ok": False, "noop": True}, summary="opportunity gone")
    if task["capability"] == "polish.final":
        return await polish(task, ctx, opp)
    return await draft(task, ctx, opp)


async def draft(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any]) -> RunResult:
    payload = task.get("payload") or {}
    version = int(payload.get("version") or 1)
    loop = int(payload.get("loop") or version)
    feedback = payload.get("feedback")
    prev = latest_doc(ctx, opp["id"])
    app = application_for(ctx, opp["id"])
    doc_kind = (app or {}).get("doc_kind") or doc_kind_for(opp)
    quotes = job_quotes(opp)
    msgs = writer_messages(org=opp["company_name"], role=opp["title"], doc_kind=doc_kind, job_quotes=quotes,
                           feedback=feedback if isinstance(feedback, list) else ([feedback] if feedback else None))
    try:
        res = await ctx.llm("writer", msgs, load_schema("draft"), max_tokens=1200, temperature=0.2,
                            task_type="draft", now_line=f"Drafting v{version} for {label(opp)}…")
    except EscalationExhausted as exc:
        raise Deferred("queued", iso_in(1800), f"no writer model or Claude available ({exc})") from exc
    sentences = clean_sentences(res.output, quotes)
    if not sentences:
        return RunResult(output={"ok": False, "version": version, "loop": loop, "feedback": "empty draft"},
                         summary=f"{label(opp)}: the writer returned no sentences", model_id=res.model_id)
    text = assemble(sentences, doc_kind)
    doc_id = new_id()
    effects: list[dict[str, Any]] = []
    app_id = app["id"] if app else new_id()
    if not app:
        effects.append({"op": "application.create", "values": {
            "id": app_id, "opportunity_id": opp["id"], "channel": opp.get("apply_channel") or "manual",
            "status": "drafting", "mode": "dry_run", "doc_kind": doc_kind}})
    subject = (res.output or {}).get("subject") if isinstance(res.output, dict) else None
    effects.append({"op": "document.create", "values": {
        "id": doc_id, "application_id": app_id, "opportunity_id": opp["id"], "kind": doc_kind,
        "version": (prev["version"] + 1) if prev else version, "parent_id": prev["id"] if prev else None,
        "content_text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(), "author_agent": ctx.agent.id,
        "author_model": res.model_id, "lineage_models_json": json.dumps(sorted(set(lineage_of(prev)) | {res.model_id})),
        "status": "checking", "subject": subject}, "sentences": sentences})
    effects.append({"op": "application.update", "id": app_id, "values": {"status": "checking", "letter_doc_id": doc_id}})
    return RunResult(output={"ok": True, "version": version, "loop": loop, "doc_id": doc_id},
                     effects=effects, summary=f"Drafted {doc_kind.replace('_', ' ')} v{version} for {label(opp)} "
                                              f"({len(sentences)} sentences)",
                     model_id=res.model_id, prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens,
                     tok_s=res.tok_s, cost_usd=res.cost_usd)


async def polish(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any]) -> RunResult:
    """Claude rewrites the latest version (to fix remaining issues, or to lift a high-fit letter). The result is a new
    version authored by Claude; every layer then re-checks it and sign-off uses a different Claude model."""
    payload = task.get("payload") or {}
    prev = latest_doc(ctx, opp["id"])
    if prev is None:
        return RunResult(output={"ok": False, "noop": True}, summary="nothing to polish")
    quotes = job_quotes(opp)
    sents = ctx.query("SELECT text, kind, fact_ids_json, job_quote_ids_json FROM document_sentences WHERE "
                      "document_id=? ORDER BY idx", (prev["id"],))
    current = [{"text": s["text"], "kind": s["kind"], "fact_ids": loads(s["fact_ids_json"], []),
                "job_quote_ids": loads(s["job_quote_ids_json"], [])} for s in sents]
    fb = payload.get("feedback")
    task_line = ("Improve this draft so it is more specific to the role while keeping every claim cited. "
                 if payload.get("reason") == "high fit" else "Fix the problems listed below; keep everything else. ")
    msgs = writer_messages(org=opp["company_name"], role=opp["title"], doc_kind=prev["kind"], job_quotes=quotes,
                           task=task_line + "CURRENT DRAFT (JSON):\n" + json.dumps({"sentences": current}),
                           feedback=fb if isinstance(fb, list) else ([fb] if fb else None), sheet=load_facts())
    system, user = msgs[0]["content"], msgs[1]["content"]
    res = await ctx.claude("polish.final", user, load_schema("draft"), system_prompt=system,
                           model=await cloud.pick(ctx.services.claude, ctx.settings))
    model = res.model
    sentences = clean_sentences(res.output, quotes)
    if not sentences:
        return RunResult(output={"ok": False}, summary="polish returned nothing", cost_usd=res.cost_usd)
    text = assemble(sentences, prev["kind"])
    doc_id = new_id()
    author = cloud.tag(model)
    effects = [{"op": "document.create", "values": {
        "id": doc_id, "application_id": prev["application_id"], "opportunity_id": opp["id"], "kind": prev["kind"],
        "version": prev["version"] + 1, "parent_id": prev["id"], "content_text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(), "author_agent": ctx.agent.id, "author_model": author,
        "lineage_models_json": json.dumps(sorted(set(lineage_of(prev)) | {author})), "status": "checking",
        "subject": prev.get("subject")}, "sentences": sentences}]
    if prev["application_id"]:
        effects.append({"op": "application.update", "id": prev["application_id"], "values": {"letter_doc_id": doc_id}})
    return RunResult(output={"ok": True, "version": prev["version"] + 1, "loop": int(payload.get("loop") or 1),
                             "polished": True, "doc_id": doc_id},
                     effects=effects, summary=f"{cloud.label(model)} polished {label(opp)} (v{prev['version'] + 1})",
                     model_id=author, cost_usd=res.cost_usd, prompt_tokens=res.input_tokens,
                     completion_tokens=res.output_tokens)


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w[\w'-]*\b", text))
