"""`sim` adapter (CONTRACT §8): realistic, clearly-simulated agent work for phase (a).

Each run takes 2–8 s ÷ sim_speed, updates progress 3–6 times with a believable "now" line, reports plausible
token counts / tok/s, fails transiently ~5% of the time, and returns `effects` (rows to write) that the worker
commits together with the pipeline transition. Outbound "sends" only ever produce `mock_mail` effects.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import timedelta
from typing import Any, Awaitable, Callable

from hq.adapters.base import RunContext, RunResult, TransientError
from hq.db.repo import TERMINAL_STAGES
from hq.sim import texts
from hq.sim.pool import CITIES, ROLES, SimRole, compute_pay, is_funded_program, role_for_canonical_key
from hq.util.ids import new_id
from hq.util.timeutil import IST, now_iso, parse_iso, to_iso, today_ist, utcnow

MAX_ACTIVE_SIM_OPPS = 60

# tok/s ranges per simulated local model (measured-ish on the M-series Mac; contract range 40–370)
LOCAL_TOK_S = {
    "qwen3-4b-2507": (150, 260), "qwen3-coder-30b-a3b": (78, 108), "qwen2.5-7b": (52, 88),
    "qwen2.5-3b": (170, 300), "qwen3-0.6b": (260, 370),
}
NON_LLM = {"chrome-headless", "mock-mailer", "rules"}

TRANSIENT = [
    "HTTP 503 from board API (sim) — will retry",
    "Model server restarted mid-stream (sim)",
    "Timed out reading page after 30 s (sim)",
    "JSON repair failed twice (sim)",
    "SQLite busy while staging results (sim)",
]

ACTIVE_STAGES = ("found", "verified", "drafted", "checked", "applied", "replied", "interview")


def _seeded(*parts: str) -> random.Random:
    return random.Random(int(hashlib.sha256(":".join(parts).encode()).hexdigest()[:16], 16))


class SimAdapter:
    name = "sim"

    def __init__(self, *, seed: int | None = None, duration_scale: float = 1.0, fail_rate: float = 0.05,
                 reply_delay_s: tuple[float, float] = (45.0, 240.0), reply_rate: float = 0.7,
                 bad_draft_rate: float = 0.12):
        self.seed = seed
        self.duration_scale = duration_scale
        self.fail_rate = fail_rate
        self.reply_delay_s = reply_delay_s
        self.reply_rate = reply_rate
        self.bad_draft_rate = bad_draft_rate
        self._handlers: dict[str, Callable[..., Awaitable[RunResult]]] = {
            "discover.ats": self._discover, "discover.program_page": self._discover,
            "discover.feed": self._discover, "discover.email_alerts": self._discover,
            "parse.job": self._parse, "verify.link": self._verify_link, "verify.deadline": self._verify_link,
            "verify.eligibility": self._verify_eligibility, "verify.scam": self._verify_scam,
            "verify.pay": self._verify_pay, "score.fit": self._score_fit, "draft.cover_letter": self._draft,
            "factcheck.deterministic": self._factcheck, "factcheck.sentence": self._factcheck,
            "check.quality": self._factcheck, "factcheck.signoff": self._signoff,
            "build.resume": self._build_resume, "apply.email_send": self._apply_email,
            "apply.manual_pack": self._manual_pack, "followup.schedule": self._followup,
            "inbox.poll": self._inbox_poll, "inbox.classify": self._inbox_classify,
            "strategy.daily_review": self._strategy,
        }

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "detail": "simulation adapter (no network)"}

    # ── plumbing ────────────────────────────────────────────────────────────────────────────────────
    def _rng(self, task: dict[str, Any]) -> random.Random:
        if self.seed is None:
            return random.Random()
        return _seeded(str(self.seed), task["id"], str(task.get("attempts", 0)))

    @staticmethod
    def _speed(ctx: RunContext) -> float:
        try:
            return min(4.0, max(0.25, float(ctx.settings.get("sim_speed", 1.0))))
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def _sim_model(ctx: RunContext) -> str:
        return str(ctx.agent.adapter_config.get("sim_model") or ctx.agent.model or "qwen3-4b-2507").split(":")[-1]

    def _is_claude(self, ctx: RunContext) -> bool:
        return ctx.agent.cost_tier == "claude" or self._sim_model(ctx).startswith("claude")

    async def _work(self, ctx: RunContext, rng: random.Random, lines: list[str], *, can_fail: bool = True,
                    opportunity_id: str | None = None) -> float | None:
        """Spread `lines` over 2–8 s ÷ sim_speed with progress updates; maybe raise a transient failure."""
        model = self._sim_model(ctx)
        model_id = f"sim:{model}"
        tok_range = None if (model in NON_LLM or self._is_claude(ctx)) else LOCAL_TOK_S.get(model, (60, 200))
        lines = [ln for ln in lines if ln][:6]
        while len(lines) < 3:
            lines.append(rng.choice(["Cross-checking intermediate results…", "Writing structured output…",
                                     "Validating JSON against schema…"]))
        total = rng.uniform(2.0, 8.0) / self._speed(ctx) * self.duration_scale
        fail_at = rng.randrange(len(lines)) if can_fail and rng.random() < self.fail_rate else None
        tok_s = None
        for i, line in enumerate(lines):
            tok_s = round(rng.uniform(*tok_range), 1) if tok_range else None
            ctx.progress(i / len(lines), line, tok_s=tok_s, model_id=model_id, opportunity_id=opportunity_id)
            await ctx.sleep(total / len(lines))
            if fail_at == i:
                raise TransientError(rng.choice(TRANSIENT))
        ctx.progress(1.0, "Committing results…", tok_s=tok_s, model_id=model_id, opportunity_id=opportunity_id)
        return tok_s

    def _result(self, ctx: RunContext, rng: random.Random, tok_s: float | None, **kw: Any) -> RunResult:
        model = self._sim_model(ctx)
        res = RunResult(model_id=f"sim:{model}", tok_s=tok_s, **kw)
        if model in NON_LLM:
            return res
        res.prompt_tokens = rng.randint(400, 3200)
        res.completion_tokens = rng.randint(60, 650)
        if self._is_claude(ctx):
            res.tok_s = None
            res.cost_usd = round(rng.uniform(0.012, 0.058), 4)
        else:
            res.ttft_ms = round(rng.uniform(90, 900), 1)
        return res

    def _load(self, ctx: RunContext) -> tuple[dict[str, Any] | None, SimRole | None]:
        if not ctx.opportunity_id:
            return None, None
        rows = ctx.query("SELECT * FROM opportunities WHERE id=?", (ctx.opportunity_id,))
        if not rows:
            return None, None
        opp = rows[0]
        return opp, role_for_canonical_key(opp["canonical_key"]) if opp["is_simulated"] else None

    @staticmethod
    def _noop(reason: str) -> RunResult:
        return RunResult(output={"ok": False, "noop": True, "reason": reason}, summary=f"Skipped: {reason}")

    def _application(self, ctx: RunContext, opp_id: str) -> dict[str, Any] | None:
        rows = ctx.query("SELECT * FROM applications WHERE opportunity_id=? ORDER BY created_at DESC LIMIT 1",
                         (opp_id,))
        return rows[0] if rows else None

    def _latest_letter(self, ctx: RunContext, opp_id: str) -> dict[str, Any] | None:
        rows = ctx.query("SELECT * FROM documents WHERE opportunity_id=? AND kind='cover_letter' "
                         "ORDER BY version DESC LIMIT 1", (opp_id,))
        return rows[0] if rows else None

    async def run(self, task: dict[str, Any], ctx: RunContext) -> RunResult:
        rng = self._rng(task)
        handler = self._handlers.get(task["capability"], self._generic)
        return await handler(task, ctx, rng)

    # ── discovery ───────────────────────────────────────────────────────────────────────────────────
    async def _discover(self, task: dict[str, Any], ctx: RunContext, rng: random.Random) -> RunResult:
        stages = ",".join("?" * len(ACTIVE_STAGES))
        active = ctx.query(f"SELECT canonical_key FROM opportunities WHERE is_simulated=1 AND stage IN ({stages})",
                           ACTIVE_STAGES)
        known = ctx.query("SELECT COUNT(*) AS n FROM opportunities")[0]["n"]
        if len(active) > MAX_ACTIVE_SIM_OPPS:
            tok_s = await self._work(ctx, rng, [
                f"Pipeline full ({len(active)} active sim items) — skipping discovery this round",
                "Waiting for downstream agents to catch up…"], can_fail=False)
            return self._result(ctx, rng, tok_s, output={"ok": True, "created": 0, "reason": "pipeline full"},
                                summary="Pipeline full — no new postings added")
        busy = {row["canonical_key"].split(":")[1] for row in active if row["canonical_key"].startswith("sim:")}
        program = task["capability"] == "discover.program_page"
        wanted = [r for r in ROLES if r.key not in busy
                  and (r.board in ("program_page", "lab_page")) == program]
        if not wanted:
            wanted = [r for r in ROLES if r.key not in busy]
        picks = rng.sample(wanted, k=min(len(wanted), rng.choice([1, 1, 2])))
        tok_s = await self._work(ctx, rng, texts.discover_lines(rng, picks, known))
        effects, opp_results = [], []
        now = utcnow()
        for role in picks:
            opp_id = new_id()
            city = CITIES[role.city]
            req = rng.randint(10000, 99999)
            deadline = None if role.deadline_days is None else to_iso(
                (now + timedelta(days=role.deadline_days)).replace(hour=18, minute=29, second=0, microsecond=0))
            pay = compute_pay(role)
            values = {
                "id": opp_id, "canonical_key": f"sim:{role.key}:{req}", "company_name": role.company,
                "title": role.title, "kind": role.kind, "role_type": role.role_type,
                "location_raw": f"{city.name}, {city.country_iso2}" + (" (remote)" if role.work_mode == "remote" else ""),
                "city": city.name, "country_iso2": city.country_iso2,
                "lat": round(city.lat + rng.uniform(-0.03, 0.03), 4), "lon": round(city.lon + rng.uniform(-0.03, 0.03), 4),
                "work_mode": role.work_mode, "url": f"https://careers.{role.slug}.example/jobs/{req}",
                "apply_url": f"https://careers.{role.slug}.example/jobs/{req}/apply",
                "apply_channel": role.channel, "apply_email": role.apply_email,
                "apply_email_quote": f"Send your CV and a short cover letter to {role.apply_email}"
                if role.apply_email else None,
                "deadline_at": deadline, "deadline_confidence": "rolling" if deadline is None else "high",
                "posted_at": to_iso(now - timedelta(days=rng.randint(0, 9))),
                "duration_months": role.duration_months,
                "pay_raw": pay["pay_raw"], "pay_min": pay["pay_min"], "pay_max": pay["pay_max"],
                "pay_currency": pay["pay_currency"], "pay_period": pay["pay_period"],
                "pay_status": role.pay.status, "stage": "found",
                "source_label": f"{role.board_label} · {role.company} (sim)",
            }
            effects.append({"op": "opp.create", "values": values, "is_simulated": True})
            opp_results.append((opp_id, {"created": True}))
        names = ", ".join(f"{r.company} — {r.title}" for r in picks)
        return self._result(ctx, rng, tok_s, output={"ok": True, "created": len(picks),
                                                     "roles": [r.key for r in picks]},
                            effects=effects, opp_results=opp_results, summary=f"Found {len(picks)}: {names}")

    async def _parse(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        tok_s = await self._work(ctx, rng, texts.parse_lines(rng, role))
        eff = [{"op": "opp.update", "id": opp["id"], "values": {"summary": role.summary}}]
        return self._result(ctx, rng, tok_s, output={"ok": True, "channel": role.channel}, effects=eff,
                            summary=f"Parsed {role.company} — {role.title}: {role.channel.replace('_', ' ')}, "
                                    f"pay \"{role.pay.raw}\"")

    # ── verification ────────────────────────────────────────────────────────────────────────────────
    async def _verify_link(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        deadline = parse_iso(opp.get("deadline_at"))
        now = utcnow()
        if deadline is None:
            note = "No deadline listed → rolling; re-verify every 3 days"
        else:
            days = (deadline - timedelta(days=1) - now).days
            note = (f"Deadline {deadline.astimezone(IST).date()} (conservative −1 day) → {days} days left"
                    if days >= 0 else f"Deadline {deadline.astimezone(IST).date()} has passed")
        tok_s = await self._work(ctx, rng, texts.link_lines(rng, role, opp["url"], note))
        eff = [{"op": "opp.update", "id": opp["id"], "values": {"link_status": "live", "last_verified_at": now_iso()}}]
        if deadline is not None and deadline - timedelta(days=1) < now:
            reason = f"expired: deadline {deadline.astimezone(IST).date()} has passed"
            return self._result(ctx, rng, tok_s, output={"ok": False, "stage_reason": reason}, effects=eff,
                                summary=f"Filtered {role.company}: {reason}")
        return self._result(ctx, rng, tok_s, output={"ok": True}, effects=eff,
                            summary=f"Link live for {role.company} — {role.title}; {note.lower()}")

    async def _verify_eligibility(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        tok_s = await self._work(ctx, rng, texts.eligibility_lines(rng, role))
        verdict, quote = role.eligibility
        conf = round(rng.uniform(0.88, 0.98), 2)
        eff = [
            {"op": "eligibility_check", "values": {
                "opportunity_id": opp["id"], "method": "sim_rules+llm", "model_id": f"sim:{self._sim_model(ctx)}",
                "requirements_json": {"grad_year": 2028, "semester": 3, "degree": "B.Tech CSE (AI/ML)"},
                "quotes_json": [quote], "verdict": verdict, "confidence": conf, "run_id": ctx.run_id}},
            {"op": "opp.update", "id": opp["id"],
             "values": {"eligibility_status": verdict, "eligibility_confidence": conf}},
        ]
        if verdict == "ineligible":
            reason = f"ineligible: '{quote}'"
            return self._result(ctx, rng, tok_s, output={"ok": False, "stage_reason": reason}, effects=eff,
                                summary=f"Filtered {role.company}: {reason}")
        label = "eligible with gaps" if verdict == "eligible_gaps" else "eligible"
        return self._result(ctx, rng, tok_s, output={"ok": True, "verdict": verdict}, effects=eff,
                            summary=f"{role.company}: {label} ('{quote}', confidence {conf})")

    async def _verify_scam(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        tok_s = await self._work(ctx, rng, texts.scam_lines(rng, role))
        scam = role.trap in ("scam", "mill")
        verdict = "scam" if scam else "clean"
        eff = [{"op": "scam_check", "values": {
                    "opportunity_id": opp["id"], "signals_json": [role.scam_signal] if scam else [],
                    "verdict": verdict, "run_id": ctx.run_id}},
               {"op": "opp.update", "id": opp["id"], "values": {"scam_status": verdict}}]
        if scam:
            reason = f"{'mill' if role.trap == 'mill' else 'scam'}: {role.scam_signal}"
            return self._result(ctx, rng, tok_s, output={"ok": False, "stage_reason": reason}, effects=eff,
                                summary=f"Filtered {role.company}: {reason}")
        return self._result(ctx, rng, tok_s, output={"ok": True}, effects=eff,
                            summary=f"{role.company}: no scam signals")

    async def _verify_pay(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        pay = compute_pay(role)
        tok_s = await self._work(ctx, rng, texts.pay_lines(role, pay))
        values = {k: v for k, v in pay.items() if k.startswith(("pay_", "fx_", "living_", "benefits"))}
        values["hours_per_week"] = pay["hours_per_week"]
        eff: list[dict[str, Any]] = [{"op": "opp.update", "id": opp["id"], "values": values}]
        status, ratio = pay["pay_status"], pay["pay_ratio"]
        min_ratio = float(ctx.settings.get("min_pay_ratio", 1.0))
        funded = is_funded_program(role, float(ctx.settings.get("funded_program_min_inr", 5000)))
        mid = texts.fmt_inr(pay["pay_monthly_inr_mid"])
        if status == "unpaid":
            return self._result(ctx, rng, tok_s, output={"ok": False, "stage_reason": "unpaid posting"},
                                effects=eff, summary=f"Filtered {role.company}: unpaid")
        if status == "fee_required":
            return self._result(ctx, rng, tok_s, output={"ok": False, "stage_reason": "asks the applicant to pay"},
                                effects=eff, summary=f"Filtered {role.company}: fee required")
        if status == "unknown":
            policy = ctx.settings.get("unknown_pay_policy", "decision")
            if policy == "reject":
                return self._result(ctx, rng, tok_s, output={"ok": False, "stage_reason": "pay not listed"},
                                    effects=eff, summary=f"Filtered {role.company}: pay not listed")
            if policy == "decision":
                eff.append({"op": "need.create", "values": {
                    "opportunity_id": opp["id"], "kind": "decision",
                    "title": f"Pay not listed — keep {role.company} in the pipeline?",
                    "instructions_md": f"**{role.title}** at {role.company} says: \"{role.pay.raw}\".\n\n"
                                       "The pipeline continues meanwhile; dismiss to keep it, or drag the card to "
                                       "*filtered* to drop it. (Simulated item.)",
                    "priority": 40, "est_minutes": 0.5, "direct_url": opp["url"]}})
            return self._result(ctx, rng, tok_s, output={"ok": True, "pay": "unknown"}, effects=eff,
                                summary=f"{role.company}: pay not listed → decision requested")
        if status == "variable":
            hr = texts.fmt_inr(pay["pay_hourly_inr_min"])
            return self._result(ctx, rng, tok_s, output={"ok": True, "pay": "variable"}, effects=eff,
                                summary=f"{role.company}: {hr}/h, hours not stated → variable")
        if funded:
            return self._result(ctx, rng, tok_s, output={"ok": True, "pay": "funded"}, effects=eff,
                                summary=f"{role.company}: funded program — stay + food + travel + {mid}/mo")
        if ratio is not None and ratio < min_ratio:
            place = "Greater Noida (remote)" if role.work_mode == "remote" else CITIES[role.city].name
            reason = f"pay below living cost ({ratio:.2f}× in {place})"
            return self._result(ctx, rng, tok_s, output={"ok": False, "stage_reason": reason}, effects=eff,
                                summary=f"Filtered {role.company}: {reason}")
        return self._result(ctx, rng, tok_s, output={"ok": True, "pay": "listed", "ratio": ratio}, effects=eff,
                            summary=f"{role.company}: {mid}/mo, {ratio:.2f}× living cost")

    async def _score_fit(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        score = max(0, min(100, role.fit + _seeded(opp["id"], "fit").randint(-5, 5)))
        tok_s = await self._work(ctx, rng, texts.fit_lines(rng, role, score))
        threshold = int(ctx.settings.get("fit_draft_threshold", 60))
        cap = int(ctx.settings.get("daily_draft_cap", 20))
        since = to_iso(utcnow().astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0))
        drafts_today = ctx.query("SELECT COUNT(*) AS n FROM documents WHERE kind='cover_letter' AND version=1 "
                                 "AND created_at >= ?", (since,))[0]["n"]
        breakdown = {"relevance": min(25, round(score * 0.25)), "skills": min(20, round(score * 0.2)),
                     "eligibility": 15 if role.eligibility[0] == "eligible" else 10, "pay": 12, "source": 8,
                     "deadline": 4, "location": 4, "benefits": 5 if role.pay.benefits else 2}
        values: dict[str, Any] = {"fit_score": score, "fit_breakdown_json": breakdown}
        advance = score >= threshold and drafts_today < cap
        if score < threshold:
            values["stage_reason"] = f"fit {score} < {threshold} — parked"
        elif not advance:
            values["stage_reason"] = f"daily draft cap ({cap}) reached — waiting"
        else:
            values["stage_reason"] = None
        eff = [{"op": "opp.update", "id": opp["id"], "values": values}]
        return self._result(ctx, rng, tok_s, output={"ok": True, "fit_score": score, "advance": advance},
                            effects=eff, summary=f"{role.company} fit {score}/100"
                                                 + ("" if advance else f" — {values['stage_reason']}"))

    # ── drafting & checks ───────────────────────────────────────────────────────────────────────────
    def _will_fail_rules(self, opp_id: str) -> bool:
        return _seeded(opp_id, "badclaim").random() < self.bad_draft_rate

    async def _draft(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        version = int((task.get("payload") or {}).get("version") or 1)
        model = self._sim_model(ctx)
        tok_range = LOCAL_TOK_S.get(model, (70, 110))
        tok_s = await self._work(ctx, rng, texts.draft_lines(rng, role, version, rng.uniform(*tok_range)))
        bad = version == 1 and self._will_fail_rules(opp["id"])
        text, sentences = texts.letter_text(role, version, bad_claim=bad)
        app = self._application(ctx, opp["id"])
        effects: list[dict[str, Any]] = []
        app_id = app["id"] if app else new_id()
        if not app:
            effects.append({"op": "application.create", "values": {
                "id": app_id, "opportunity_id": opp["id"], "channel": role.channel, "status": "drafting",
                "mode": ctx.settings.get("mode", "dry_run")}})
        prev = self._latest_letter(ctx, opp["id"])
        doc_id = new_id()
        lineage = (prev.get("lineage_models_json") if prev else None) or "[]"
        lineage_list = json.loads(lineage) if isinstance(lineage, str) else list(lineage)
        if f"sim:{model}" not in lineage_list:
            lineage_list.append(f"sim:{model}")
        effects.append({"op": "document.create", "values": {
            "id": doc_id, "application_id": app_id, "opportunity_id": opp["id"], "kind": "cover_letter",
            "version": version, "parent_id": prev["id"] if prev else None, "content_text": text,
            "author_agent": ctx.agent.id, "author_model": f"sim:{model}", "lineage_models_json": lineage_list,
            "status": "draft"}, "sentences": sentences})
        effects.append({"op": "application.update", "id": app_id,
                        "values": {"letter_doc_id": doc_id, "status": "checking"}})
        return self._result(ctx, rng, tok_s, output={"ok": True, "version": version, "document_id": doc_id},
                            effects=effects,
                            summary=f"Drafted cover letter v{version} for {role.company} ({len(sentences)} sentences)")

    async def _factcheck(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        doc = self._latest_letter(ctx, opp["id"])
        if not doc:
            return self._noop("no letter to check")
        cap = task["capability"]
        n_sent = len([s for s in (doc.get("content_text") or "").splitlines() if s.strip()]) - 1
        tok_s = await self._work(ctx, rng, texts.factcheck_lines(rng, cap, max(n_sent, 4)))
        version = int(doc["version"])
        gate = {"factcheck.deterministic": "fact_rules", "factcheck.sentence": "fact_sentences",
                "check.quality": "quality"}[cap]
        failed = cap == "factcheck.deterministic" and "deployed the recommender" in (doc.get("content_text") or "")
        details: dict[str, Any] = {"version": version, "checker_model": f"sim:{self._sim_model(ctx)}"}
        feedback = None
        if failed:
            feedback = ("BANNED_CLAIM: 'deployed … to production' in sentence 6 is not supported by F-BOOK-PIPELINE "
                        "(the project has a Streamlit demo, not a production deployment)")
            details.update(rule="BANNED_CLAIM", sentence=6, feedback=feedback)
        effects: list[dict[str, Any]] = [
            {"op": "gate_result", "values": {"application_id": doc["application_id"], "document_id": doc["id"],
                                             "gate": gate, "passed": 0 if failed else 1, "details_json": details}},
        ]
        if failed:
            effects.append({"op": "document.update", "id": doc["id"], "values": {"status": "failed"}})
            effects.append({"op": "event", "type": "log", "level": "warn",
                            "message": f"Fact gate blocked a claim in the {role.company} letter — sending back "
                                       "to the Writer", "data": {"rule": "BANNED_CLAIM"}})
            return self._result(ctx, rng, tok_s, output={"ok": False, "version": version, "feedback": feedback},
                                effects=effects, summary=f"{role.company} letter v{version}: {feedback[:60]}…")
        label = {"fact_rules": "deterministic rules", "fact_sentences": "per-sentence check",
                 "quality": "quality gate"}[gate]
        return self._result(ctx, rng, tok_s, output={"ok": True, "version": version}, effects=effects,
                            summary=f"{role.company} letter v{version} passed {label}")

    async def _signoff(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        doc = self._latest_letter(ctx, opp["id"])
        if not doc:
            return self._noop("no letter to sign off")
        tok_s = await self._work(ctx, rng, texts.signoff_lines(9))
        approve_first = ctx.settings.get("autonomy") == "approve_first"
        effects = [
            {"op": "gate_result", "values": {"application_id": doc["application_id"], "document_id": doc["id"],
                                             "gate": "claude_signoff", "passed": 1,
                                             "details_json": {"version": doc["version"], "verdict": "approved"}}},
            {"op": "document.update", "id": doc["id"], "values": {"status": "passed"}},
            {"op": "application.update", "id": doc["application_id"],
             "values": {"status": "awaiting_approval" if approve_first else "queued"}},
        ]
        return self._result(ctx, rng, tok_s, output={"ok": True, "version": doc["version"]}, effects=effects,
                            summary=f"Signed off {role.company} letter v{doc['version']}")

    async def _build_resume(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        tok_s = await self._work(ctx, rng, texts.resume_lines(role))
        app = self._application(ctx, opp["id"])
        doc_id = new_id()
        approve_first = ctx.settings.get("autonomy") == "approve_first"
        effects: list[dict[str, Any]] = [{"op": "document.create", "values": {
            "id": doc_id, "application_id": app["id"] if app else None, "opportunity_id": opp["id"],
            "kind": "resume_pdf", "version": 1, "status": "passed", "author_agent": ctx.agent.id,
            "author_model": "sim:chrome-headless", "lineage_models_json": [],
            "content_text": f"Tailored one-page résumé (simulated) — {role.role_type} emphasis, approved bullets only."}}]
        if app:
            effects.append({"op": "application.update", "id": app["id"], "values": {"resume_doc_id": doc_id}})
        if approve_first:
            effects.append({"op": "need.create", "values": {
                "opportunity_id": opp["id"], "application_id": app["id"] if app else None, "kind": "approve",
                "title": f"Approve application to {role.company} — {role.title}",
                "instructions_md": "Autonomy is set to **approve first**. Review the letter and résumé in the "
                                   "detail page, then mark this done to let the Applicant proceed. (Simulated.)",
                "priority": 70, "est_minutes": 2, "direct_url": opp["url"]}})
            effects.append({"op": "opp.update", "id": opp["id"],
                            "values": {"stage_reason": "awaiting Prerit's approval"}})
        return self._result(ctx, rng, tok_s,
                            output={"ok": True, "apply_channel": opp["apply_channel"],
                                    "approval_required": approve_first},
                            effects=effects, summary=f"Built one-page résumé for {role.company}")

    # ── applying ────────────────────────────────────────────────────────────────────────────────────
    async def _apply_email(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        if opp["stage"] in TERMINAL_STAGES or opp["stage"] == "applied":
            return self._noop(f"stage is {opp['stage']}")
        tok_s = await self._work(ctx, rng, texts.apply_email_lines(role), can_fail=True)
        app = self._application(ctx, opp["id"])
        letter = self._latest_letter(ctx, opp["id"])
        if not app or not letter or not opp.get("apply_email"):
            return self._noop("missing application, letter or apply address")
        subject = f"Application: {role.title} — Prerit Sangwan"
        mail_id = new_id()
        effects = [
            {"op": "mock_mail", "values": {
                "id": mail_id, "to_addr": opp["apply_email"], "subject": subject, "body": letter["content_text"],
                "attachments_json": [{"name": f"Prerit_Sangwan_Resume_{role.slug}.pdf", "sim": True}],
                "application_id": app["id"]}},
            {"op": "application.update", "id": app["id"], "values": {
                "status": "submitted", "submitted_at": now_iso(), "submission_ref": f"mock_mailbox:{mail_id}",
                "message_id": f"<{app['id'].lower()}.sim@agent-hq.local>"}},
            {"op": "document.update", "id": letter["id"], "values": {"status": "sent"}},
            {"op": "opp.update", "id": opp["id"], "values": {"stage_reason": "mock-sent (dry run)"}},
        ]
        return self._result(ctx, rng, tok_s, output={"ok": True, "channel": "email", "mock_mail_id": mail_id},
                            effects=effects, summary=f"Mock-sent application to {opp['apply_email']} (dry run)")

    async def _manual_pack(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        tok_s = await self._work(ctx, rng, texts.manual_pack_lines(rng, role))
        app = self._application(ctx, opp["id"])
        letter = self._latest_letter(ctx, opp["id"])
        answers = [
            {"label": "Full name", "value": "Prerit Sangwan", "copy": True},
            {"label": "University", "value": "Bennett University", "copy": True},
            {"label": "Degree / year", "value": "B.Tech CSE (AI/ML), 2nd year", "copy": True},
            {"label": "Expected graduation", "value": "2028", "copy": True},
            {"label": "Why this role? (≤ 300 chars)",
             "value": f"I built a KNN book recommender and a RandomForest churn model; {role.company}'s work — "
                      f"{role.job_quote[:90]} — is where I want to learn next.", "copy": True},
            {"label": "Phone", "value": "(fill yourself — not confirmed in Profile)", "copy": False},
            {"label": "Gender / EEO questions", "value": "Prefer not to say", "copy": True},
        ]
        files = [{"name": f"Prerit_Sangwan_Resume_{role.slug}.pdf", "path": f"data/artifacts/sim/{opp['id']}/resume.pdf"}]
        if letter:
            files.append({"name": f"Cover_letter_{role.slug}.txt", "path": f"data/artifacts/sim/{opp['id']}/letter.txt"})
        effects: list[dict[str, Any]] = [
            {"op": "need.create", "values": {
                "opportunity_id": opp["id"], "application_id": app["id"] if app else None, "kind": "submit_form",
                "title": f"Submit {role.company} — {role.title} ({'ATS form' if role.channel == 'ats_form' else 'portal'})",
                "instructions_md": f"1. Open the form (direct link).\n2. Paste the answers below.\n3. Upload the "
                                   f"résumé.\n4. Click *I submitted it*.\n\n_Simulated pack — the link is "
                                   f"fictional ({role.slug}.example)._",
                "answers_json": answers, "files_json": files, "direct_url": opp["apply_url"] or opp["url"],
                "priority": 60, "est_minutes": 2, "due_at": opp.get("deadline_at")}},
            {"op": "opp.update", "id": opp["id"],
             "values": {"stage_reason": "pre-filled pack ready — waiting for Prerit to submit"}},
        ]
        if app:
            effects.append({"op": "application.update", "id": app["id"], "values": {"status": "needs_prerit"}})
        return self._result(ctx, rng, tok_s, output={"ok": True, "channel": role.channel}, effects=effects,
                            summary=f"Pre-filled pack ready for {role.company} (≈2 min for Prerit)")

    async def _followup(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        app = self._application(ctx, opp["id"])
        submitted = parse_iso(app.get("submitted_at")) if app else None
        due = to_iso((submitted or utcnow()) + timedelta(days=10))
        tok_s = await self._work(ctx, rng, [
            f"Checking thread for {role.company}: no reply yet",
            f"Scheduling one follow-up for {parse_iso(due).astimezone(IST).date()} (10 days, only if no reply)",
            "Follow-up stays gated: never on a locked thread"], can_fail=False)
        effects = [{"op": "application.update", "id": app["id"], "values": {"followup_due_at": due}}] if app else []
        return self._result(ctx, rng, tok_s, output={"ok": True, "followup_due_at": due}, effects=effects,
                            summary=f"Follow-up for {role.company} scheduled for "
                                    f"{parse_iso(due).astimezone(IST).date()}")

    # ── inbox ───────────────────────────────────────────────────────────────────────────────────────
    def _reply_plan(self, opp_id: str, speed: float) -> tuple[bool, float]:
        r = _seeded(opp_id, "reply")
        will = r.random() < self.reply_rate
        delay = r.uniform(*self.reply_delay_s) / speed * self.duration_scale
        return will, delay

    @staticmethod
    def _classification(opp_id: str) -> str:
        x = _seeded(opp_id, "classify").random()
        for label, cut in (("interview", 0.30), ("rejection", 0.75), ("offer", 0.82), ("auto_ack", 0.92)):
            if x < cut:
                return label
        return "info_request"

    async def _inbox_poll(self, task, ctx, rng):
        rows = ctx.query(
            "SELECT o.id, o.canonical_key, a.id AS app_id, a.submitted_at FROM opportunities o "
            "JOIN applications a ON a.opportunity_id=o.id WHERE o.is_simulated=1 AND o.stage='applied' "
            "AND o.stage_override=0 AND a.submitted_at IS NOT NULL ORDER BY a.submitted_at LIMIT 200")
        speed = self._speed(ctx)
        now = utcnow()
        due = []
        for row in rows:
            will, delay = self._reply_plan(row["id"], speed)
            submitted = parse_iso(row["submitted_at"])
            if will and submitted and (now - submitted).total_seconds() >= delay:
                due.append(row)
        due = due[:3]
        tok_s = await self._work(ctx, rng, [
            f"Polling mock inbox (history id {rng.randint(40000, 99999)})…",
            f"{len(due)} new message{'s' if len(due) != 1 else ''} across {len(rows)} open applications",
            "Matching replies to application threads…"])
        effects, opp_results = [], []
        for row in due:
            role = role_for_canonical_key(row["canonical_key"])
            if role is None:
                continue
            label = self._classification(row["id"])
            subject, snippet = texts.reply_for(label, role)
            thread_id, msg_id = new_id(), new_id()
            effects.append({"op": "email.inbound", "thread": {
                "id": thread_id, "gmail_thread_id": f"sim-{thread_id.lower()}", "opportunity_id": row["id"],
                "application_id": row["app_id"], "subject": subject, "counterpart_domain": f"{role.slug}.example"},
                "message": {"id": msg_id, "gmail_message_id": f"sim-{msg_id.lower()}", "direction": "inbound",
                            "from_addr": f"recruiting@{role.slug}.example", "to_addr": "prerit (mock inbox)",
                            "subject": subject, "snippet": snippet}})
            opp_results.append((row["id"], {"reply": True, "message_id": msg_id, "stage_reason": "reply received"}))
        return self._result(ctx, rng, tok_s, output={"ok": True, "new_messages": len(opp_results)},
                            effects=effects, opp_results=opp_results,
                            summary=f"Inbox poll: {len(opp_results)} new repl{'y' if len(opp_results) == 1 else 'ies'}")

    async def _inbox_classify(self, task, ctx, rng):
        opp, role = self._load(ctx)
        if not role:
            return self._noop("opportunity is not simulated or no longer exists")
        msgs = ctx.query("SELECT m.id, m.thread_id FROM email_messages m JOIN email_threads t ON t.id=m.thread_id "
                         "WHERE t.opportunity_id=? ORDER BY m.rowid DESC LIMIT 1", (opp["id"],))
        label = self._classification(opp["id"])
        conf = round(rng.uniform(0.9, 0.99), 2)
        locked = label in ("interview", "offer", "info_request")
        tok_s = await self._work(ctx, rng, [
            f"Classifying reply from {role.company}…",
            "Rules pass: scheduling / offer / rejection lexicons…",
            f"Classified: {label.replace('_', ' ')} ({conf})" + (" → notify-only lock" if locked else "")])
        effects: list[dict[str, Any]] = []
        if msgs:
            effects.append({"op": "email.classify", "message_id": msgs[0]["id"], "thread_id": msgs[0]["thread_id"],
                            "classification": label, "confidence": conf, "lock": locked,
                            "lock_reason": label if locked else None})
        url = f"/o/{opp['id']}"
        if label == "interview":
            effects += [
                {"op": "need.create", "values": {
                    "opportunity_id": opp["id"], "kind": "interview",
                    "title": f"Interview request — {role.company} ({role.title})",
                    "instructions_md": "**Notify-only lock:** Agent HQ will not reply on this thread. Reply yourself "
                                       "with 2–3 time slots. (Simulated reply in the mock inbox.)",
                    "priority": 95, "est_minutes": 5}},
                {"op": "notification", "values": {"severity": "alert", "title": f"Interview request: {role.company}",
                                                  "body": f"{role.title} — reply yourself; agents are locked out of "
                                                          "this thread.", "url": url}},
                {"op": "opp.update", "id": opp["id"],
                 "values": {"stage_reason": "interview request — notify-only, reply yourself"}},
            ]
        elif label == "offer":
            effects += [
                {"op": "need.create", "values": {
                    "opportunity_id": opp["id"], "kind": "offer", "title": f"Offer — {role.company} ({role.title})",
                    "instructions_md": "**Notify-only lock:** review the offer yourself. Agents never act on money or "
                                       "contracts. (Simulated.)", "priority": 99, "est_minutes": 10}},
                {"op": "notification", "values": {"severity": "alert", "title": f"Offer from {role.company}",
                                                  "body": f"{role.title} — review it yourself.", "url": url}},
                {"op": "opp.update", "id": opp["id"], "values": {"stage_reason": "offer received — review yourself"}},
            ]
        elif label == "info_request":
            effects += [
                {"op": "need.create", "values": {
                    "opportunity_id": opp["id"], "kind": "missing_info",
                    "title": f"{role.company} asks about your availability",
                    "instructions_md": "They asked for availability dates and weekly hours. Reply yourself — "
                                       "availability is not confirmed in your Profile. (Simulated.)",
                    "priority": 80, "est_minutes": 3}},
                {"op": "opp.update", "id": opp["id"], "values": {"stage_reason": "asked for availability"}},
            ]
        elif label == "auto_ack":
            effects.append({"op": "opp.update", "id": opp["id"], "values": {"stage_reason": "auto-acknowledgement"}})
        elif label == "rejection":
            effects.append({"op": "opp.update", "id": opp["id"], "values": {"stage_reason": "rejection email"}})
        return self._result(ctx, rng, tok_s, output={"ok": True, "classification": label, "confidence": conf},
                            effects=effects,
                            summary=f"Reply from {role.company}: {label.replace('_', ' ')}"
                                    + (" — notify-only, no action taken" if locked else ""))

    # ── strategy / generic ──────────────────────────────────────────────────────────────────────────
    async def _strategy(self, task, ctx, rng):
        counts = {r["stage"]: r["n"] for r in ctx.query(
            "SELECT stage, COUNT(*) AS n FROM opportunities WHERE is_simulated=1 GROUP BY stage")}
        summary_counts = {
            "found": sum(counts.values()), "filtered": counts.get("filtered", 0),
            "verified": sum(counts.get(s, 0) for s in ("verified", "drafted", "checked", "applied", "replied",
                                                        "interview", "offer", "rejected")),
            "applied": sum(counts.get(s, 0) for s in ("applied", "replied", "interview", "offer", "rejected")),
            "replies": sum(counts.get(s, 0) for s in ("replied", "interview", "offer", "rejected")),
            "interview": counts.get("interview", 0), "offer": counts.get("offer", 0)}
        top = ctx.query("SELECT company_name, title, pay_monthly_inr_mid FROM opportunities WHERE is_simulated=1 "
                        "AND stage NOT IN ('filtered','rejected') AND pay_monthly_inr_mid IS NOT NULL "
                        "ORDER BY pay_monthly_inr_mid DESC LIMIT 3")
        tok_s = await self._work(ctx, rng, [
            f"Reviewing today's pipeline: {summary_counts['found']} found, {summary_counts['filtered']} filtered…",
            "Looking for sources with repeated scam or ineligible hits…",
            "Drafting proposals (need Prerit's OK)…", "Writing daily report…"])
        report = texts.strategy_report(summary_counts, top)
        effects = [{"op": "strategy_report", "values": {
            "date": today_ist().isoformat(), "report_md": report,
            "proposed_actions_json": [{"kind": "add_source", "detail": "two more Ashby boards (sim)"},
                                      {"kind": "tune_threshold", "detail": "fit threshold 55 for funded programs"}]}}]
        return self._result(ctx, rng, tok_s, output={"ok": True, **summary_counts}, effects=effects,
                            summary="Daily review written (simulated)")

    async def _generic(self, task, ctx, rng):
        opp, role = self._load(ctx)
        what = f"{role.company} — {role.title}" if role else "the current item"
        tok_s = await self._work(ctx, rng, [f"Working on {task['capability']} for {what}…",
                                            "Checking intermediate output…", "Writing structured result…"])
        return self._result(ctx, rng, tok_s, output={"ok": True}, summary=f"{task['capability']} done for {what}")
