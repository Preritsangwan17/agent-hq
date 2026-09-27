"""Phase (c) building blocks: net guard, polite fetcher, sources, title filter, rules-first parse, eligibility rules,
scam lexicon, answers, the outbound guard, and the phase-(c) API routes."""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from conftest import MUTATE

from hq.db.conn import tx
from hq.db.seed import set_settings
from hq.models.benchmark.tasks._fixtures import job_text
from hq.pipeline.apply import guard
from hq.pipeline.apply.answers import resolve
from hq.pipeline.discover import sources as src_mod
from hq.pipeline.discover.fetch import Fetcher, FetchBlocked
from hq.pipeline.discover.parse import job_quotes, rules_parse
from hq.pipeline.discover.titles import classify_title
from hq.pipeline.verify.eligibility_rules import check as rules_check
from hq.pipeline.verify.scam import check_scam
from hq.util import netguard


# ── net guard ─────────────────────────────────────────────────────────────────────────────────────────
def test_netguard_allows_only_gets_to_third_parties_and_never_manual_lane():
    netguard.check("GET", "https://boards-api.greenhouse.io/v1/boards/x/jobs")
    netguard.check("POST", "http://127.0.0.1:8799/jobs/1/apply")           # loopback (mock ATS)
    with pytest.raises(netguard.NetGuardError):
        netguard.check("POST", "https://boards.greenhouse.io/x/jobs/1")
    for url in ("https://www.linkedin.com/jobs/view/1", "https://internshala.com/internship/detail/x"):
        with pytest.raises(netguard.NetGuardError, match="manual-lane"):
            netguard.check("GET", url)
    with pytest.raises(netguard.NetGuardError):                              # dry run: even Gmail POSTs are blocked
        netguard.check("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
    netguard.check("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", mode="live")


def test_forced_dry_run_is_the_default(monkeypatch):
    monkeypatch.delenv("HQ_FORCE_DRY_RUN", raising=False)
    monkeypatch.setenv("HQ_MODE", "live")
    assert netguard.current_mode() == "dry_run"


# ── fetcher ───────────────────────────────────────────────────────────────────────────────────────────
class Site:
    def __init__(self, robots: str = "User-agent: *\nAllow: /\n"):
        self.robots = robots
        self.seen: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.seen.append(req)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=self.robots)
        if req.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, text="<h1>Intern</h1>", headers={"ETag": '"v1"'})


async def _nosleep(_: float) -> None:
    return None


async def test_fetcher_honours_robots_caches_and_logs(db):
    site = Site()
    sleeps: list[float] = []

    async def sleep(s: float) -> None:
        sleeps.append(s)

    f = Fetcher(db, transport=httpx.MockTransport(site), sleep=sleep, clock=lambda: 1000.0)
    first = await f.get("https://jobs.example.org/a", kind="html")
    second = await f.get("https://jobs.example.org/a", kind="html")
    assert first.status == 200 and not first.from_cache and second.from_cache and second.text == first.text
    assert sleeps and min(sleeps) >= 4.9                                # ≥ 5 s between HTML requests to one domain
    assert all(r.headers["user-agent"].startswith("AgentHQ/") for r in site.seen)
    assert {r.method for r in site.seen} == {"GET"}
    logged = [dict(r) for r in db.execute("SELECT method, domain, from_cache FROM fetch_log ORDER BY id")]
    assert logged and all(r["method"] == "GET" for r in logged) and logged[-1]["from_cache"] == 1


async def test_fetcher_refuses_robots_disallow_manual_lane_and_offline(db, monkeypatch):
    site = Site(robots="User-agent: *\nDisallow: /private\n")
    f = Fetcher(db, transport=httpx.MockTransport(site), sleep=_nosleep)
    with pytest.raises(FetchBlocked, match="robots"):
        await f.get("https://jobs.example.org/private/1")
    n = len(site.seen)
    with pytest.raises(FetchBlocked, match="manual-lane"):
        await f.get("https://www.naukri.com/job-listings-1")
    assert len(site.seen) == n                                           # never even tried
    monkeypatch.setenv("HQ_OFFLINE", "1")
    with pytest.raises(FetchBlocked, match="offline"):
        await Fetcher(db, sleep=_nosleep).get("https://jobs.example.org/a")
    reasons = {r["blocked_reason"] for r in db.execute("SELECT blocked_reason FROM fetch_log WHERE blocked_reason IS NOT NULL")}
    assert any("robots" in r for r in reasons) and "manual lane" in reasons


# ── sources ───────────────────────────────────────────────────────────────────────────────────────────
def test_sources_seed_and_breaker(db):
    rows = {r["id"]: dict(r) for r in db.execute("SELECT * FROM sources")}
    assert rows["greenhouse:anthropic"]["enabled"] == 1 and rows["greenhouse:anthropic"]["tos_status"] == "allowed"
    progs = [r for r in rows.values() if r["kind"] == "program_page"]
    assert progs and all(r["enabled"] == 0 and r["tos_status"] == "unreviewed" for r in progs)
    assert rows["greenhouse:mocktech"]["enabled"] == 0                  # local mock ATS: off by default
    with tx(db):
        for _ in range(5):
            src_mod.record_poll(db, "greenhouse:anthropic", ok=False, error="HTTP 500")
    r = db.execute("SELECT consecutive_errors, disabled_until FROM sources WHERE id='greenhouse:anthropic'").fetchone()
    assert r["consecutive_errors"] == 5 and r["disabled_until"]
    assert "greenhouse:anthropic" not in {s["id"] for s in src_mod.due_sources(db, ("greenhouse",), limit=100)}


# ── titles / parse / eligibility / scam ───────────────────────────────────────────────────────────────
def test_title_filter_matches_all_gold_titles():
    from pathlib import Path

    gold = [json.loads(line) for line in (Path(__file__).parents[1] / "fixtures" / "titles_gold.jsonl").open()]
    wrong = [g["title"] for g in gold if classify_title(g["title"]).target != g["target"]]
    assert len(gold) == 189 and not wrong, wrong
    # "uncertain" titles go to the title model; none of them is a gold target, so a failed model call loses nothing
    assert not [g for g in gold if classify_title(g["title"]).uncertain and g["target"]]


def test_rules_parse_finds_pay_and_exact_quotes():
    text = ("About the role: you will build data pipelines in Python.\nRequirements:\n- Currently pursuing a B.Tech in "
            "Computer Science.\n- Familiarity with pandas and scikit-learn.\nStipend: ₹25,000 per month for 6 months. "
            "The team ships recommendation features used by millions of readers every single day.")
    p = rules_parse(text, company="X", title="ML Intern")
    assert p.pay_raw and "25,000" in p.pay_raw
    assert all(q in text for q in job_quotes(p))
    assert rules_parse("5 years of experience with 3 engineers in 2 teams " * 5).pay_raw is None  # numbers ≠ pay


def test_eligibility_rules_catch_every_ineligible_gold_posting_without_false_hits():
    from pathlib import Path

    gold = [json.loads(line) for line in (Path(__file__).parents[1] / "fixtures" / "eligibility_gold.jsonl").open()]
    for g in gold:
        r = rules_check(job_text(g["fixture"]), start=date(2026, 10, 1))
        if g["verdict"] == "ineligible":
            assert r.ineligible, g["fixture"]
        else:
            assert not r.ineligible, (g["fixture"], [h.detail for h in r.hits])


def test_scam_lexicon_flags_fees_and_passes_real_postings():
    bad = check_scam(company="Fast Track", text="Guaranteed internship with certificate. A registration fee of "
                                                "Rs. 2,999 is payable to confirm your seat.")
    assert bad.verdict in ("scam", "suspicious") and bad.signals
    ok = check_scam(company="Fakeco", text=job_text("jobs/linkedin_4469130739.txt"))
    assert ok.verdict == "clean"


# ── answers ───────────────────────────────────────────────────────────────────────────────────────────
def test_answers_use_only_confirmed_values_and_never_sensitive_ids(db):
    from hq.profile.fields import update_field

    assert resolve(db, "Email").value == "sangwanprerit40@gmail.com"
    assert resolve(db, "Phone number").status == "needs_prerit"          # unconfirmed → left for Prerit
    with tx(db):
        update_field(db, "phone", "+91 90000 11111")
    assert resolve(db, "Phone number").value == "+91 90000 11111"
    for q in ("Aadhaar number", "PAN card number", "Passport number"):
        a = resolve(db, q)
        assert a.status == "never" and not a.value, q
    assert resolve(db, "Gender", options=["Male", "Female", "Prefer not to say"]).value == "Male"
    assert resolve(db, "Gender", options=["Female", "Prefer not to say"]).status == "needs_prerit"
    assert resolve(db, "Gender").value == "Male"
    assert resolve(db, "Race", options=["Prefer not to say"]).value == "Prefer not to say"
    assert resolve(db, "Resume/CV", qtype="file").status == "file"


# ── outbound guard ────────────────────────────────────────────────────────────────────────────────────
def _opp_app(db, email="careers@fakeco.ai", quote="Send your CV to careers@fakeco.ai"):
    from hq.db import repo

    with tx(db):
        oid = repo.insert_opportunity(db, {"canonical_key": f"t:{email}", "company_name": "Fakeco", "title": "ML Intern",
                                           "url": "https://fakeco.ai/careers/ml", "apply_email": email,
                                           "apply_email_quote": quote, "stage": "checked"}, is_simulated=False)
        db.execute("INSERT INTO applications(id, opportunity_id, channel, status, mode, created_at, updated_at) "
                   "VALUES (?, ?, 'email', 'queued', 'dry_run', '2026-01-01', '2026-01-01')", (f"app-{oid}", oid))
    return oid, f"app-{oid}"


def test_guard_dry_run_writes_only_the_mock_mailbox_and_is_idempotent(db):
    _, app = _opp_app(db)
    sha = guard.approval_sha("Dear Hiring Team, …", None, None)
    r1 = guard.send_email(db, application_id=app, to_addr="careers@fakeco.ai", subject="Application", body="Hi",
                          attachments=[], content_sha=sha)
    r2 = guard.send_email(db, application_id=app, to_addr="careers@fakeco.ai", subject="Application", body="Hi",
                          attachments=[], content_sha=sha)
    assert r1.status == "sent" and r1.mode == "dry_run" and r2.status == "duplicate" and r2.message_id == r1.message_id
    assert r1.message_id == guard.message_id_for(app, sha)
    assert db.execute("SELECT COUNT(*) FROM mock_mailbox").fetchone()[0] == 1


def test_guard_blocks_wrong_recipient_unapproved_text_and_caps(db):
    _, app = _opp_app(db, email="jobs@gmail.com", quote="mail jobs@gmail.com")
    with pytest.raises(guard.GuardBlocked) as e:
        guard.send_email(db, application_id=app, to_addr="jobs@gmail.com", subject="s", body="b", attachments=[],
                         content_sha="x")
    assert e.value.kind == "recipient"
    _, app2 = _opp_app(db, email="hr@fakeco.ai", quote="write to hr@fakeco.ai")
    with tx(db):
        set_settings(db, {"autonomy": "approve_first"})
    with pytest.raises(guard.GuardBlocked) as e:
        guard.send_email(db, application_id=app2, to_addr="hr@fakeco.ai", subject="s", body="b", attachments=[],
                         content_sha="not-approved")
    assert e.value.kind == "approval"
    with tx(db):
        set_settings(db, {"autonomy": "auto", "email_daily_cap": 0})
    with pytest.raises(guard.GuardBlocked) as e:
        guard.send_email(db, application_id=app2, to_addr="hr@fakeco.ai", subject="s", body="b", attachments=[],
                         content_sha="x")
    assert e.value.kind == "cap"
    assert db.execute("SELECT COUNT(*) FROM mock_mailbox").fetchone()[0] == 0


# ── API ───────────────────────────────────────────────────────────────────────────────────────────────
def test_manual_paste_route(authed, db):
    r = authed.post("/api/opportunities/manual", json={"url": "https://www.linkedin.com/jobs/view/123"}, headers=MUTATE)
    assert r.status_code == 422 and "manual-lane" in r.json()["error"]
    body = {"url": "https://www.linkedin.com/jobs/view/123", "company": "Fakeco", "title": "ML Intern",
            "text": "Fakeco is hiring an ML intern. Requirements: pursuing a B.Tech. Stipend ₹30,000 per month."}
    r = authed.post("/api/opportunities/manual", json=body, headers=MUTATE)
    assert r.status_code == 201, r.text
    opp = r.json()
    row = db.execute("SELECT * FROM opportunities WHERE id=?", (opp["id"],)).fetchone()
    assert row["automation"] == "manual_lane" and row["is_simulated"] == 0 and row["description_path"]
    assert db.execute("SELECT 1 FROM tasks WHERE opportunity_id=? AND capability='parse.job'", (opp["id"],)).fetchone()
    assert authed.post("/api/opportunities/manual", json=body, headers=MUTATE).status_code == 409


def test_sources_routes_require_tos_review_before_enabling(authed):
    items = authed.get("/api/sources").json()["items"]
    prog = next(s for s in items if s["kind"] == "program_page")
    r = authed.patch(f"/api/sources/{prog['id']}", json={"enabled": True}, headers=MUTATE)
    assert r.status_code == 409
    r = authed.patch(f"/api/sources/{prog['id']}", json={"tos_status": "allowed"}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["tos_reviewed_at"]
    r = authed.patch(f"/api/sources/{prog['id']}", json={"enabled": True}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert "linkedin.com" in authed.get("/api/sources").json()["manual_lane"]
    audit = authed.get("/api/audit", params={"action": "source.update"}).json()["items"]
    assert len(audit) >= 2


def test_files_route_serves_only_artifacts(authed, db, hq_env):
    from hq import settings as paths

    art = paths.ARTIFACTS / "applications" / "o1" / "v1"
    art.mkdir(parents=True)
    (art / "r.pdf").write_bytes(b"%PDF-1.4 test")
    outside = hq_env.root / "secret.txt"
    outside.write_text("nope")
    with tx(db):
        db.execute("INSERT INTO documents(id, kind, version, status, content_path, created_at) VALUES "
                   "('d1','resume_pdf',1,'passed',?, '2026-01-01'), ('d2','resume_pdf',1,'passed',?, '2026-01-01')",
                   (str(art / "r.pdf"), str(outside)))
    assert authed.get("/api/documents/d1/file").content.startswith(b"%PDF")
    assert authed.get("/api/documents/d2/file").status_code == 404


def test_verdicts_csv_has_the_audit_columns(authed):
    r = authed.get("/api/audit/verdicts.csv")
    assert r.status_code == 200 and r.text.splitlines()[0].startswith("opportunity_id,company,title")
