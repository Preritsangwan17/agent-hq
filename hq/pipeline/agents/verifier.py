"""Verifier (verify.link, verify.deadline, verify.eligibility(+availability), verify.eligibility_hard, verify.scam,
verify.pay, score.fit). Domain outcomes (closed, expired, ineligible, scam, unpaid) are stage changes with a
reason, never task failures. Decisions only Prerit can make (unknown pay, unclear eligibility) become one-click
items in Needs Prerit, and the opportunity waits for his answer."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from hq.adapters.base import Deferred, RunContext, RunResult
from hq.llm import policy
from hq.llm.prompts import load_prompt, load_schema
from hq.llm.router import EscalationExhausted
from hq.pipeline.agents.common import (
    confirmed,
    decision_choice,
    decision_effect,
    label,
    load_opp,
    loads,
    open_decision,
    posting_text,
    sim_or_none,
)
from hq.pipeline.discover.parse import parse_date
from hq.pipeline.verify import fx as fx_mod
from hq.pipeline.verify import living_cost as lc_mod
from hq.pipeline.verify import pay as pay_mod
from hq.pipeline.verify.availability import check_availability
from hq.pipeline.verify.eligibility_rules import Candidate, check as rules_check
from hq.pipeline.verify.link import check_link, deadline_state
from hq.pipeline.verify.scam import check_scam
from hq.pipeline.verify.score import fit_score
from hq.util.timeutil import IST, now_iso, today_ist

VERDICTS = ("eligible", "eligible_gaps", "ineligible", "needs_info")


async def run(task: dict[str, Any], ctx: RunContext) -> RunResult:
    sim = await sim_or_none(task, ctx)
    if sim is not None:
        return sim
    opp = load_opp(ctx)
    if opp is None:
        return RunResult(output={"ok": False, "noop": True}, summary="opportunity gone")
    cap = task["capability"]
    handler = {"verify.link": link, "verify.deadline": deadline, "verify.eligibility": eligibility,
               "verify.eligibility_hard": eligibility, "verify.scam": scam, "verify.pay": pay,
               "score.fit": score}.get(cap)
    if handler is None:
        return RunResult(output={"ok": True, "noop": True}, summary=f"{cap}: nothing to do")
    return await handler(task, ctx, opp)


def _update(opp: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    return {"op": "opp.update", "id": opp["id"], "values": values}


# ── link + deadline ───────────────────────────────────────────────────────────────────────────────────
async def link(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any]) -> RunResult:
    ctx.progress(0.3, f"Checking {label(opp)} is still open…")
    res = await check_link(ctx.services.fetcher, canonical_key=opp["canonical_key"], url=opp.get("url"))
    values = {"link_status": res.status, "last_verified_at": now_iso()}
    if res.status == "dead":
        values["stage_reason"] = f"Posting closed: {res.reason}"
        return RunResult(output={"ok": False, "stage_reason": values["stage_reason"]},
                         effects=[_update(opp, values)], summary=f"{label(opp)}: closed ({res.reason})")
    return RunResult(output={"ok": True, "deadline_step": True}, effects=[_update(opp, values)],
                     summary=f"Link {res.status} for {label(opp)} ({res.reason})")


async def deadline(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any]) -> RunResult:
    state, reason = deadline_state(opp.get("deadline_at"))
    values: dict[str, Any] = {}
    if state == "rolling" and not opp.get("deadline_confidence"):
        values["deadline_confidence"] = "rolling"
    if state == "expired":
        values["stage_reason"] = f"Expired: {reason}"
        return RunResult(output={"ok": False, "stage_reason": values["stage_reason"]}, effects=[_update(opp, values)],
                         summary=f"{label(opp)}: {reason}")
    return RunResult(output={"ok": True}, effects=[_update(opp, values)] if values else [],
                     summary=f"Deadline for {label(opp)}: {reason}")


# ── eligibility ───────────────────────────────────────────────────────────────────────────────────────
def candidate(ctx: RunContext) -> Candidate:
    f = confirmed(ctx)
    c = Candidate()
    if f.get("grad_year"):
        c.grad_year, c.grad_year_confirmed = int(float(f["grad_year"])), True
    if f.get("semester"):
        c.semester = int(float(f["semester"]))
    if f.get("cgpa"):
        c.cgpa = float(f["cgpa"])
    return c


def start_date(opp: dict[str, Any]) -> date | None:
    parse = loads(opp.get("parse_json"), {})
    raw = parse.get("start_raw")
    if raw:
        iso = parse_date(raw)
        if iso:
            return date.fromisoformat(iso[:10])
    return None


def model_accuracy(ctx: RunContext, model_id: str) -> float:
    if model_id.startswith("xai:"):
        return 0.9
    rows = ctx.query("SELECT accuracy FROM benchmarks WHERE model_id=? AND task='eligibility' ORDER BY created_at DESC "
                     "LIMIT 1", (model_id,))
    return float(rows[0]["accuracy"]) if rows and rows[0]["accuracy"] is not None else 0.75


def grounding(out: dict[str, Any], text: str) -> tuple[float, list[dict[str, Any]]]:
    norm = " ".join(text.split()).lower()
    reqs = [r for r in out.get("requirements") or [] if isinstance(r, dict)]
    kept = [r for r in reqs if isinstance(r.get("quote"), str) and " ".join(r["quote"].split()).lower() in norm]
    if not reqs:
        return (0.6 if out.get("verdict") in ("ineligible", "needs_info") else 1.0), kept
    return len(kept) / len(reqs), kept


async def _llm_eligibility(ctx: RunContext, text: str, rules_needs_info: bool) -> dict[str, Any] | None:
    """Up to three opinions (role model → a different local model → Grok) until one is confident enough.
    hq.llm.policy decides the Grok step: in API-saving mode Grok answers only when no local model could; an unclear
    local answer becomes a one-click decision for Prerit instead of a paid call."""
    threshold = float(ctx.settings.get("eligibility_threshold", 0.8))
    msgs = [{"role": "system", "content": load_prompt("eligibility")},
            {"role": "user", "content": f"POSTING:\n{text[:12000]}"}]
    tried: set[str] = set()
    best: dict[str, Any] | None = None
    attempt = 0
    while attempt < 3:
        local_phase = attempt < 2 and policy.local_on(ctx.settings)
        use = None if local_phase else ("second_look" if best is not None else "needed")
        try:
            res = await ctx.llm("eligibility", msgs, load_schema("eligibility"), exclude_models=set(tried),
                                cloud_use=use, confidence_threshold=0.0, max_tokens=700,
                                task_type="verify.eligibility_hard", now_line="Checking eligibility with quotes…")
        except EscalationExhausted:
            if local_phase:
                attempt = 2   # no (further) local model: the Grok step decides whether to ask Grok
                continue
            break
        attempt = attempt + 1 if local_phase else 3
        tried.add(res.model_id)
        out = res.output if isinstance(res.output, dict) else {}
        verdict = out.get("verdict")
        if verdict not in VERDICTS:
            continue
        ground, kept = grounding(out, text)
        agree = 1.0 if (verdict == "needs_info") == rules_needs_info or verdict in ("eligible", "eligible_gaps") and \
            not rules_needs_info else 0.4
        conf = round(model_accuracy(ctx, res.model_id) * agree * ground, 3)
        cand = {"verdict": verdict, "confidence": conf, "model_id": res.model_id, "quotes": kept,
                "skill_gaps": [g for g in out.get("skill_gaps") or [] if isinstance(g, str)][:10]}
        if best is None or conf > best["confidence"]:
            best = cand
        if conf >= threshold:
            break
    return best


async def eligibility(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any]) -> RunResult:
    text = posting_text(opp) or f"{opp['title']} at {opp['company_name']}"
    ctx.progress(0.2, f"Applying eligibility rules to {label(opp)}…")
    rules = rules_check(text, candidate=candidate(ctx), start=start_date(opp),
                        remote=opp.get("work_mode") == "remote", country_iso2=opp.get("country_iso2"))
    effects: list[dict[str, Any]] = []
    avail = check_availability(windows_json=confirmed(ctx).get("availability_windows"),
                               hours_cap=confirmed(ctx).get("hours_cap_term"), start=start_date(opp),
                               duration_months=opp.get("duration_months"), hours_per_week=opp.get("hours_per_week"),
                               work_mode=opp.get("work_mode"))
    if rules.ineligible:
        h = rules.hits[0]
        effects.append({"op": "eligibility_check", "values": {
            "opportunity_id": opp["id"], "method": "rules", "requirements_json": json.dumps(rules.as_dict()),
            "quotes_json": json.dumps([x.quote for x in rules.hits]), "verdict": "ineligible", "confidence": 0.95,
            "run_id": ctx.run_id}})
        effects.append(_update(opp, {"eligibility_status": "ineligible", "eligibility_confidence": 0.95,
                                     "availability_status": avail.status,
                                     "stage_reason": f"Ineligible: {h.detail}"}))
        return RunResult(output={"ok": False, "stage_reason": f"Ineligible: {h.detail}"}, effects=effects,
                         summary=f"{label(opp)}: ineligible — “{h.quote[:120]}”")
    best = await _llm_eligibility(ctx, text, bool(rules.needs_info))
    if best is None:
        raise Deferred("queued", _in_minutes(30), "no eligibility model available yet (local models / Grok)")
    threshold = float(ctx.settings.get("eligibility_threshold", 0.8))
    verdict, conf = best["verdict"], best["confidence"]
    if rules.needs_info and verdict in ("eligible", "eligible_gaps"):
        verdict = "needs_info"
    if verdict in ("eligible", "eligible_gaps") and conf < threshold:
        verdict = "needs_info"
    effects.append({"op": "eligibility_check", "values": {
        "opportunity_id": opp["id"], "method": "rules+llm", "model_id": best["model_id"],
        "requirements_json": json.dumps({"rules": rules.as_dict(), "skill_gaps": best["skill_gaps"]}),
        "quotes_json": json.dumps(best["quotes"]), "verdict": verdict, "confidence": conf, "run_id": ctx.run_id}})
    values = {"eligibility_status": verdict, "eligibility_confidence": conf, "availability_status": avail.status}
    if verdict == "ineligible":
        q = best["quotes"][0]["quote"] if best["quotes"] else "see eligibility check"
        values["stage_reason"] = f"Ineligible: “{q[:160]}”"
        effects.append(_update(opp, values))
        return RunResult(output={"ok": False, "stage_reason": values["stage_reason"]}, effects=effects,
                         summary=f"{label(opp)}: ineligible ({best['model_id']}, confidence {conf:.2f})",
                         model_id=best["model_id"])
    if avail.status == "conflict":
        values["stage_reason"] = f"Dates don't fit: {avail.reason}"
        effects.append(_update(opp, values))
        return RunResult(output={"ok": False, "stage_reason": values["stage_reason"]}, effects=effects,
                         summary=f"{label(opp)}: {avail.reason}")
    effects.append(_update(opp, values))
    if verdict == "needs_info" and not open_decision(ctx, opp["id"], "eligibility"):
        quotes = "\n".join(f"> {q['quote']}" for q in best["quotes"][:4]) or "> (no clear requirement quoted)"
        why = "; ".join(h.detail for h in rules.needs_info) or f"model confidence {conf:.2f} < {threshold:.2f}"
        effects.append(decision_effect(opp, "eligibility", f"Eligible for {label(opp)}?",
                                       f"HQ couldn't decide eligibility on its own ({why}).\n\n{quotes}\n\n"
                                       f"[Open the posting]({opp.get('url') or ''})", keep_label="I'm eligible",
                                       drop_label="Not eligible"))
    return RunResult(output={"ok": True, "verdict": verdict}, effects=effects,
                     summary=f"{label(opp)}: {verdict.replace('_', ' ')} (confidence {conf:.2f})",
                     model_id=best["model_id"])


def _in_minutes(n: int) -> str:
    from hq.util.timeutil import iso_in

    return iso_in(n * 60)


# ── scam ──────────────────────────────────────────────────────────────────────────────────────────────
async def scam(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any]) -> RunResult:
    res = check_scam(company=opp["company_name"], text=posting_text(opp), url=opp.get("url"),
                     apply_email=opp.get("apply_email"))
    effects = [{"op": "scam_check", "values": {"opportunity_id": opp["id"], "signals_json": json.dumps(res.signals),
                                               "verdict": res.verdict, "run_id": ctx.run_id}}]
    values: dict[str, Any] = {"scam_status": res.verdict}
    if res.fee:
        values["pay_status"] = "fee_required"
    if res.verdict == "scam":
        values["stage_reason"] = "Scam signals: " + ", ".join(f"{s['kind']} “{s['evidence']}”" for s in res.signals[:2])
        effects.append(_update(opp, values))
        return RunResult(output={"ok": False, "stage_reason": values["stage_reason"]}, effects=effects,
                         summary=f"{label(opp)}: {values['stage_reason']}")
    effects.append(_update(opp, values))
    return RunResult(output={"ok": True}, effects=effects,
                     summary=f"{label(opp)}: {'no scam signals' if res.verdict == 'clean' else 'suspicious — ' + res.signals[0]['kind']}")


# ── pay ───────────────────────────────────────────────────────────────────────────────────────────────
async def pay(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any]) -> RunResult:
    benefits = loads(opp.get("benefits_json"), {})
    parsed = pay_mod.parse_pay(opp.get("pay_raw"), hours_per_week=opp.get("hours_per_week"),
                               duration_months=opp.get("duration_months"))
    if opp.get("pay_status") == "fee_required":
        parsed = pay_mod.ParsedPay(raw=opp.get("pay_raw"), status="fee_required")
    values = pay_mod.normalize(parsed, fx_mod.default(), lc_mod.default(), city=opp.get("city"),
                               country_iso2=opp.get("country_iso2"), work_mode=opp.get("work_mode"), benefits=benefits)
    effects: list[dict[str, Any]] = []
    s = ctx.settings
    status, ratio = values["pay_status"], values.get("pay_ratio")
    funded = bool(benefits.get("housing") and benefits.get("meals") and benefits.get("travel"))
    allowance = values.get("pay_monthly_inr_min") or benefits.get("allowance_inr") or 0
    if status in ("unpaid", "fee_required"):
        values["stage_reason"] = "Unpaid" if status == "unpaid" else "Charges a fee"
        effects.append(_update(opp, values))
        return RunResult(output={"ok": False, "stage_reason": values["stage_reason"]}, effects=effects,
                         summary=f"{label(opp)}: {values['stage_reason'].lower()}")
    if values.get("living_cost_monthly_inr") is None and opp.get("city") and not open_decision(ctx, opp["id"], "living_cost"):
        effects.append(decision_effect(opp, "living_cost", f"Living cost for {opp['city']}?",
                                       f"HQ has no living-cost figure for **{opp['city']}** yet, so it can't compare "
                                       f"{label(opp)}'s pay with it. Add a row to `config/living_costs.csv` (or Settings) "
                                       "and mark this done; *drop* skips the role.", keep_label="Added — continue"))
    if status == "listed" and ratio is not None and ratio < float(s.get("min_pay_ratio", 1.0)) and \
            not (funded and allowance >= float(s.get("funded_program_min_inr", 5000))):
        values["stage_reason"] = f"Pay ₹{values['pay_monthly_inr_min']:,.0f}/mo is {ratio:.2f}× living cost " \
                                 f"(needs {float(s.get('min_pay_ratio', 1.0)):.1f}×)"
        effects.append(_update(opp, values))
        return RunResult(output={"ok": False, "stage_reason": values["stage_reason"]}, effects=effects,
                         summary=f"{label(opp)}: {values['stage_reason']}")
    if status in ("unknown", "variable") and s.get("unknown_pay_policy") == "reject" and status == "unknown":
        values["stage_reason"] = "Pay not stated (policy: drop)"
        effects.append(_update(opp, values))
        return RunResult(output={"ok": False, "stage_reason": values["stage_reason"]}, effects=effects,
                         summary=f"{label(opp)}: pay not stated — dropped by policy")
    effects.append(_update(opp, values))
    shown = f"₹{values['pay_monthly_inr_min']:,.0f}/mo" if values.get("pay_monthly_inr_min") else status
    return RunResult(output={"ok": True, "pay_status": status}, effects=effects,
                     summary=f"{label(opp)}: pay {shown}" + (f" ({ratio:.2f}× living cost)" if ratio else ""))


# ── score ─────────────────────────────────────────────────────────────────────────────────────────────
def _drafts_today(ctx: RunContext) -> int:
    from datetime import time as dtime

    start = datetime.combine(today_ist(), dtime.min, tzinfo=IST).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ctx.query("SELECT COUNT(*) AS n FROM documents d JOIN opportunities o ON o.id=d.opportunity_id WHERE "
                     "o.is_simulated=0 AND d.version=1 AND d.kind IN ('cover_letter','cold_email') AND d.created_at>=?",
                     (start,))[0]["n"]


async def score(task: dict[str, Any], ctx: RunContext, opp: dict[str, Any]) -> RunResult:
    s = ctx.settings
    effects: list[dict[str, Any]] = []
    # decisions Prerit must make first
    holds = []
    if opp["eligibility_status"] == "needs_info":
        choice = decision_choice(ctx, opp["id"], "eligibility")
        if choice == "drop":
            return _filtered(opp, "Prerit: not eligible")
        if choice != "keep":
            holds.append("eligibility")
    if opp["pay_status"] in ("unknown", "variable") and s.get("unknown_pay_policy", "decision") == "decision":
        choice = decision_choice(ctx, opp["id"], "unknown_pay")
        if choice == "drop":
            return _filtered(opp, "Prerit: skip (pay unknown)")
        if choice != "keep":
            holds.append("unknown_pay")
            if not open_decision(ctx, opp["id"], "unknown_pay"):
                effects.append(decision_effect(
                    opp, "unknown_pay", f"Pay not stated: {label(opp)}",
                    f"**{label(opp)}** doesn't say what it pays"
                    + (f" (“{opp['pay_raw']}”)" if opp.get("pay_raw") else "") + ". Keep going and draft an "
                    "application anyway, or drop it?\n\n" + (f"[Open the posting]({opp['url']})" if opp.get("url") else ""),
                    keep_label="Keep — apply anyway"))
    if open_decision(ctx, opp["id"], "living_cost") and decision_choice(ctx, opp["id"], "living_cost") is None:
        holds.append("living_cost")
    elif decision_choice(ctx, opp["id"], "living_cost") == "drop":
        return _filtered(opp, "Prerit: skip (living cost unknown)")
    text = posting_text(opp)
    state, _ = deadline_state(opp.get("deadline_at"))
    opp_view = {**opp, "benefits": loads(opp.get("benefits_json"), {})}
    threshold = int(s.get("fit_draft_threshold", 60))
    mill = ctx.query("SELECT known_mill FROM companies WHERE id=?", (opp.get("company_id"),)) if opp.get("company_id") else []
    opp_view["known_mill"] = bool(mill and mill[0]["known_mill"])
    fit, breakdown = fit_score(opp_view, text=text, eligibility_confidence=opp.get("eligibility_confidence"),
                               eligibility_status=opp["eligibility_status"], deadline=state, draft_threshold=threshold)
    values: dict[str, Any] = {"fit_score": fit, "fit_breakdown_json": json.dumps(breakdown)}
    advance = False
    delay = 0.0
    forced = bool((task.get("payload") or {}).get("force"))   # Prerit clicked "Apply anyway" on a parked match
    if holds:
        values["stage_reason"] = "Waiting for your decision (" + ", ".join(h.replace("_", " ") for h in holds) + ")"
    elif fit < threshold and not forced:
        values["stage_reason"] = (f"Match {fit}/100 — {breakdown['verdict']}: parked (below {threshold}). "
                                  + ("; ".join(breakdown["concerns"][:2]) or ""))[:300]
    else:
        advance = True
        if _drafts_today(ctx) >= int(s.get("daily_draft_cap", 20)):
            from hq.worker.budget import next_midnight_ist

            delay = max(0.0, (next_midnight_ist() - datetime.now(timezone.utc)).total_seconds())
            values["stage_reason"] = "Draft cap reached — drafting after midnight IST"
        else:
            values["stage_reason"] = f"Match {fit}/100 ({breakdown['track_label']}) — drafting"
    effects.append(_update(opp, values))
    return RunResult(output={"ok": True, "advance": advance, "draft_delay_s": delay, "fit": fit}, effects=effects,
                     summary=f"{label(opp)}: match {fit}/100" + ("" if advance else f" — {values['stage_reason']}"))


def _filtered(opp: dict[str, Any], reason: str) -> RunResult:
    return RunResult(output={"ok": False, "stage_reason": reason},
                     effects=[{"op": "opp.update", "id": opp["id"], "values": {"stage_reason": reason}}],
                     summary=f"{label(opp)}: {reason}")
