"""Simulation content and end-to-end sim pipeline (offline: any HTTP attempt fails the test)."""
from __future__ import annotations

import json
import socket
from collections import Counter

import httpx
import pytest
from conftest import drive

from hq.db.conn import tx
from hq.db.seed import set_settings
from hq.sim.pool import CITIES, ROLES, SIM_FX_INR, compute_pay, is_funded_program, role_for_canonical_key
from hq.worker import queue
from hq.worker.orchestrator import Worker


@pytest.fixture
def offline(monkeypatch):
    """Fail loudly on any network use: httpx (sync + async) and raw sockets to non-local hosts."""
    calls = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise AssertionError("network access attempted during sim test")

    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost") and not host.startswith("/"):
            refuse(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    return calls


def test_pool_is_large_varied_and_fictional():
    assert len(ROLES) >= 40
    assert {CITIES[r.city].country_iso2 for r in ROLES} >= {"IN", "US", "DE", "CH", "TW", "JP", "SG", "GB", "CA",
                                                            "AE", "NL"}
    assert {r.kind for r in ROLES} >= {"internship", "part_time", "contract", "fellowship", "program"}
    traps = Counter(r.trap for r in ROLES)
    n = len(ROLES)
    assert 0.07 <= (traps["scam"] + traps["mill"]) / n <= 0.13
    assert 0.12 <= traps["ineligible"] / n <= 0.18
    assert 0.03 <= traps["expired"] / n <= 0.07
    for r in ROLES:
        assert r.apply_email is None or r.apply_email.endswith(".example")
        assert r.pay.currency is None or r.pay.currency in SIM_FX_INR
    statuses = Counter(compute_pay(r)["pay_status"] for r in ROLES)
    assert statuses["unknown"] >= 2 and statuses["variable"] >= 2 and statuses["unpaid"] >= 1
    assert sum(1 for r in ROLES if r.pay.benefits.get("housing")) >= 3


def test_pay_semantics():
    by_key = {r.key: r for r in ROLES}
    hourly = compute_pay(by_key["juniper-llm-eval"])
    assert hourly["pay_status"] == "variable" and hourly["pay_monthly_inr_min"] is None
    assert hourly["pay_hourly_inr_min"] == 25 * SIM_FX_INR["USD"]
    stated = compute_pay(by_key["obsidian-search"])  # CAD 28/h × 40 h/week
    assert stated["pay_status"] == "listed" and stated["pay_monthly_inr_min"] == round(28 * 40 * 52 / 12 * 64)
    lpa = compute_pay(by_key["starling-junior-ml"])
    assert lpa["pay_monthly_inr_min"] == round(800000 / 12) and lpa["pay_monthly_inr_max"] == round(1000000 / 12)
    funded = compute_pay(by_key["hoshizora-vurp"])
    assert funded["benefits_json"] == {"housing": True, "meals": True, "travel": True, "allowance_inr": 88500}
    assert is_funded_program(by_key["hoshizora-vurp"], 5000)
    remote = compute_pay(by_key["quillfeather-nlp"])
    assert remote["living_cost_basis"].startswith("sim: remote") and remote["pay_ratio"] == 1.4
    assert compute_pay(by_key["solstice-climate"])["pay_ratio"] is None
    assert role_for_canonical_key("sim:quillfeather-nlp:12345").company == "Quillfeather AI"
    assert role_for_canonical_key("legacy:1") is None


def _seed(db, key: str) -> str:
    from hq.db import repo

    role = next(r for r in ROLES if r.key == key)
    city = CITIES[role.city]
    pay = compute_pay(role)
    with tx(db):
        opp_id = repo.insert_opportunity(db, {
            "canonical_key": f"sim:{key}:4242", "company_name": role.company, "title": role.title, "kind": role.kind,
            "city": city.name, "country_iso2": city.country_iso2, "lat": city.lat, "lon": city.lon,
            "work_mode": role.work_mode, "url": f"https://careers.{role.slug}.example/jobs/4242",
            "apply_url": f"https://careers.{role.slug}.example/jobs/4242/apply", "apply_channel": role.channel,
            "apply_email": role.apply_email, "deadline_at": "2099-01-01T00:00:00.000Z", "pay_raw": pay["pay_raw"],
            "pay_status": role.pay.status, "stage": "found"}, is_simulated=True)
        queue.enqueue(db, "parse.job", opportunity_id=opp_id)
    return opp_id


def _worker(**sim_kwargs) -> Worker:
    kwargs = {"duration_scale": 0.01, "fail_rate": 0.0, "bad_draft_rate": 0.0, "seed": 7}
    kwargs.update(sim_kwargs)
    return Worker(sim_kwargs=kwargs, loop_interval=0.02, watch=False, schedule=False)


def _idle(db) -> bool:
    return db.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('queued','leased','running')").fetchone()[0] == 0


def _stage(db, opp_id):
    return db.execute("SELECT stage FROM opportunities WHERE id=?", (opp_id,)).fetchone()[0]


async def test_sim_flow_reaches_applied_with_only_mock_mailbox_writes(team, db, offline):
    with tx(db):
        set_settings(db, {"sim_speed": 4.0})
    opp_id = _seed(db, "quillfeather-nlp")  # clean, email channel
    w = _worker()
    w.startup()
    assert await drive(w, lambda: _stage(db, opp_id) == "applied" and _idle(db), timeout=30), _stage(db, opp_id)
    await w.shutdown()
    assert offline == []
    mails = db.execute("SELECT to_addr, subject, body, application_id FROM mock_mailbox").fetchall()
    assert len(mails) == 1 and mails[0]["to_addr"] == "careers@quillfeather.example"
    assert "[SIMULATED DRAFT" in mails[0]["body"]
    assert db.execute("SELECT COUNT(*) FROM outbound_log").fetchone()[0] == 0
    app = db.execute("SELECT status, submitted_at, submission_ref FROM applications").fetchone()
    assert app["status"] == "submitted" and app["submission_ref"].startswith("mock_mailbox:")
    sent = db.execute("SELECT data_json FROM events WHERE type='mail.mock_sent'").fetchone()
    assert json.loads(sent[0])["to"] == "careers@quillfeather.example"
    stages = [json.loads(r[0])["to"] for r in db.execute("SELECT data_json FROM events WHERE type='opp.stage'")]
    assert stages == ["verified", "drafted", "checked", "applied"]
    handoffs = {(json.loads(r[0])["from_agent"], json.loads(r[0])["to_agent"])
                for r in db.execute("SELECT data_json FROM events WHERE type='task.handoff'")}
    assert {("scout", "verifier"), ("verifier", "writer"), ("writer", "factchecker"), ("factchecker", "reviewer"),
            ("reviewer", "resume"), ("resume", "applicant"), ("applicant", "followup")} <= handoffs
    runs = db.execute("SELECT agent_id, model_id, tok_s, cost_usd, status FROM agent_runs").fetchall()
    assert all(r["status"] == "succeeded" and r["model_id"].startswith("sim:") for r in runs)
    reviewer = next(r for r in runs if r["agent_id"] == "reviewer")
    assert reviewer["tok_s"] is None and reviewer["cost_usd"] > 0
    assert all(40 <= r["tok_s"] <= 370 for r in runs if r["agent_id"] in ("verifier", "writer", "factchecker"))
    docs = db.execute("SELECT kind, author_model FROM documents ORDER BY created_at").fetchall()
    assert [d["kind"] for d in docs] == ["cover_letter", "resume_pdf"]
    # fact-checker model differs from the writer model (independence)
    assert db.execute("SELECT model_id FROM agent_runs WHERE agent_id='factchecker'").fetchone()[0] != docs[0][
        "author_model"]


async def test_fact_gate_loop_redrafts_then_passes(team, db, offline):
    with tx(db):
        set_settings(db, {"sim_speed": 4.0})
    opp_id = _seed(db, "kestrel-cv")
    w = _worker(bad_draft_rate=1.0)
    w.startup()
    assert await drive(w, lambda: _stage(db, opp_id) == "applied", timeout=30)
    await w.shutdown()
    versions = [r[0] for r in db.execute("SELECT version FROM documents WHERE kind='cover_letter' ORDER BY version")]
    assert versions == [1, 2]
    gate = db.execute("SELECT passed, details_json FROM gate_results WHERE gate='fact_rules' ORDER BY ts").fetchall()
    assert gate[0]["passed"] == 0 and "BANNED_CLAIM" in gate[0]["details_json"] and gate[-1]["passed"] == 1
    sent = db.execute("SELECT body FROM mock_mailbox").fetchone()[0]
    assert "deployed" not in sent


async def test_manual_channel_creates_submit_form_pack(team, db, offline):
    with tx(db):
        set_settings(db, {"sim_speed": 4.0})
    opp_id = _seed(db, "nimbus-ml-intern")  # ATS form
    w = _worker()
    w.startup()
    assert await drive(w, lambda: db.execute("SELECT COUNT(*) FROM needs_prerit WHERE kind='submit_form'").fetchone()[0]
                       == 1, timeout=30)
    await w.shutdown()
    need = db.execute("SELECT * FROM needs_prerit WHERE kind='submit_form'").fetchone()
    answers = json.loads(need["answers_json"])
    assert any(a["label"] == "Full name" and a["value"] == "Prerit Sangwan" for a in answers)
    assert need["est_minutes"] == 2 and need["direct_url"].endswith(".example/jobs/4242/apply")
    assert _stage(db, opp_id) == "checked"
    assert db.execute("SELECT COUNT(*) FROM mock_mailbox").fetchone()[0] == 0


@pytest.mark.parametrize("key,reason", [
    ("marlowe-bioml", "ineligible: 'Open to 2026 graduates only'"),
    ("skillforge-virtual", "scam:"),
    ("saffron-bi", "pay below living cost"),
    ("harbor-civic-data", "unpaid"),
])
async def test_traps_get_filtered_with_reason(team, db, offline, key, reason):
    with tx(db):
        set_settings(db, {"sim_speed": 4.0})
    opp_id = _seed(db, key)
    w = _worker()
    w.startup()
    assert await drive(w, lambda: _stage(db, opp_id) == "filtered", timeout=20)
    await w.shutdown()
    got = db.execute("SELECT stage_reason FROM opportunities WHERE id=?", (opp_id,)).fetchone()[0]
    assert got.startswith(reason) or reason in got


async def test_interview_reply_is_notify_only(team, db, offline):
    """Applied sim items get replies; an interview creates an alert need and no outbound anything."""
    from hq.adapters.sim import SimAdapter

    with tx(db):
        set_settings(db, {"sim_speed": 4.0})
    interview_key = None
    for n in range(500):  # find a seeded opp id that classifies as interview and will reply
        candidate = f"OPP{n:04d}"
        if SimAdapter._classification(candidate) == "interview" and SimAdapter(reply_rate=1.0)._reply_plan(
                candidate, 4.0)[0]:
            interview_key = candidate
            break
    assert interview_key
    opp_id = _seed(db, "quillfeather-nlp")
    with tx(db):
        db.execute("UPDATE opportunities SET id=? WHERE id=?", (interview_key, opp_id))
        db.execute("UPDATE tasks SET opportunity_id=? WHERE opportunity_id=?", (interview_key, opp_id))
    w = _worker(reply_rate=1.0, reply_delay_s=(0.0, 0.0))
    w.startup()
    assert await drive(w, lambda: _stage(db, interview_key) == "applied", timeout=30)
    with tx(db):
        queue.enqueue(db, "inbox.poll", type_="scheduled")
    assert await drive(w, lambda: _stage(db, interview_key) == "interview", timeout=20)
    await w.shutdown()
    need = db.execute("SELECT kind, priority FROM needs_prerit WHERE kind='interview'").fetchone()
    assert need and need["priority"] >= 90
    thread = db.execute("SELECT classification, notify_only_lock FROM email_threads").fetchone()
    assert thread["classification"] == "interview" and thread["notify_only_lock"] == 1
    assert db.execute("SELECT COUNT(*) FROM events WHERE type='notification' AND level='alert'").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM mock_mailbox").fetchone()[0] == 1  # only the application itself
    assert db.execute("SELECT COUNT(*) FROM tasks WHERE capability LIKE 'reply.%'").fetchone()[0] == 0


async def test_scout_discovers_and_respects_active_cap(team, db, offline, monkeypatch):
    import hq.adapters.sim as sim_mod

    w = _worker()
    w.startup()
    with tx(db):
        tid = queue.enqueue(db, "discover.ats", type_="scheduled")
    assert await drive(w, lambda: db.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0]
                       == "succeeded", timeout=10)
    created = db.execute("SELECT COUNT(*) FROM events WHERE type='opp.created'").fetchone()[0]
    assert 1 <= created <= 2
    opp = db.execute("SELECT * FROM opportunities").fetchone()
    assert opp["is_simulated"] == 1 and opp["canonical_key"].startswith("sim:") and ".example" in opp["url"]
    assert opp["pay_raw"] and opp["pay_monthly_inr_min"] is None  # INR conversion happens in verify.pay
    monkeypatch.setattr(sim_mod, "MAX_ACTIVE_SIM_OPPS", 0)
    with tx(db):
        tid2 = queue.enqueue(db, "discover.ats", type_="scheduled")
    assert await drive(w, lambda: db.execute("SELECT status FROM tasks WHERE id=?", (tid2,)).fetchone()[0]
                       == "succeeded", timeout=10)
    await w.shutdown()
    result = json.loads(db.execute("SELECT result_json FROM tasks WHERE id=?", (tid2,)).fetchone()[0])
    assert result["created"] == 0 and result["reason"] == "pipeline full"
