"""Scout (discover.ats, discover.program_page, parse.job, classify.title).

Discovery polls the sources that are due (enabled, ToS allowed, interval passed, breaker closed), keeps the target
titles, merges duplicates into `opportunity_sources` and creates the rest as real opportunities. When the
simulator is on, the scheduled run also lets it invent its tagged SIM roles. parse.job turns the posting text into
a JobParse (rules first, the parser model when one is assigned); non-substring quotes never survive.
"""
from __future__ import annotations

import json
from typing import Any

from hq.adapters.base import Deferred, RunContext, RunResult, TransientError
from hq.db.conn import tx
from hq.llm.prompts import load_prompt, load_schema
from hq.pipeline.agents.common import has_role_model, label, load_opp, posting_text, sim_or_none
from hq.pipeline.discover import sources as src_mod
from hq.pipeline.discover.ats import read_board
from hq.pipeline.discover.dedupe import find_duplicate
from hq.pipeline.discover.fetch import FetchBlocked
from hq.pipeline.discover.parse import job_quotes, merge_llm, rules_parse
from hq.pipeline.discover.postings import RawPosting, description_path, opportunity_values
from hq.pipeline.discover.program_pages import parse_program_page
from hq.pipeline.discover.text import html_to_text
from hq.pipeline.discover.titles import classify_title
from hq.util import netguard

MAX_NEW_PER_RUN = 25
SOURCES_PER_RUN = 4


async def run(task: dict[str, Any], ctx: RunContext) -> RunResult:
    cap = task["capability"]
    if cap.startswith("discover."):
        return await discover(task, ctx)
    sim = await sim_or_none(task, ctx)
    if sim is not None:
        return sim
    if cap == "parse.job":
        return await parse_job(task, ctx)
    return RunResult(output={"ok": True, "noop": True}, summary=f"{cap}: nothing to do")


# ── discovery ─────────────────────────────────────────────────────────────────────────────────────────
async def _llm_titles(ctx: RunContext, postings: list[RawPosting]) -> set[str]:
    """Ask the title_filter model about uncertain titles (best effort; failures keep them out)."""
    if not postings or not has_role_model(ctx, "title_filter"):
        return set()
    lines = "\n".join(f"{i}. {p.title} — {p.company} ({p.location_raw or ''})" for i, p in enumerate(postings[:25]))
    try:
        res = await ctx.llm("title_filter", [{"role": "system", "content": load_prompt("title_filter")},
                                             {"role": "user", "content": f"TITLES:\n{lines}"}],
                            load_schema("title_filter"), allow_claude=False, max_tokens=800,
                            now_line="Classifying uncertain titles…")
    except Exception:
        return set()
    keep = set()
    for r in (res.output or {}).get("results", []):
        if isinstance(r, dict) and r.get("target") and isinstance(r.get("i"), int) and r["i"] < len(postings):
            keep.add(postings[r["i"]].external_id)
    return keep


async def discover(task: dict[str, Any], ctx: RunContext) -> RunResult:
    cap = task["capability"]
    kinds = src_mod.ATS_KINDS if cap == "discover.ats" else ("program_page",)
    fetcher = ctx.services.fetcher
    effects: list[dict[str, Any]] = []
    opp_results: list[tuple[str, dict[str, Any]]] = []
    lines: list[str] = []
    due = src_mod.due_sources(ctx.conn, kinds, limit=SOURCES_PER_RUN) if fetcher is not None else []
    created = 0
    for i, source in enumerate(due):
        ctx.check_cancel()
        ctx.progress((i + 0.2) / max(1, len(due)), f"Reading {source['name']}…")
        try:
            if source["kind"] == "program_page":
                res = await fetcher.get(source["config"]["url"], kind="html", source_id=source["id"])
                if res.status != 200:
                    raise LookupError(f"HTTP {res.status}")
                postings = parse_program_page(res.text, source)
            else:
                postings = await read_board(fetcher, source)
        except (FetchBlocked, LookupError, TransientError, ValueError) as exc:
            with tx(ctx.conn):
                src_mod.record_poll(ctx.conn, source["id"], ok=False, error=str(exc)[:200])
            lines.append(f"{source['name']}: {exc}")
            continue
        decisions = {p.external_id: classify_title(p.title) for p in postings}
        uncertain = [p for p in postings if decisions[p.external_id].uncertain]
        rescued = await _llm_titles(ctx, uncertain)
        kept = [p for p in postings if decisions[p.external_id].target or p.external_id in rescued]
        if source["kind"] == "program_page":
            kept = postings  # programme pages are curated targets already
        new_here = 0
        for p in kept:
            dup = find_duplicate(ctx.conn, p)
            if dup:
                effects.append({"op": "opp.source", "values": {"opportunity_id": dup, "source_id": p.source_id,
                                                                "external_id": p.external_id, "source_url": p.url}})
                continue
            if created >= MAX_NEW_PER_RUN:
                break
            values = opportunity_values(p, source_label=f"{source['name']}")
            if p.extra.get("deadline_at"):
                values["deadline_at"], values["deadline_confidence"] = p.extra["deadline_at"], "medium"
            if p.extra.get("kind"):
                values["kind"] = p.extra["kind"]
            effects.append({"op": "opp.create", "values": values, "is_simulated": False})
            effects.append({"op": "opp.source", "values": {"opportunity_id": values["id"], "source_id": p.source_id,
                                                            "external_id": p.external_id, "source_url": p.url}})
            opp_results.append((values["id"], {"created": True}))
            created += 1
            new_here += 1
        with tx(ctx.conn):
            src_mod.record_poll(ctx.conn, source["id"], ok=True, found=new_here)
        lines.append(f"{source['name']}: {len(postings)} postings, {len(kept)} targets, {new_here} new")
    summary = "; ".join(lines) if lines else "No sources due"
    output: dict[str, Any] = {"ok": True, "created": created, "sources": len(due)}
    sim = None
    if ctx.settings.get("sim_enabled", True) and ctx.services.sim is not None:
        sim = await ctx.services.sim.run(task, ctx)
        effects += sim.effects
        opp_results += sim.opp_results
        output["sim_created"] = int(sim.output.get("created", 0) or 0)
        output["created"] = created + output["sim_created"]
        output.update({k: v for k, v in sim.output.items() if k not in output})
        summary = f"{summary} · sim: {sim.summary}" if lines else (sim.summary or summary)
    return RunResult(output=output, effects=effects, opp_results=opp_results, summary=summary[:400],
                     model_id=sim.model_id if sim else None, tok_s=sim.tok_s if sim else None)


# ── parse.job ─────────────────────────────────────────────────────────────────────────────────────────
async def parse_job(task: dict[str, Any], ctx: RunContext) -> RunResult:
    opp = load_opp(ctx)
    if opp is None:
        return RunResult(output={"ok": False, "noop": True}, summary="opportunity gone")
    text = posting_text(opp)
    updates: dict[str, Any] = {}
    if not text and opp.get("url") and not netguard.is_manual_lane(opp["url"]) and ctx.services.fetcher:
        ctx.progress(0.2, f"Fetching {label(opp)}…")
        try:
            res = await ctx.services.fetcher.get(opp["url"], kind="html")
            if res.status == 200:
                text = html_to_text(res.text)[:60000]
                path, digest = description_path(opp["id"], text)
                updates.update(description_path=path, desc_hash=digest)
        except FetchBlocked as exc:
            text = ""
            updates["link_status"] = "not_automatable"
            updates["stage_reason"] = str(exc)[:200]
    ctx.progress(0.4, f"Parsing {label(opp)}…")
    parsed = rules_parse(text, company=opp["company_name"], title=opp["title"], pay_hint=opp.get("pay_raw"))
    model_id = None
    if parsed.parse_ok and has_role_model(ctx, "parser"):
        try:
            res = await ctx.llm("parser", [{"role": "system", "content": load_prompt("parse_job")},
                                           {"role": "user", "content": f"POSTING:\n{text[:12000]}"}],
                                load_schema("job_parse"), allow_claude=False, max_tokens=900,
                                now_line=f"Extracting requirements from {opp['company_name']}…")
            parsed = merge_llm(parsed, res.output, text, res.model_id)
            model_id = res.model_id
        except Deferred:
            raise
        except Exception:
            pass  # the rules parse stands on its own
    if not parsed.parse_ok:
        return RunResult(output={"ok": False, "stage_reason": "Posting unreadable (empty, login wall or closed)"},
                         effects=[{"op": "opp.update", "id": opp["id"], "values": {
                             **updates, "stage_reason": "Posting unreadable (empty, login wall or closed)",
                             "parse_json": json.dumps(parsed.as_dict())}}],
                         summary=f"{label(opp)}: unreadable posting")
    benefits = json.loads(opp.get("benefits_json") or "{}")
    benefits.update({k: v for k, v in parsed.benefits.items() if v})
    updates.update({
        "parse_json": json.dumps(parsed.as_dict(), ensure_ascii=False),
        "requirements_json": json.dumps(parsed.requirements, ensure_ascii=False),
        "job_quotes_json": json.dumps(job_quotes(parsed), ensure_ascii=False),
        "benefits_json": json.dumps(benefits),
        "summary": (parsed.duties[0] if parsed.duties else (opp.get("summary") or ""))[:400] or None,
    })
    if parsed.pay_raw and not opp.get("pay_raw"):
        updates["pay_raw"] = parsed.pay_raw[:300]
    if parsed.deadline_at and not opp.get("deadline_at"):
        updates["deadline_at"], updates["deadline_confidence"] = parsed.deadline_at, "high"
    if parsed.hours_per_week:
        updates["hours_per_week"] = parsed.hours_per_week
    if parsed.duration_months:
        updates["duration_months"] = parsed.duration_months
    if parsed.apply.get("email"):
        updates.update(apply_channel="email", apply_email=parsed.apply["email"],
                       apply_email_quote=parsed.apply.get("email_quote", "")[:500])
    if opp.get("automation") == "manual_lane":
        updates["apply_channel"] = "manual"
    reqs = len(parsed.requirements)
    return RunResult(output={"ok": True, "requirements": reqs, "method": parsed.method},
                     effects=[{"op": "opp.update", "id": opp["id"], "values": updates}],
                     summary=f"Parsed {label(opp)}: {reqs} requirement quotes"
                             + (f", pay “{parsed.pay_raw}”" if parsed.pay_raw else ", pay not stated"),
                     model_id=model_id)
