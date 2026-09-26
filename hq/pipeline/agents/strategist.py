"""Strategist (strategy.daily_review) — CONTRACT_E §1.

Every morning at 07:30 IST (and on "Run review now") it reads the last 24 h / 7 days of the pipeline and writes the
daily report card. The numbers and every action are decided by code here; a model only words the review:
cloud model when one is available and the budget allows → the local summarizer → a built-in summary. A report is
therefore written every day, even with no model at all.

Auto-applied (low risk, whitelisted, capped):
- disable_source: an enabled source with ≥ 5 consecutive errors while other sources work (so a dead Wi-Fi never
  switches everything off), or with no new postings for 14 days after polling fine.
- add_ats_slug: a model-proposed Greenhouse/Lever/Ashby board, only after one GET shows it exists.
Everything else (keywords, thresholds, notes) is a proposal shown to Prerit.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

from hq import insights
from hq.adapters.base import Cancelled, Deferred, RunContext, RunResult
from hq.llm.prompts import load_prompt, load_schema
from hq.pipeline.agents.common import has_role_model
from hq.pipeline.discover import sources as src_mod
from hq.util.timeutil import today_ist, utcnow

ERROR_LIMIT = 5
IDLE_DAYS = 14
MAX_DISABLE = 5
MAX_ADD = 3
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
ACTION_TYPES = ("add_ats_slug", "disable_source", "tune_keywords", "change_threshold", "note")


def _since(days: float) -> str:
    return (utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


# ── the numbers ──────────────────────────────────────────────────────────────────────────────────────
def window(ctx: RunContext, days: float) -> dict[str, Any]:
    since = _since(days)
    new = ctx.query("SELECT stage, is_simulated FROM opportunities WHERE first_seen_at >= ? "
                    "AND stage NOT IN ('frozen','skipped')", (since,))
    applied = ctx.query("SELECT a.mode, o.is_simulated FROM applications a JOIN opportunities o ON "
                        "o.id=a.opportunity_id WHERE a.submitted_at >= ?", (since,))
    replies = ctx.query("SELECT classification FROM email_threads WHERE last_message_at >= ? AND "
                        "classification IS NOT NULL AND classification NOT IN ('job_alert','other','auto_ack')",
                        (since,))
    return {"found": len(new), "found_real": sum(not r["is_simulated"] for r in new),
            "filtered": sum(r["stage"] == "filtered" for r in new),
            "verified": sum(insights.REACHED.get(r["stage"], -1) >= 1 for r in new),
            "applied": len(applied), "applied_live": sum(r["mode"] == "live" for r in applied),
            "replies": len(replies),
            "interviews": sum(r["classification"] == "interview_invite" for r in replies),
            "offers": sum(r["classification"] == "offer" for r in replies)}


def failing_sources(ctx: RunContext) -> list[dict[str, Any]]:
    """Sources the Strategist may switch off. Error-based only while some other source polled fine in 24 h."""
    rows = ctx.query("SELECT id, name, kind, consecutive_errors, last_ok_at, last_polled_at, created_at "
                     "FROM sources WHERE enabled=1")
    others_ok = any((r["last_ok_at"] or "") >= _since(1) for r in rows)
    recent = {r["source_id"] for r in ctx.query("SELECT DISTINCT source_id FROM opportunity_sources "
                                                "WHERE first_seen >= ?", (_since(IDLE_DAYS),))}
    out = []
    for r in rows:
        if r["consecutive_errors"] >= ERROR_LIMIT and others_ok:
            out.append({**r, "why": f"{r['consecutive_errors']} errors in a row while other sources work"})
        elif (r["created_at"] or "") < _since(IDLE_DAYS) and (r["last_ok_at"] or "") >= _since(1) \
                and r["id"] not in recent:
            out.append({**r, "why": f"no new postings in {IDLE_DAYS} days"})
    return out


def agent_errors(ctx: RunContext) -> list[dict[str, Any]]:
    rows = ctx.query("SELECT COALESCE(json_extract(a.config_json, '$.name'), r.agent_id) AS agent_id, r.error "
                     "FROM agent_runs r LEFT JOIN agents a ON a.id=r.agent_id WHERE r.status='failed' AND "
                     "r.started_at >= ?", (_since(1),))
    groups: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (r["agent_id"], (r["error"] or "error").split(":", 1)[0][:80])
        groups[key] = groups.get(key, 0) + 1
    return [{"agent": a, "error": e, "n": n} for (a, e), n in sorted(groups.items(), key=lambda kv: -kv[1])][:8]


def gather(ctx: RunContext) -> dict[str, Any]:
    a = insights.analytics(ctx.conn, scope="all", days=7)
    real = insights.analytics(ctx.conn, scope="real", days=7)
    today = today_ist().isoformat()
    spend = next((d for d in a["cloud_spend"]["days"] if d["date"] == today), {"usd": 0.0, "calls": 0})
    top = ctx.query("SELECT company_name, title, country_iso2, pay_monthly_inr_mid, pay_ratio, is_simulated "
                    "FROM opportunities WHERE stage NOT IN ('filtered','rejected','frozen','skipped') AND "
                    "pay_monthly_inr_mid IS NOT NULL ORDER BY pay_monthly_inr_mid DESC LIMIT 5")
    needs = ctx.query("SELECT COUNT(*) AS n FROM needs_prerit WHERE status='open'")[0]["n"]
    return {
        "date": today, "last_24h": window(ctx, 1), "last_7d": window(ctx, 7),
        "totals": a["totals"], "real_totals": real["totals"],
        "sources": [s for s in a["sources"] if s["found"]][:12],
        "filter_reasons": a["gate_failures"]["filtered"][:6], "draft_gate_failures": a["gate_failures"]["drafts"][:6],
        "reply_rates": {k: v[:5] for k, v in a["reply_rates"].items()},
        "failing_sources": [{"source_id": s["id"], "name": s["name"], "why": s["why"]} for s in failing_sources(ctx)],
        "agent_errors_24h": agent_errors(ctx),
        "cloud_today": {"usd": spend["usd"], "calls": spend["calls"], "cap_usd": a["cloud_spend"]["cap_usd"],
                        "call_cap": a["cloud_spend"]["call_cap"]},
        "open_needs": needs,
        "top_paying": [{"company": t["company_name"], "title": t["title"], "country": t["country_iso2"],
                        "inr_month": round(t["pay_monthly_inr_mid"]), "ratio": t["pay_ratio"],
                        "simulated": bool(t["is_simulated"])} for t in top],
        "existing_ats_boards": sorted(r["id"] for r in ctx.query(
            "SELECT id FROM sources WHERE kind IN ('greenhouse','lever','ashby')")),
    }


# ── the built-in wording (no model needed) ───────────────────────────────────────────────────────────
def _inr(v: float | None) -> str:
    if v is None:
        return "—"
    return f"₹{v / 100_000:.1f}L" if v >= 100_000 else f"₹{v / 1000:.0f}K"


def builtin_report(d: dict[str, Any], applied: list[dict[str, Any]], proposals: list[dict[str, Any]]) -> str:
    h, w, t = d["last_24h"], d["last_7d"], d["totals"]
    lines = [f"**Last 24 h:** {h['found']} found ({h['found_real']} real) · {h['filtered']} filtered · "
             f"{h['applied']} applied · {h['replies']} replies.",
             f"**Last 7 days:** {w['found']} found · {w['verified']} verified · {w['applied']} applied · "
             f"{w['replies']} replies · {w['interviews']} interviews · {w['offers']} offers.", ""]
    if t["simulated"] and t["simulated"] == t["opportunities"]:
        lines += ["Everything in the pipeline is simulated (SIM). Turn the simulator off in Settings › Simulation to "
                  "see only real roles.", ""]
    good = [s for s in d["sources"] if s["verified"]]
    lines.append("## What worked")
    if good:
        for s in good[:3]:
            lines.append(f"- {s['name']}: {s['verified']} verified, {s['applied']} applied (n={s['found']})")
    else:
        lines.append("- Nothing verified yet — too early to tell.")
    lines += ["", "## What didn't"]
    bad = False
    for r in d["filter_reasons"][:3]:
        lines.append(f"- Filtered as {r['reason']}: {r['n']}")
        bad = True
    for s in d["failing_sources"][:3]:
        lines.append(f"- {s['name']}: {s['why']}")
        bad = True
    for e in d["agent_errors_24h"][:2]:
        lines.append(f"- {e['agent']} failed {e['n']}× ({e['error']})")
        bad = True
    if not bad:
        lines.append("- No filters, failing sources or agent errors worth a note.")
    if d["top_paying"]:
        lines += ["", "## Best-paying live roles"]
        for o in d["top_paying"][:3]:
            sim = " (SIM)" if o["simulated"] else ""
            lines.append(f"- {o['company']} — {o['title']}{sim}: {_inr(o['inr_month'])}/mo")
    c = d["cloud_today"]
    lines += ["", f"Cloud today: ${c['usd']:.2f} of ${c['cap_usd']:.2f} ({c['calls']}/{c['call_cap']} calls) · "
                  f"{d['open_needs']} item(s) waiting in Needs Prerit."]
    if applied:
        lines += ["", "## Done automatically"] + [f"- {a['rationale']}" for a in applied]
    if proposals:
        lines += ["", "## Proposals (need your OK)"] + [f"- {p.get('rationale') or p['type']}" for p in proposals]
    return "\n".join(lines)


# ── model wording ────────────────────────────────────────────────────────────────────────────────────
def _valid(out: Any) -> dict[str, Any] | None:
    if not isinstance(out, dict) or not isinstance(out.get("report_md"), str) or len(out["report_md"].strip()) < 20:
        return None
    acts = [a for a in (out.get("actions") or []) if isinstance(a, dict) and a.get("type") in ACTION_TYPES]
    return {"report_md": out["report_md"].strip()[:6000], "actions": acts[:10]}


async def model_review(ctx: RunContext, data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, float]:
    """(review, model id, cost). Cloud first, then the local summarizer; (None, None, 0) when neither can."""
    prompt = "PIPELINE DATA (JSON):\n" + json.dumps(data, ensure_ascii=False, default=str)
    system = load_prompt("strategist")
    schema = load_schema("strategy")
    if ctx.services.claude is not None:
        try:
            res = await ctx.claude("strategy.daily_review", prompt, schema, system_prompt=system)
            review = _valid(res.output)
            if review:
                return review, ctx.model_id, res.cost_usd or 0.0
        except (Cancelled, KeyboardInterrupt):
            raise
        except Deferred as exc:
            ctx.emit("log", f"Strategist: cloud model skipped ({exc.reason}); using the local summary", level="debug")
        except Exception as exc:  # noqa: BLE001 — a failed wording never costs the day's report
            ctx.emit("log", f"Strategist: cloud review failed ({str(exc)[:160]}); using the local summary",
                     level="warn")
    if ctx.services.router is not None and has_role_model(ctx, "summarizer"):
        try:
            res = await ctx.llm("summarizer", [{"role": "system", "content": system},
                                               {"role": "user", "content": prompt}], schema, allow_claude=False,
                                max_tokens=1200, now_line="Writing the daily review…")
            review = _valid(res.output)
            if review:
                return review, res.model_id, 0.0
        except (Cancelled, KeyboardInterrupt):
            raise
        except Exception as exc:  # noqa: BLE001
            ctx.emit("log", f"Strategist: local summarizer failed ({str(exc)[:160]})", level="debug")
    return None, None, 0.0


# ── actions ──────────────────────────────────────────────────────────────────────────────────────────
async def _board_exists(ctx: RunContext, provider: str, slug: str) -> tuple[bool, str]:
    from hq.pipeline.discover.ats import read_board
    from hq.pipeline.discover.fetch import FetchBlocked

    fetcher = ctx.services.fetcher
    if fetcher is None:
        return False, "no fetcher in this worker"
    try:
        postings = await read_board(fetcher, {"id": f"{provider}:{slug}", "kind": provider, "config": {"slug": slug}})
    except (FetchBlocked, LookupError) as exc:
        return False, str(exc)[:160]
    except Exception as exc:  # noqa: BLE001 — parse errors, timeouts: not a board we can use
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"
    return True, f"{len(postings)} open posting(s)"


async def decide(ctx: RunContext, data: dict[str, Any], suggested: list[dict[str, Any]]) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """(effects, applied, proposals). Code decides; suggestions from a model are only candidates."""
    effects: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    failing = {s["source_id"]: s for s in data["failing_sources"]}
    for s in list(failing.values())[:MAX_DISABLE]:
        effects.append({"op": "source.disable", "id": s["source_id"], "name": s["name"], "reason": s["why"]})
        applied.append({"type": "disable_source", "params": {"source_id": s["source_id"]}, "risk": "low",
                        "rationale": f"Turned off {s['name']}: {s['why']}.", "status": "applied"})
    existing = set(data["existing_ats_boards"])
    added = 0
    ats_cfg = src_mod.config().get("ats") or {}
    for a in suggested:
        typ, params = a["type"], a.get("params") if isinstance(a.get("params"), dict) else {}
        rationale = (a.get("rationale") or "").strip()[:300] or None
        if typ == "disable_source":
            if params.get("source_id") not in failing:  # the model can't switch off a healthy source
                proposals.append({"type": typ, "params": params, "risk": a.get("risk") or "medium",
                                  "rationale": rationale, "status": "proposed"})
            continue
        if typ == "add_ats_slug":
            provider = str(params.get("provider") or "").lower()
            slug = str(params.get("slug") or "").strip().lower()
            sid = f"{provider}:{slug}"
            if provider not in src_mod.ATS_KINDS or not SLUG_RE.match(slug) or sid in existing:
                continue
            if added >= MAX_ADD:
                proposals.append({"type": typ, "params": params, "risk": "low", "rationale": rationale,
                                  "status": "proposed"})
                continue
            ok, why = await _board_exists(ctx, provider, slug)
            if not ok:
                proposals.append({"type": typ, "params": params, "risk": "low", "status": "not_verified",
                                  "rationale": f"{rationale or 'Suggested board'} (not added: {why})"})
                continue
            company = str(params.get("company") or slug)[:80]
            spec = ats_cfg.get(provider) or {}
            effects.append({"op": "source.add", "reason": rationale or "suggested by the Strategist", "values": {
                "id": sid, "name": f"{src_mod.ATS_LABEL.get(provider, provider)} · {slug}", "kind": provider,
                "config": {"slug": slug, "tos_note": spec.get("tos_note"), "company": company},
                "tos_url": spec.get("tos_url")}})
            applied.append({"type": typ, "params": {"provider": provider, "slug": slug, "company": company},
                            "risk": "low", "status": "applied",
                            "rationale": f"Added the {company} board on {src_mod.ATS_LABEL.get(provider, provider)} "
                                         f"({why})."})
            existing.add(sid)
            added += 1
            continue
        proposals.append({"type": typ, "params": params, "risk": a.get("risk") or "medium", "rationale": rationale,
                          "status": "proposed"})
    return effects, applied, proposals[:8]


# ── entry point ──────────────────────────────────────────────────────────────────────────────────────
async def run(task: dict[str, Any], ctx: RunContext) -> RunResult:
    ctx.progress(0.1, "Reading the last 24 hours and 7 days…")
    data = gather(ctx)
    ctx.check_cancel()
    ctx.progress(0.35, "Writing the daily review…")
    review, model_id, cost = await model_review(ctx, data)
    ctx.progress(0.75, "Checking proposed actions…")
    effects, applied, proposals = await decide(ctx, data, review["actions"] if review else [])
    if review:
        report = review["report_md"]
        if applied:
            report += "\n\n## Done automatically\n" + "\n".join(f"- {a['rationale']}" for a in applied)
    else:
        report = builtin_report(data, applied, proposals)
    effects.append({"op": "strategy_report", "values": {
        "date": data["date"], "report_md": report, "proposed_actions_json": proposals,
        "applied_actions_json": applied}})
    effects.append({"op": "notification", "values": {
        "severity": "info", "title": "Strategist: daily review ready",
        "body": (f"{len(applied)} change(s) made, " if applied else "") + f"{len(proposals)} proposal(s)",
        "url": "/analytics"}})
    by = "the built-in summary" if not model_id else model_id
    return RunResult(output={"ok": True, "applied": len(applied), "proposals": len(proposals), "model": model_id},
                     effects=effects, model_id=model_id, cost_usd=cost or None,
                     summary=f"Daily review written ({by}): {len(applied)} applied, {len(proposals)} proposed")
