"""Strategist daily review (CONTRACT_E §1) and the analytics aggregates behind it (§2).

The review is written every day even with no model; code decides every action, and the only automatic changes are
switching off a failing source (never while every source fails) and adding an ATS board a GET proved exists."""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from conftest import MUTATE, drive

from hq import insights
from hq.adapters.base import Services
from hq.db.conn import tx
from hq.db.seed import set_settings
from hq.llm.claude import ClaudeResult
from hq.pipeline.discover.fetch import Fetcher
from hq.util.timeutil import now_iso, to_iso, utcnow
from hq.worker import effects, queue
from hq.worker.orchestrator import Worker


class FakeCloud:
    reason = "fake"

    def __init__(self, output: dict[str, Any]):
        self.output = output
        self.prompts: list[str] = []

    async def available(self) -> bool:
        return True

    async def run(self, prompt: str, *, schema: dict, system_prompt: str, model: str, max_budget_usd: float,
                  **_: Any) -> ClaudeResult:
        self.prompts.append(prompt)
        return ClaudeResult(output=self.output, cost_usd=0.01, input_tokens=900, output_tokens=200,
                            cache_read_tokens=0, duration_ms=10.0, model=model, subtype="success")


def _board(req: httpx.Request) -> httpx.Response:
    if req.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")
    if req.url.path == "/v1/boards/goodco/jobs":
        return httpx.Response(200, json={"jobs": [{"id": 1, "title": "ML Intern", "absolute_url": "https://x/1",
                                                   "location": {"name": "Remote"}, "content": "Python"}]})
    return httpx.Response(404)


async def _nosleep(_):
    return None


def _worker(db, team, claude=None) -> Worker:
    return Worker(conn=db, agents_dir=team, loop_interval=0.01, watch=False, schedule=False,
                  services=Services(claude=claude, fetcher=Fetcher(db, transport=httpx.MockTransport(_board),
                                                                   sleep=_nosleep)))


async def _review(db, team, claude=None) -> dict[str, Any]:
    w = _worker(db, team, claude)
    w.startup()
    with tx(db):
        queue.enqueue(db, "strategy.daily_review", type_="scheduled")
    ok = await drive(w, lambda: db.execute("SELECT 1 FROM strategy_reports").fetchone() is not None, timeout=10)
    await w.shutdown()
    assert ok, [dict(r) for r in db.execute("SELECT capability, status, last_error FROM tasks")]
    row = dict(db.execute("SELECT * FROM strategy_reports").fetchone())
    row["applied"] = json.loads(row["applied_actions_json"])
    row["proposed"] = json.loads(row["proposed_actions_json"])
    return row


def _break(db, source_id: str, errors: int = 6) -> None:
    db.execute("UPDATE sources SET consecutive_errors=? WHERE id=?", (errors, source_id))


def test_strategist_agent_is_real_and_runs_at_0730_ist(team):
    import yaml

    cfg = yaml.safe_load((team / "strategist.yaml").read_text())
    assert cfg["adapter"] == "script" and cfg["adapter_config"]["module"] == "hq.pipeline.agents.strategist"
    assert cfg["schedule"] == {"mode": "cron", "cron": "30 7 * * *"}


async def test_builtin_review_without_any_model(db, team):
    with tx(db):
        set_settings(db, {"sim_enabled": False})
    r = await _review(db, team)
    assert "Last 24 h" in r["report_md"] and "What worked" in r["report_md"]
    assert r["applied"] == [] and r["created_at"]
    note = db.execute("SELECT title, url FROM notifications").fetchone()
    assert note["title"] == "Strategist: daily review ready" and note["url"] == "/analytics"


async def test_failing_source_is_switched_off_only_while_others_work(db, team):
    with tx(db):
        set_settings(db, {"sim_enabled": False})
        _break(db, "greenhouse:stripe")
    r = await _review(db, team)
    assert r["applied"] == []   # nothing polled fine in 24 h: maybe the Wi-Fi, so nothing is switched off
    assert db.execute("SELECT enabled FROM sources WHERE id='greenhouse:stripe'").fetchone()[0] == 1

    with tx(db):
        db.execute("DELETE FROM strategy_reports")
        db.execute("UPDATE sources SET last_ok_at=? WHERE id='greenhouse:figma'", (now_iso(),))
    r = await _review(db, team)
    assert [a["params"]["source_id"] for a in r["applied"]] == ["greenhouse:stripe"]
    assert db.execute("SELECT enabled FROM sources WHERE id='greenhouse:stripe'").fetchone()[0] == 0
    assert db.execute("SELECT 1 FROM audit_log WHERE actor='strategist' AND action='source.disable' AND "
                      "target='greenhouse:stripe'").fetchone()
    assert "Turned off" in r["report_md"]


async def test_model_suggestions_are_checked_before_anything_changes(db, team):
    cloud = FakeCloud({"report_md": "# Today\nStripe's board keeps failing; try GoodCo.", "actions": [
        {"type": "add_ats_slug", "params": {"provider": "greenhouse", "slug": "goodco", "company": "GoodCo"},
         "rationale": "Hires ML interns", "risk": "low"},
        {"type": "add_ats_slug", "params": {"provider": "greenhouse", "slug": "ghostco"}, "rationale": "maybe"},
        {"type": "add_ats_slug", "params": {"provider": "workday", "slug": "evil"}, "rationale": "not an ATS we use"},
        {"type": "add_ats_slug", "params": {"provider": "greenhouse", "slug": "../../etc"}, "rationale": "bad slug"},
        {"type": "disable_source", "params": {"source_id": "greenhouse:anthropic"}, "rationale": "healthy one"},
        {"type": "change_threshold", "params": {"setting": "fit_draft_threshold", "value": 55},
         "rationale": "few drafts", "risk": "medium"}]})
    with tx(db):
        set_settings(db, {"sim_enabled": False})
    r = await _review(db, team, cloud)
    assert r["report_md"].startswith("# Today") and cloud.prompts and "PIPELINE DATA" in cloud.prompts[0]
    src = db.execute("SELECT enabled, added_by, kind FROM sources WHERE id='greenhouse:goodco'").fetchone()
    assert tuple(src) == (1, "strategist", "greenhouse")
    assert [a["type"] for a in r["applied"]] == ["add_ats_slug"]
    assert not db.execute("SELECT 1 FROM sources WHERE id IN ('greenhouse:ghostco','workday:evil')").fetchone()
    assert db.execute("SELECT enabled FROM sources WHERE id='greenhouse:anthropic'").fetchone()[0] == 1
    kinds = sorted((p["type"], p["status"]) for p in r["proposed"])
    assert kinds == [("add_ats_slug", "not_verified"), ("change_threshold", "proposed"),
                     ("disable_source", "proposed")]
    assert db.execute("SELECT COUNT(*) FROM claude_usage").fetchone()[0] == 1


def test_only_the_strategist_may_change_sources(db):
    with tx(db), pytest.raises(ValueError, match="only the Strategist"):
        effects.apply_effects(db, [{"op": "source.disable", "id": "greenhouse:stripe"}], agent_id="scout",
                              task_id="t", run_id="r")


def test_run_now_queues_one_review(authed, db, team):
    from hq.agents.registry import Registry

    Registry(team, db).scan()
    r = authed.post("/api/strategy/run", headers=MUTATE)
    assert r.status_code == 200 and r.json()["queued"] is True
    again = authed.post("/api/strategy/run", headers=MUTATE).json()
    assert again["queued"] is False and again["task_id"] == r.json()["task_id"]
    assert db.execute("SELECT COUNT(*) FROM tasks WHERE capability='strategy.daily_review'").fetchone()[0] == 1


# ── analytics ────────────────────────────────────────────────────────────────────────────────────────
def _opp(db, key: str, stage: str, *, sim: int = 0, country: str = "IN", pay: float | None = None,
         reason: str | None = None, source: str | None = None, days_ago: float = 0) -> str:
    from hq.util.ids import new_id

    oid = new_id()
    ts = to_iso(utcnow() - timedelta(days=days_ago))
    db.execute("INSERT INTO opportunities(id, canonical_key, is_simulated, company_name, title, kind, role_type, "
               "country_iso2, stage, stage_reason, pay_monthly_inr_mid, first_seen_at, updated_at) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (oid, key, sim, f"Co {key}", "ML Intern", "internship", "ml", country, stage, reason, pay, ts, ts))
    if source:
        db.execute("INSERT INTO opportunity_sources(opportunity_id, source_id, external_id, source_url, first_seen, "
                   "last_seen) VALUES (?,?,?,?,?,?)", (oid, source, key, "https://x", ts, ts))
    return oid


def test_analytics_funnel_rates_and_pay(db):
    with tx(db):
        _opp(db, "a", "found", pay=12_000, source="greenhouse:stripe")
        _opp(db, "b", "filtered", reason="ineligible: 7th semester only", source="greenhouse:stripe")
        _opp(db, "c", "applied", pay=40_000, source="greenhouse:stripe")
        _opp(db, "d", "interview", pay=150_000, country="CH", source="lever:paytm")
        _opp(db, "e", "rejected", pay=30_000, source="lever:paytm")
        _opp(db, "f", "frozen", pay=99_000, source="legacy")
        _opp(db, "g", "checked", sim=1, pay=35_000)
    a = insights.analytics(db, scope="real", days=30)
    assert a["totals"]["opportunities"] == 5 and a["totals"]["history"] == 1 and a["totals"]["applied"] == 3
    assert [f["n"] for f in a["funnel"]] == [5, 3, 3, 3, 3, 2, 1, 0]
    by_src = {r["key"]: r for r in a["reply_rates"]["source"]}
    assert by_src["lever:paytm"]["rate"] == 1.0 and by_src["greenhouse:stripe"]["rate"] == 0.0
    assert a["gate_failures"]["filtered"] == [{"reason": "ineligible", "n": 1}]
    hist = {b["label"]: b["n"] for b in a["pay_histogram"]["buckets"]}
    assert hist["₹10–20K"] == 1 and hist["₹1L+"] == 1 and a["pay_histogram"]["unknown"] == 0
    assert a["pay_by_country"][0]["country"] == "CH"
    names = [s["name"] for s in a["sources"]]
    assert "Legacy shortlist" not in names and names == ["Lever · paytm", "Greenhouse · stripe"]  # most applied first
    assert insights.analytics(db, scope="sim")["totals"]["opportunities"] == 1
    assert len(a["applications_per_day"]) == 30 and len(a["cloud_spend"]["days"]) == 30


def test_analytics_api(authed):
    r = authed.get("/api/analytics?scope=real&days=14")
    assert r.status_code == 200 and r.json()["days"] == 14
    assert authed.get("/api/analytics?scope=bogus").status_code == 422


@pytest.mark.parametrize("reason, category", [
    ("Ineligible: 'Only 7th/8th semester students'", "ineligible"), ("Posting closed: 404", "expired"),
    ("Expired: deadline 2026-09-01 passed", "expired"), ("Scam signals: fee “₹999 registration”", "scam"),
    ("Charges a fee", "scam"), ("Pay ₹9,000/mo is 0.60× living cost (needs 1.0×)", "pay"), ("Unpaid", "unpaid"),
    ("Fit 40 < 60 — parked", "low_fit"), ("Dates don't fit: needs June–Aug", "availability"),
    ("Posting unreadable (empty, login wall or closed)", "unreadable"), ("mill: known internship mill", "mill"),
    (None, "other"), ("something new", "other"),
])
def test_filter_reason_categories(reason, category):
    assert insights.filter_reason(reason) == category
