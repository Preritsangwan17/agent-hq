"""Fact-Checker (factcheck.deterministic, factcheck.sentence, check.quality) and Reviewer (factcheck.signoff).

The fact gate runs every layer on every version: (a) deterministic rules, (b) an independent local verifier whose
model differs from every model in the document's lineage ("partial" fails), (c) Claude sign-off with a Claude model
that didn't write or polish the text. Any failure sends targeted feedback back to the Writer and all layers run
again; after 3 loops there is one Claude polish, and if it still fails the letter goes to Needs Prerit for review.
"""
from __future__ import annotations

import json
from typing import Any

from hq.adapters.base import Deferred, RunContext, RunResult
from hq.llm import cloud
from hq.llm.prompts import load_prompt, load_schema
from hq.llm.router import EscalationExhausted
from hq.util.timeutil import iso_in
from hq.models import roles as roles_mod
from hq.pipeline.agents.common import has_role_model, confirmed, label, load_opp, loads, need_effect, sim_or_none
from hq.pipeline.agents.writer import job_quotes, latest_doc
from hq.pipeline.draft.writer_input import facts_block
from hq.pipeline.gates.fact_deterministic import check_document
from hq.pipeline.gates.quality import check_quality
from hq.profile.facts import load_facts

MAX_LOOPS = 3
RUBRIC_SCHEMA = {"type": "object", "required": ["score"], "properties": {
    "score": {"type": "integer", "minimum": 1, "maximum": 5}, "reasons": {"type": "string"}}}
RUBRIC_PROMPT = ("You rate how specific a job application letter is to ONE employer and role, from 1 (generic, could "
                 "be sent anywhere) to 5 (clearly written for this role: names the organisation, refers to concrete "
                 "details from the posting, connects them to the applicant's real projects). Return only JSON "
                 '{"score": 1-5, "reasons": "short"}.')


async def run(task: dict[str, Any], ctx: RunContext) -> RunResult:
    sim = await sim_or_none(task, ctx)
    if sim is not None:
        return sim
    opp = load_opp(ctx)
    if opp is None:
        return RunResult(output={"ok": False, "noop": True}, summary="opportunity gone")
    doc = latest_doc(ctx, opp["id"])
    if doc is None:
        return RunResult(output={"ok": False, "noop": True}, summary="no draft to check")
    cap = task["capability"]
    handler = {"factcheck.deterministic": deterministic, "factcheck.sentence": sentence_check,
               "check.quality": quality, "factcheck.signoff": signoff}[cap]
    return await handler(task, ctx, opp, doc)


def _sentences(ctx: RunContext, doc_id: str) -> list[dict[str, Any]]:
    return [{"id": r["id"], "idx": r["idx"], "text": r["text"], "kind": r["kind"],
             "fact_ids": loads(r["fact_ids_json"], []), "job_quote_ids": loads(r["job_quote_ids_json"], [])}
            for r in ctx.query("SELECT * FROM document_sentences WHERE document_id=? ORDER BY idx", (doc_id,))]


def _carry(task: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    p = task.get("payload") or {}
    return {"version": int(p.get("version") or doc["version"]), "loop": int(p.get("loop") or 1),
            **({"polished": True} if p.get("polished") else {})}


async def _polish_allowed(ctx: RunContext) -> bool:
    return has_role_model(ctx, "writer") or await cloud.pick(ctx.services.claude, ctx.settings, task_type="polish.final") is not None


async def _fail(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any], doc: dict[str, Any], layer: str,
                feedback: list[str], effects: list[dict[str, Any]], summary: str,
                model_id: str | None = None) -> RunResult:
    carry = _carry(task, doc)
    allowed = await _polish_allowed(ctx)
    effects = effects + [{"op": "document.update", "id": doc["id"], "values": {"status": "failed"}},
                         {"op": "gate_result", "values": {"application_id": doc["application_id"], "document_id": doc["id"],
                                                          "gate": layer, "passed": 0,
                                                          "details_json": json.dumps({"feedback": feedback})}}]
    out = {"ok": False, **carry, "feedback": feedback[:12], "polish_allowed": allowed}
    exhausted = carry["loop"] >= MAX_LOOPS and (carry.get("polished") or not allowed)
    if exhausted:
        effects.append(need_effect(
            opp, kind="review_letter", title=f"Review the letter for {label(opp)}",
            instructions=("The fact gate still rejects this letter after 3 rewrites"
                          + (" and a Claude polish" if carry.get("polished") else "") + ". Edit it yourself or skip "
                          "the role. Problems found:\n\n" + "\n".join(f"- {f}" for f in feedback[:10])
                          + f"\n\n---\n\n{doc['content_text']}"),
            priority=60, est_minutes=5, application_id=doc["application_id"],
            payload={"document_id": doc["id"], "layer": layer}))
    return RunResult(output=out, effects=effects, summary=summary, model_id=model_id)


def _pass(task: dict[str, Any], doc: dict[str, Any], layer: str, effects: list[dict[str, Any]], summary: str,
          extra: dict[str, Any] | None = None, model_id: str | None = None, cost: float | None = None) -> RunResult:
    effects = effects + [{"op": "gate_result", "values": {"application_id": doc["application_id"],
                                                          "document_id": doc["id"], "gate": layer, "passed": 1,
                                                          "details_json": json.dumps(extra or {})}}]
    return RunResult(output={"ok": True, **_carry(task, doc), **(extra or {})}, effects=effects, summary=summary,
                     model_id=model_id, cost_usd=cost)


# ── (a) deterministic rules ──────────────────────────────────────────────────────────────────────────
async def deterministic(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any], doc: dict[str, Any]) -> RunResult:
    sents = _sentences(ctx, doc["id"])
    report = check_document(sents, job_quotes=job_quotes(opp), confirmed_fields=confirmed(ctx), require_citations=True)
    effects: list[dict[str, Any]] = []
    feedback = []
    for s, r in zip(sents, report.sentences):
        if r["violations"]:
            rules = [v["rule"] for v in r["violations"]]
            effects.append({"op": "fact_check", "values": {
                "document_id": doc["id"], "sentence_id": s["id"], "layer": "deterministic", "verdict": "unsupported",
                "rule_ids_json": json.dumps(rules), "unsupported_span": r["violations"][0]["span"][:200],
                "explanation": "; ".join(v["message"] for v in r["violations"])[:500]}})
            feedback.append(f"Sentence {s['idx'] + 1} (“{s['text'][:100]}”): " + "; ".join(
                f"{v['rule']} — {v['message']} (“{v['span']}”)" for v in r["violations"]))
    if feedback:
        return await _fail(task, ctx, opp, doc, "fact.deterministic", feedback, effects,
                           f"{label(opp)} v{doc['version']}: {len(feedback)} sentence(s) blocked by the fact rules")
    return _pass(task, doc, "fact.deterministic", effects,
                 f"{label(opp)} v{doc['version']}: all {len(sents)} sentences pass the fact rules")


# ── (b) independent local verifier ───────────────────────────────────────────────────────────────────
async def sentence_check(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any], doc: dict[str, Any]) -> RunResult:
    sents = _sentences(ctx, doc["id"])
    lineage = loads(doc.get("lineage_models_json"), [])
    lines, prev = [], "(start)"
    for i, s in enumerate(sents):
        lines.append(f"[{i}] PREVIOUS: {prev}\n[{i}] SENTENCE: {s['text']}")
        prev = s["text"]
    msgs = [{"role": "system", "content": load_prompt("fact_checker")},
            {"role": "user", "content": f"FACTS:\n{facts_block(load_facts())}\n\nSENTENCES:\n" + "\n\n".join(lines)}]
    try:
        res = await ctx.llm("fact_checker", msgs, load_schema("factcheck"), lineage=tuple(lineage), allow_claude=False,
                            max_tokens=1600, now_line=f"Checking {len(sents)} sentences for {opp['company_name']}…")
    except EscalationExhausted:
        return _pass(task, doc, "fact.local", [], f"{label(opp)}: no independent local checker — Claude sign-off decides",
                     extra={"skipped": "no local checker independent of the authors"})
    if not roles_mod.checker_allowed(res.model_id, lineage):
        return _pass(task, doc, "fact.local", [], "local checker not independent — skipped",
                     extra={"skipped": "checker in lineage"})
    got = {r["i"]: r for r in (res.output or {}).get("results", []) if isinstance(r, dict) and isinstance(r.get("i"), int)}
    effects: list[dict[str, Any]] = []
    feedback = []
    for i, s in enumerate(sents):
        r = got.get(i, {})
        verdict = r.get("verdict", "na")
        effects.append({"op": "fact_check", "values": {
            "document_id": doc["id"], "sentence_id": s["id"], "layer": "local", "checker_model": res.model_id,
            "verdict": verdict, "unsupported_span": (r.get("unsupported_span") or None),
            "explanation": (r.get("explanation") or None)}})
        if verdict in ("unsupported", "partial"):
            feedback.append(f"Sentence {i + 1} (“{s['text'][:100]}”): the checker says {verdict}"
                            + (f" — “{r.get('unsupported_span')}”" if r.get("unsupported_span") else "")
                            + (f": {r.get('explanation')}" if r.get("explanation") else ""))
    if feedback:
        return await _fail(task, ctx, opp, doc, "fact.local", feedback, effects,
                           f"{label(opp)} v{doc['version']}: checker {res.model_id} flagged {len(feedback)} sentence(s)",
                           model_id=res.model_id)
    return _pass(task, doc, "fact.local", effects, f"{label(opp)} v{doc['version']}: {res.model_id} supports every claim",
                 model_id=res.model_id)


# ── quality gate ─────────────────────────────────────────────────────────────────────────────────────
async def quality(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any], doc: dict[str, Any]) -> RunResult:
    sents = _sentences(ctx, doc["id"])
    recent = [r["content_text"] for r in ctx.query(
        "SELECT content_text FROM documents WHERE kind=? AND opportunity_id!=? AND status IN ('passed','sent') "
        "ORDER BY created_at DESC LIMIT 20", (doc["kind"], opp["id"])) if r["content_text"]]
    rubric = None
    rubric_model = None
    try:
        res = await ctx.llm("summarizer", [{"role": "system", "content": RUBRIC_PROMPT},
                                           {"role": "user", "content": f"ROLE: {opp['title']} at {opp['company_name']}\n\n"
                                                                       f"LETTER:\n{doc['content_text']}"}],
                            RUBRIC_SCHEMA, lineage=tuple(loads(doc.get("lineage_models_json"), [])), allow_claude=False,
                            max_tokens=200, now_line="Rating specificity…")
        rubric, rubric_model = float(res.output.get("score")), res.model_id
    except (EscalationExhausted, TypeError, ValueError, AttributeError):
        rubric = None
    report = check_quality(sents, doc_kind=doc["kind"], org=opp["company_name"], recent_texts=recent,
                           rubric_score=rubric)
    if not report.passed:
        return await _fail(task, ctx, opp, doc, "quality", report.failures(), [],
                           f"{label(opp)} v{doc['version']}: quality gate — " + "; ".join(report.failures())[:200],
                           model_id=rubric_model)
    p = task.get("payload") or {}
    polish = (int(opp.get("fit_score") or 0) >= int(ctx.settings.get("fit_polish_threshold", 75))
              and not p.get("polished") and await _polish_allowed(ctx))
    return _pass(task, doc, "quality", [], f"{label(opp)} v{doc['version']}: quality gate passed"
                 + (f" (specificity {rubric:.0f}/5)" if rubric else "") + (" — high fit, local-first polish next" if polish else ""),
                 extra={"polish": polish, "checks": report.checks}, model_id=rubric_model)


# ── (c) Claude sign-off ──────────────────────────────────────────────────────────────────────────────
async def signoff(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any], doc: dict[str, Any]) -> RunResult:
    s = ctx.settings
    required = bool(s.get("require_claude_signoff", True)) or roles_mod.needs_claude_signoff(ctx.conn)
    effects: list[dict[str, Any]] = []
    if not required:
        effects.append({"op": "document.update", "id": doc["id"], "values": {"status": "passed"}})
        return _pass(task, doc, "fact.signoff", effects, f"{label(opp)}: sign-off not required (setting off)",
                     extra={"skipped": "require_claude_signoff is off"})
    lineage = set(loads(doc.get("lineage_models_json"), []))
    model = await cloud.signoff_model(ctx.services.claude, s, lineage) if ctx.services.claude else None
    if model is None:  # every reachable cloud model wrote part of this text (or none is reachable): wait
        raise Deferred("queued", iso_in(3600), "no independent cloud model is available for sign-off" + (
            " — every cloud model is switched off; switch one on or turn off Require sign-off (Settings › Budget)"
            if not cloud.order(s) else ""))
    mid = cloud.tag(model)
    sents = _sentences(ctx, doc["id"])
    lines, prev = [], "(start)"
    for i, x in enumerate(sents):
        lines.append(f"[{i}] PREVIOUS: {prev}\n[{i}] SENTENCE: {x['text']}")
        prev = x["text"]
    res = await ctx.claude("factcheck.signoff", f"FACTS:\n{facts_block(load_facts())}\n\nSENTENCES:\n" + "\n\n".join(lines),
                           load_schema("factcheck"), system_prompt=load_prompt("fact_checker"), model=model)
    got = {r["i"]: r for r in (res.output or {}).get("results", []) if isinstance(r, dict) and isinstance(r.get("i"), int)}
    feedback = []
    for i, x in enumerate(sents):
        r = got.get(i, {})
        verdict = r.get("verdict", "na")
        effects.append({"op": "fact_check", "values": {
            "document_id": doc["id"], "sentence_id": x["id"], "layer": "signoff", "checker_model": mid,
            "verdict": verdict, "unsupported_span": r.get("unsupported_span"), "explanation": r.get("explanation")}})
        if verdict in ("unsupported", "partial"):
            feedback.append(f"Sentence {i + 1} (“{x['text'][:100]}”): {cloud.label(model)} sign-off says {verdict}"
                            + (f" — “{r.get('unsupported_span')}”" if r.get("unsupported_span") else ""))
    if feedback:
        return await _fail(task, ctx, opp, doc, "fact.signoff", feedback, effects,
                           f"{label(opp)}: {cloud.label(model)} sign-off rejected {len(feedback)} sentence(s)",
                           model_id=mid)
    effects.append({"op": "document.update", "id": doc["id"], "values": {"status": "passed"}})
    return _pass(task, doc, "fact.signoff", effects,
                 f"{label(opp)} v{doc['version']}: signed off by {cloud.label(model)} {model.split(':')[-1]}",
                 model_id=mid, cost=res.cost_usd)
