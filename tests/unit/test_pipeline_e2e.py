"""Phase (c) end to end in DRY RUN with fakes at the edges only: a fake Greenhouse board behind an httpx
MockTransport, fake local models behind the router and a fake Claude. Everything in between is the real code:
discovery, rules-first parsing, eligibility rules, scam/pay checks, fit, the Writer, all fact-check layers, the
quality gate, the résumé builder and the Applicant's manual pack. Also proves: nothing but GETs leaves the Mac, the
phone number never reaches a model, and unconfirmed profile values are left for Prerit."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import drive

from hq.adapters.base import Services
from hq.db.conn import tx
from hq.db.seed import set_settings
from hq.llm.claude import ClaudeResult
from hq.llm.router import LLMResult
from hq.pipeline.discover.fetch import Fetcher
from hq.worker import queue
from hq.worker.orchestrator import Worker

sys.path.insert(0, str(Path(__file__).parent))
from _letter_fixture import letter  # noqa: E402

PHONE = "+91 98111 22334"
WRITER, CHECKER = "local/qwen-writer-7b", "local/llama-checker-8b"

JOBS = [
    {"id": 101, "title": "Machine Learning Intern", "location": {"name": "Bengaluru, India"},
     "absolute_url": "https://boards.greenhouse.io/fakeco/jobs/101", "updated_at": "2026-09-20T10:00:00Z",
     "content": "<p>Fakeco builds recommendation systems for readers.</p><h3>What you will do</h3><ul>"
                "<li>As a Machine Learning Intern you will work on collaborative filtering and data pipelines in "
                "Python with pandas and scikit-learn.</li></ul><h3>Requirements</h3><ul><li>Currently pursuing a "
                "Bachelor's degree in Computer Science or a related field.</li><li>Familiarity with Python and "
                "scikit-learn.</li></ul><p>Stipend: ₹60,000 per month. Duration: 6 months.</p>"},
    {"id": 102, "title": "Senior Staff Software Engineer", "location": {"name": "Bengaluru, India"},
     "absolute_url": "https://boards.greenhouse.io/fakeco/jobs/102", "updated_at": "2026-09-20T10:00:00Z",
     "content": "<p>10+ years of experience.</p>"},
    {"id": 103, "title": "Data Science Intern", "location": {"name": "Pune, India"},
     "absolute_url": "https://boards.greenhouse.io/fakeco/jobs/103", "updated_at": "2026-09-20T10:00:00Z",
     "content": "<p>Work with pandas on churn data.</p><p>Eligibility: Graduation Year: 2026 pass-out candidates "
                "only.</p><p>Stipend: ₹30,000 per month.</p>"},
    {"id": 104, "title": "AI Intern", "location": {"name": "Remote, India"},
     "absolute_url": "https://boards.greenhouse.io/fakeco/jobs/104", "updated_at": "2026-09-20T10:00:00Z",
     "content": "<p>Guaranteed internship with certificate. A registration fee of Rs. 2,999 is payable to confirm "
                "your seat. Stipend: ₹10,000 per month.</p>"},
]
QUESTIONS = [{"label": "First Name", "required": True, "fields": [{"name": "first_name", "type": "input_text"}]},
             {"label": "Email", "required": True, "fields": [{"name": "email", "type": "input_text"}]},
             {"label": "Phone", "required": True, "fields": [{"name": "phone", "type": "input_text"}]},
             {"label": "Resume/CV", "required": True, "fields": [{"name": "resume", "type": "input_file"}]},
             {"label": "Are you legally authorized to work in India?", "required": True,
              "fields": [{"name": "q1", "type": "multi_value_single_select",
                          "values": [{"label": "Yes", "value": 1}, {"label": "No", "value": 0}]}]},
             {"label": "Aadhaar number", "required": False, "fields": [{"name": "q2", "type": "input_text"}]}]


class Board:
    """The fake third-party internet: a Greenhouse board API + posting pages. Records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.host == "boards-api.greenhouse.io" and path == "/v1/boards/fakeco/jobs":
            return httpx.Response(200, json={"jobs": JOBS})
        m = re.fullmatch(r"/v1/boards/fakeco/jobs/(\d+)", path)
        if request.url.host == "boards-api.greenhouse.io" and m:
            job = next(j for j in JOBS if j["id"] == int(m.group(1)))
            return httpx.Response(200, json={**job, "questions": QUESTIONS})
        m = re.fullmatch(r"/fakeco/jobs/(\d+)", path)
        if request.url.host == "boards.greenhouse.io" and m:
            job = next((j for j in JOBS if j["id"] == int(m.group(1))), None)
            if job:
                return httpx.Response(200, html=f"<html><body><h1>{job['title']}</h1>{job['content']}"
                                                f"<a href='#app'>Apply for this job</a></body></html>")
        return httpx.Response(404, text="not found")


class FakeRouter:
    """Stands in for the local-model router: one canned, schema-valid answer per role."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def route(self, role: str, messages: list[dict[str, str]], schema: Any, **kw: Any) -> LLMResult:
        self.calls.append({"role": role, "messages": messages, **{k: kw.get(k) for k in ("lineage", "exclude_models")}})
        text = "\n".join(m["content"] for m in messages)
        if role == "eligibility":
            quote = "Currently pursuing a Bachelor's degree in Computer Science or a related field."
            return LLMResult(WRITER, {"verdict": "eligible", "requirements": [{"quote": quote, "met": True}],
                                      "skill_gaps": []})
        if role == "writer":
            out = letter("Fakeco")
            jid = next((m.group(1) for m in re.finditer(r"\b(J\d+)\b[^\n]*collaborative filtering", text)), "J1")
            for s in out["sentences"]:
                s["job_quote_ids"] = [jid] if s["job_quote_ids"] else []
            return LLMResult(WRITER, out, prompt_tokens=900, completion_tokens=400, tok_s=42.0)
        if role == "fact_checker":
            n = len(re.findall(r"SENTENCE:", text)) or 20
            return LLMResult(CHECKER, {"results": [{"i": i, "verdict": "supported"} for i in range(n)]})
        if role == "summarizer":
            return LLMResult(CHECKER, {"score": 4, "reasons": "names the organisation and the work"})
        raise AssertionError(f"unexpected role {role}")


class FakeClaude:
    reason = "fake"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def available(self) -> bool:
        return True

    async def run(self, prompt: str, *, schema: dict, system_prompt: str, model: str, max_budget_usd: float,
                  **_: Any) -> ClaudeResult:
        self.prompts.append(system_prompt + "\n" + prompt)
        if "sentences" in (schema.get("properties") or {}):  # polish
            out = letter("Fakeco")
            jid = next((m.group(1) for m in re.finditer(r"\b(J\d+)\b[^\n]*collaborative filtering", prompt)), "J1")
            for s in out["sentences"]:
                s["job_quote_ids"] = [jid] if s["job_quote_ids"] else []
        else:
            n = len(re.findall(r"SENTENCE:", prompt))
            out = {"results": [{"i": i, "verdict": "supported"} for i in range(n)]}
        return ClaudeResult(out, 0.02, 1200, 300, 0, 50.0, model, "success")


async def _nosleep(_: float) -> None:
    return None


@pytest.fixture
def pipeline(db, team, monkeypatch):
    from hq.profile.fields import update_field

    with tx(db):
        set_settings(db, {"sim_enabled": False, "autonomy": "auto"})
        db.execute("UPDATE sources SET enabled=0")
        db.execute("INSERT INTO sources(id, name, kind, config_json, automation, tos_status, enabled, added_by, "
                   "created_at, poll_interval_min) VALUES ('greenhouse:fakeco', 'Greenhouse · fakeco', 'greenhouse', "
                   "'{\"slug\": \"fakeco\"}', 'discover_only', 'allowed', 1, 'test', '2026-01-01T00:00:00Z', 360)")
        db.execute("INSERT INTO benchmarks(id, model_id, suite_version, task, accuracy, created_at) VALUES "
                   "('b1', ?, 'v1', 'eligibility', 0.95, '2026-01-01T00:00:00Z')", (WRITER,))
        update_field(db, "phone", PHONE)
    board = Board()
    router, claude = FakeRouter(), FakeClaude()
    fetcher = Fetcher(db, transport=httpx.MockTransport(board), sleep=_nosleep)
    w = Worker(conn=db, agents_dir=team, loop_interval=0.01, watch=False, schedule=False,
               services=Services(router=router, claude=claude, fetcher=fetcher))
    return w, board, router, claude


def _stage(db, title: str) -> tuple[str | None, str | None]:
    r = db.execute("SELECT stage, stage_reason FROM opportunities WHERE title=?", (title,)).fetchone()
    return (r["stage"], r["stage_reason"]) if r else (None, None)


async def test_dry_run_pipeline_end_to_end(db, pipeline):
    w, board, router, claude = pipeline
    w.startup()
    with tx(db):
        queue.enqueue(db, "discover.ats", type_="scheduled")

    def done() -> bool:
        return db.execute("SELECT 1 FROM needs_prerit WHERE kind='submit_form'").fetchone() is not None

    ok = await drive(w, done, timeout=90)
    failed = [dict(r) for r in db.execute("SELECT capability, last_error FROM tasks WHERE status IN ('failed','dead')")]
    await w.shutdown()
    assert ok, f"pipeline did not reach a pack; failed tasks: {failed}; stages: " + str(
        [dict(r) for r in db.execute("SELECT title, stage, stage_reason FROM opportunities")])

    # discovery + filters
    titles = {r["title"] for r in db.execute("SELECT title FROM opportunities")}
    assert "Senior Staff Software Engineer" not in titles          # dropped by the deterministic title filter
    stage, reason = _stage(db, "Data Science Intern")
    assert stage == "filtered" and "neligible" in (reason or "")   # 2026 pass-outs only (rules, no model needed)
    stage, reason = _stage(db, "AI Intern")
    assert stage == "filtered"                                      # registration fee → scam/fee filter
    stale = db.execute("SELECT COUNT(*) FROM needs_prerit n JOIN opportunities o ON o.id=n.opportunity_id "
                       "WHERE o.stage='filtered' AND n.status='open'").fetchone()[0]
    assert stale == 0                                               # no keep/drop left open for a filtered role

    # the good one went all the way to a pack
    opp = db.execute("SELECT * FROM opportunities WHERE title='Machine Learning Intern'").fetchone()
    assert opp["stage"] == "checked" and opp["pay_monthly_inr_min"] == 60000 and opp["eligibility_status"] == "eligible"
    doc = db.execute("SELECT * FROM documents WHERE opportunity_id=? AND kind='cover_letter' ORDER BY version DESC",
                     (opp["id"],)).fetchone()
    assert doc["status"] == "passed" and "Fakeco" in doc["content_text"] and doc["content_text"].startswith("Dear Hiring Team,")
    layers = {r["layer"] for r in db.execute("SELECT layer FROM fact_checks WHERE document_id=?", (doc["id"],))}
    assert {"local", "signoff"} <= layers
    gates = {r["gate"]: r["passed"] for r in db.execute(
        "SELECT gate, passed FROM gate_results WHERE document_id=?", (doc["id"],))}
    assert all(gates.get(g) for g in ("fact.deterministic", "fact.local", "quality", "fact.signoff")), gates
    resume = db.execute("SELECT * FROM documents WHERE opportunity_id=? AND kind='resume_pdf'", (opp["id"],)).fetchone()
    assert resume and Path(resume["content_path"]).read_bytes()[:4] == b"%PDF"

    need = db.execute("SELECT * FROM needs_prerit WHERE kind='submit_form'").fetchone()
    answers = {a["label"]: a for a in json.loads(need["answers_json"])}
    assert answers["Email"]["status"] == "filled" and answers["Phone"]["value"] == PHONE  # confirmed → filled
    assert answers["Aadhaar number"]["status"] == "never" and answers["Aadhaar number"]["copy"] is False
    assert need["direct_url"] == "https://boards.greenhouse.io/fakeco/jobs/101"
    app = db.execute("SELECT * FROM applications WHERE opportunity_id=?", (opp["id"],)).fetchone()
    assert app["status"] == "needs_prerit" and app["pack_need_id"] == need["id"] and app["mode"] == "dry_run"

    # independence: the checker is told the letter's lineage (so the router can refuse the writer's model)
    checks = [c for c in router.calls if c["role"] == "fact_checker"]
    assert checks and all(WRITER in (c["lineage"] or ()) for c in checks)
    assert claude.prompts, "Claude sign-off never ran"

    # safety: GET-only to third parties, phone never sent to a model or Claude, nothing mailed
    assert board.requests and {r.method for r in board.requests} == {"GET"}
    assert set(r["method"] for r in db.execute("SELECT method FROM fetch_log")) <= {"GET", "HEAD"}
    everything_sent = json.dumps([c["messages"] for c in router.calls]) + "\n".join(claude.prompts)
    assert PHONE not in everything_sent and "98111" not in everything_sent
    assert db.execute("SELECT COUNT(*) FROM mock_mailbox").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM outbound_log").fetchone()[0] == 0


async def test_unconfirmed_phone_is_left_for_prerit(db, pipeline):
    w, board, router, claude = pipeline
    with tx(db):
        db.execute("UPDATE profile_fields SET confirmed_by_prerit=0 WHERE key='phone'")
    w.startup()
    with tx(db):
        queue.enqueue(db, "discover.ats", type_="scheduled")
    ok = await drive(w, lambda: db.execute("SELECT 1 FROM needs_prerit WHERE kind='submit_form'").fetchone() is not None,
                     timeout=90)
    await w.shutdown()
    assert ok
    need = db.execute("SELECT * FROM needs_prerit WHERE kind='submit_form'").fetchone()
    answers = {a["label"]: a for a in json.loads(need["answers_json"])}
    assert answers["Phone"]["status"] == "needs_prerit" and PHONE not in need["answers_json"]
    assert "Phone" in json.loads(need["payload_json"])["missing"]
    assert "Needs you" in need["instructions_md"]


def _need(db, kind: str):
    return db.execute("SELECT * FROM needs_prerit WHERE kind=? ORDER BY created_at DESC", (kind,)).fetchone()


async def test_approve_first_binds_approval_to_the_exact_letter_and_resume(db, pipeline, authed):
    from conftest import MUTATE

    w, board, router, claude = pipeline
    with tx(db):
        set_settings(db, {"autonomy": "approve_first"})
    w.settings["autonomy"] = "approve_first"
    w.startup()
    with tx(db):
        queue.enqueue(db, "discover.ats", type_="scheduled")
    assert await drive(w, lambda: _need(db, "approve") is not None, timeout=90)
    need = _need(db, "approve")
    payload = json.loads(need["payload_json"])
    assert payload["route"] == "pack" and len(payload["sha256"]) == 64
    assert "Dear Hiring Team," in need["instructions_md"]          # the preview shows the exact letter
    await drive(w, lambda: False, timeout=0.3)
    assert _need(db, "submit_form") is None                         # nothing moves until Prerit approves
    r = authed.patch(f"/api/needs/{need['id']}", json={"status": "done"}, headers=MUTATE)
    assert r.status_code == 200, r.text
    app = db.execute("SELECT * FROM applications WHERE id=?", (need["application_id"],)).fetchone()
    assert app["approval_sha256"] == payload["sha256"] and app["approved_by"] == "prerit"
    assert await drive(w, lambda: _need(db, "submit_form") is not None, timeout=60)
    await w.shutdown()


async def test_unknown_pay_waits_for_a_keep_or_drop_decision(db, pipeline, authed, monkeypatch):
    from conftest import MUTATE

    mod = sys.modules[__name__]
    no_pay = dict(JOBS[0], content=JOBS[0]["content"].replace("<p>Stipend: ₹60,000 per month. Duration: 6 months.</p>", ""))
    monkeypatch.setattr(mod, "JOBS", [no_pay])
    w, board, router, claude = pipeline
    w.startup()
    with tx(db):
        queue.enqueue(db, "discover.ats", type_="scheduled")
    assert await drive(w, lambda: _need(db, "decision") is not None, timeout=60)
    need = _need(db, "decision")
    assert json.loads(need["payload_json"])["decision"] == "unknown_pay"
    await drive(w, lambda: False, timeout=0.3)
    assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0   # held: no draft while undecided
    bad = authed.patch(f"/api/needs/{need['id']}", json={"status": "done", "choice": "maybe"}, headers=MUTATE)
    assert bad.status_code == 422
    r = authed.patch(f"/api/needs/{need['id']}", json={"status": "done", "choice": "keep"}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["payload"]["choice"] == "keep"
    assert await drive(w, lambda: db.execute("SELECT 1 FROM documents WHERE kind='cover_letter'").fetchone() is not None,
                       timeout=60)
    await w.shutdown()


async def test_dropping_a_decision_filters_the_role(db, pipeline, authed, monkeypatch):
    from conftest import MUTATE

    mod = sys.modules[__name__]
    no_pay = dict(JOBS[0], content=JOBS[0]["content"].replace("<p>Stipend: ₹60,000 per month. Duration: 6 months.</p>", ""))
    monkeypatch.setattr(mod, "JOBS", [no_pay])
    w, *_ = pipeline
    w.startup()
    with tx(db):
        queue.enqueue(db, "discover.ats", type_="scheduled")
    assert await drive(w, lambda: _need(db, "decision") is not None, timeout=60)
    r = authed.patch(f"/api/needs/{_need(db, 'decision')['id']}", json={"status": "dismissed"}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["payload"]["choice"] == "drop"
    assert await drive(w, lambda: _stage(db, "Machine Learning Intern")[0] == "filtered", timeout=30)
    await w.shutdown()
