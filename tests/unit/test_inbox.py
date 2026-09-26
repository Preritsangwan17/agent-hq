"""Inbox Watcher, follow-ups, notifications and go-live (CONTRACT_D §2, §4–§6) with the fake Gmail.

Acceptance: a synthetic interview email produces an alert, a notification and a lock, and no reply; the follow-up
fires once at day 10 on a simulated clock."""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from conftest import MUTATE, drive

from hq.adapters.base import Services
from hq.db.conn import tx
from hq.db.seed import get_settings, set_settings
from hq.gmail.fake import FakeGmail
from hq.pipeline import followup as fu
from hq.pipeline.agents.inbox import merge
from hq.pipeline.apply import guard
from hq.pipeline.discover.fetch import Fetcher
from hq.pipeline.inbox import alerts, rules
from hq.util import timeutil
from hq.worker import queue
from hq.worker.orchestrator import Worker

GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "emails_synthetic.jsonl"


# ── rules on the gold set ────────────────────────────────────────────────────────────────────────────
def test_rules_lock_precision_recall_and_labels_on_gold():
    rows = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]
    tp = fp = fn = 0
    wrong = []
    for r in rows:
        res = rules.classify(r["subject"], r["body"], r["from"])
        tp += res.lock and r["lock_expected"]
        fp += res.lock and not r["lock_expected"]
        fn += (not res.lock) and r["lock_expected"]
        if (res.label or "other") != r["label"]:
            wrong.append((r["id"], r["label"], res.label))
    assert fp == 0 and fn == 0 and tp == sum(r["lock_expected"] for r in rows)       # lock precision = recall = 1
    io = [r for r in rows if r["label"] in ("interview_invite", "offer")]
    hit = sum(1 for r in io if rules.classify(r["subject"], r["body"], r["from"]).label == r["label"])
    assert hit / len(io) >= 0.95
    assert not wrong, wrong


@pytest.mark.parametrize("subject, body, sender, label, lock", [
    ("Thanks for applying", "If shortlisted, we will invite you to an interview.", "no-reply@greenhouse.io",
     "auto_ack", False),
    ("Update", "Unfortunately we are unable to offer you a position.", "hr@acme.com", "rejection", False),
    ("Offer letter", "Your offer letter is attached. Share your bank account details for the stipend.",
     "hr@acme.com", "offer", True),
    ("Message", "Rahul sent you a message: would you like to interview with us?", "messages-noreply@linkedin.com",
     "interview_invite", True),
    ("Quick one", "Please share your LinkedIn profile.", "talent@acme.com", "info_request", False),
])
def test_rules_probes_beyond_gold(subject, body, sender, label, lock):
    res = rules.classify(subject, body, sender)
    assert (res.label, res.lock) == (label, lock)


def test_model_can_add_a_lock_but_never_remove_one():
    interview = rules.classify("Chat?", "Are you free for a quick call tomorrow?", "cto@startup.io")
    label, lock, *_ = merge(interview, {"label": "other", "lock": False, "confidence": 0.95, "model_id": "m"})
    assert lock is True and label == "interview_invite"            # a rule lock is final
    plain = rules.classify("Hello", "Just checking in about the internship.", "cto@startup.io")
    label, lock, *_ = merge(plain, {"label": "offer", "lock": True, "confidence": 0.9, "model_id": "m"})
    assert lock is True and label == "offer"


def test_alert_parsing_keeps_target_roles_only():
    rows = [json.loads(line) for line in GOLD.read_text().splitlines() if '"job_alert"' in line]
    by_id = {r["id"]: alerts.postings(r["subject"], r["body"], r["from"]) for r in rows}
    assert [(p.company, p.automation) for p in by_id["syn-33"]] == [("Orbit Data", "manual_lane"),
                                                                     ("Lumen ML", "manual_lane")]
    assert by_id["syn-35"] == []                                    # "AI trainer" is not a target title
    li = ("Machine Learning Intern\nScale AI\nBengaluru, Karnataka, India\nView job: https://www.linkedin.com/comm/"
          "jobs/view/1/\n\nSenior Director, Sales\nScale AI\nRemote\nView job: https://www.linkedin.com/comm/jobs/view/2/")
    roles = alerts.postings("2 new jobs", li, "jobalerts-noreply@linkedin.com")
    assert [(p.title, p.url) for p in roles] == [("Machine Learning Intern", "https://www.linkedin.com/comm/jobs/view/1/")]


# ── the watcher end to end ───────────────────────────────────────────────────────────────────────────
@pytest.fixture
def inbox(db, team, monkeypatch):
    """Worker + fake Gmail, with one real (non-simulated) email application already sent in dry run."""
    from hq.db import repo

    with tx(db):
        set_settings(db, {"sim_enabled": False})
        oid = repo.insert_opportunity(db, {"canonical_key": "t:fakeco", "company_name": "Fakeco", "title": "ML Intern",
                                           "url": "https://fakeco.ai/careers/ml", "apply_email": "careers@fakeco.ai",
                                           "apply_email_quote": "Send your CV to careers@fakeco.ai", "stage": "checked",
                                           "apply_channel": "email"}, is_simulated=False)
        db.execute("INSERT INTO applications(id, opportunity_id, channel, status, mode, created_at, updated_at) VALUES "
                   "('app1', ?, 'email', 'queued', 'dry_run', '2026-09-01', '2026-09-01')", (oid,))
    res = guard.send_email(db, application_id="app1", to_addr="careers@fakeco.ai", subject="Application: ML Intern",
                           body="Dear Hiring Team, …", attachments=[], content_sha="s1")
    with tx(db):
        db.execute("UPDATE opportunities SET stage='applied' WHERE id=?", (oid,))
    gmail = FakeGmail()
    w = Worker(conn=db, agents_dir=team, loop_interval=0.01, watch=False, schedule=False,
               services=Services(gmail=gmail, fetcher=Fetcher(db, transport=httpx.MockTransport(
                   lambda r: httpx.Response(404)))))
    return w, gmail, oid, res.message_id


async def _poll(w, db, until):
    with tx(db):
        queue.enqueue(db, "inbox.poll", type_="scheduled")
    ok = await drive(w, until, timeout=20)
    failed = [dict(r) for r in db.execute("SELECT capability, last_error FROM tasks WHERE status IN ('failed','dead')")]
    assert ok, failed
    return ok


async def test_interview_email_alerts_notifies_locks_and_nobody_replies(db, inbox):
    w, gmail, oid, our_id = inbox
    w.startup()
    gmail.deliver(from_addr="careers@fakeco.ai", from_name="Asha Rao", subject="Re: Application: ML Intern",
                  body="Hi Prerit, we'd like to invite you to a 30-minute interview. Please pick a slot: "
                       "https://calendly.com/fakeco/30min", in_reply_to=our_id)
    gmail.deliver(from_addr="friend@example.org", subject="Dinner?", body="Pizza tonight?")   # out of scope
    await _poll(w, db, lambda: db.execute("SELECT stage FROM opportunities WHERE id=?", (oid,)).fetchone()[0]
                == "interview")
    await w.shutdown()
    t = db.execute("SELECT * FROM email_threads WHERE opportunity_id=? AND gmail_thread_id NOT LIKE 'mock-%'",
                   (oid,)).fetchone()
    assert t["notify_only_lock"] == 1 and t["lock_reason"] == "interview" and t["counterpart_addr"] == "careers@fakeco.ai"
    need = db.execute("SELECT * FROM needs_prerit WHERE kind='interview'").fetchone()
    assert need and need["priority"] >= 95 and "Notify-only lock" in need["instructions_md"]
    note = db.execute("SELECT * FROM notifications WHERE severity='alert'").fetchone()
    assert note and note["title"].startswith("Interview request")
    assert db.execute("SELECT COUNT(*) FROM email_messages WHERE from_addr='friend@example.org'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM mock_mailbox").fetchone()[0] == 1        # only the original application
    assert not gmail.sent() and not [c for c in gmail.calls if c[0] in ("send", "draft")]
    with pytest.raises(guard.GuardBlocked) as e:                                     # and nothing can write there
        guard.prepare(db, kind="reply", to_addr="careers@fakeco.ai", subject="Re: hi", body="x", attachments=[],
                      content_sha="r", thread_id=t["id"])
    assert e.value.kind == "locked"
    assert get_settings(db)["gmail_state"]["history_id"]


async def test_history_404_falls_back_to_a_30_day_full_sync(db, inbox):
    w, gmail, oid, our_id = inbox
    w.startup()
    with tx(db):
        set_settings(db, {"gmail_state": {"history_id": "5"}})
    gmail.expire_history()
    gmail.deliver(from_addr="no-reply@greenhouse.io", subject="Thanks for applying to Fakeco",
                  body="We have received your application for ML Intern at Fakeco.")
    await _poll(w, db, lambda: db.execute("SELECT COUNT(*) FROM email_messages WHERE classification IS NOT NULL "
                                          "AND direction='inbound'").fetchone()[0] == 1)
    await w.shutdown()
    st = get_settings(db)["gmail_state"]
    assert st["last_full_sync_at"] and int(st["history_id"]) >= gmail.history_id - 1
    m = db.execute("SELECT m.classification, t.opportunity_id FROM email_messages m JOIN email_threads t ON "
                   "t.id=m.thread_id WHERE m.direction='inbound'").fetchone()
    assert m["classification"] == "auto_ack" and m["opportunity_id"] == oid        # linked via the ATS + company name
    assert db.execute("SELECT stage FROM opportunities WHERE id=?", (oid,)).fetchone()[0] == "applied"


async def test_info_request_gets_a_gated_draft_that_prerit_approves(db, inbox, authed):
    w, gmail, oid, our_id = inbox
    w.startup()
    gmail.deliver(from_addr="careers@fakeco.ai", subject="Re: Application: ML Intern",
                  body="Hi Prerit, could you share the link to your GitHub profile?", in_reply_to=our_id)
    await _poll(w, db, lambda: db.execute("SELECT 1 FROM needs_prerit WHERE kind='approve_reply'").fetchone()
                is not None)
    need = db.execute("SELECT * FROM needs_prerit WHERE kind='approve_reply'").fetchone()
    doc_id = json.loads(need["payload_json"])["document_id"]
    doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    assert doc["status"] == "draft" and "https://github.com/Preritsangwan17" in doc["content_text"]
    assert "auto-replies are off" in need["instructions_md"]
    r = authed.post(f"/api/inbox/drafts/{doc_id}/send", headers=MUTATE)
    assert r.status_code == 200 and r.json()["queued"]
    assert await drive(w, lambda: db.execute("SELECT status FROM documents WHERE id=?", (doc_id,)).fetchone()[0]
                       == "sent", timeout=20)
    await w.shutdown()
    mail = db.execute("SELECT * FROM mock_mailbox ORDER BY created_at DESC").fetchone()
    assert mail["to_addr"] == "careers@fakeco.ai" and mail["in_reply_to"] and mail["subject"].startswith("Re:")
    assert db.execute("SELECT stage FROM opportunities WHERE id=?", (oid,)).fetchone()[0] == "replied"


async def test_requests_outside_the_allowed_set_are_left_for_prerit(db, inbox):
    w, gmail, oid, our_id = inbox
    w.startup()
    gmail.deliver(from_addr="careers@fakeco.ai", subject="Re: Application", in_reply_to=our_id,
                  body="Could you please send your transcript?")
    await _poll(w, db, lambda: db.execute("SELECT 1 FROM needs_prerit WHERE kind='missing_info'").fetchone()
                is not None)
    await w.shutdown()
    assert not db.execute("SELECT 1 FROM documents WHERE kind='reply'").fetchone()


async def test_job_alert_becomes_opportunities_and_finds_the_ats_posting(db, team):
    board = {"jobs": [{"id": 77, "title": "Machine Learning Intern", "location": {"name": "Bengaluru, India"},
                       "absolute_url": "https://boards.greenhouse.io/orbitdata/jobs/77", "content": "<p>Intern</p>",
                       "updated_at": "2026-09-20T10:00:00Z"}]}

    def api(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if req.url.host == "boards-api.greenhouse.io" and req.url.path == "/v1/boards/orbitdata/jobs":
            return httpx.Response(200, json=board)
        return httpx.Response(404)

    async def nosleep(_):
        return None

    with tx(db):
        set_settings(db, {"sim_enabled": False})
    gmail = FakeGmail()
    w = Worker(conn=db, agents_dir=team, loop_interval=0.01, watch=False, schedule=False,
               services=Services(gmail=gmail, fetcher=Fetcher(db, transport=httpx.MockTransport(api), sleep=nosleep)))
    w.startup()
    gmail.deliver(from_addr="jobalerts-noreply@linkedin.com", subject="Machine Learning Intern at Orbit Data",
                  body="New jobs matching Machine Learning Intern in India: Orbit Data - Bengaluru; Lumen ML - Remote. "
                       "View all jobs.")
    await _poll(w, db, lambda: db.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 2)
    await w.shutdown()
    rows = {r["company_name"]: dict(r) for r in db.execute("SELECT * FROM opportunities")}
    assert rows["Orbitdata"]["canonical_key"] == "greenhouse:orbitdata:77" or \
        rows.get("Orbit Data", {}).get("canonical_key", "").startswith("greenhouse:")
    lumen = rows["Lumen ML"]
    assert lumen["automation"] == "manual_lane" and lumen["apply_channel"] == "manual"
    assert db.execute("SELECT COUNT(*) FROM tasks WHERE capability='parse.job'").fetchone()[0] == 2
    assert not [c for c in gmail.calls if c[0] == "send"]


# ── follow-ups on a simulated clock ──────────────────────────────────────────────────────────────────
async def test_followup_fires_exactly_once_at_day_ten(db, inbox):
    w, gmail, oid, our_id = inbox
    app = dict(db.execute("SELECT * FROM applications WHERE id='app1'").fetchone())
    opp = dict(db.execute("SELECT * FROM opportunities WHERE id=?", (oid,)).fetchone())
    values, why = fu.schedule_values(db, app, opp)
    assert values and values["to_addr"] == "careers@fakeco.ai"
    with tx(db):
        for _ in range(2):  # UNIQUE: a second schedule for the same application is ignored
            db.execute("INSERT OR IGNORE INTO followups(id, application_id, opportunity_id, to_addr, due_at, status, "
                       "created_at, updated_at) VALUES (?,?,?,?,?, 'scheduled', ?, ?)",
                       (f"f{_}", "app1", oid, values["to_addr"], values["due_at"], "2026-09-01", "2026-09-01"))
    assert db.execute("SELECT COUNT(*) FROM followups").fetchone()[0] == 1
    submitted = timeutil.parse_iso(app["submitted_at"])
    assert await fu.run_due(db, None, now=submitted + timedelta(days=9, hours=23)) == []
    assert await fu.run_due(db, None, now=submitted + timedelta(days=10, minutes=1)) == [("sent", "dry_run")]
    assert await fu.run_due(db, None, now=submitted + timedelta(days=30)) == []
    mails = [dict(r) for r in db.execute("SELECT * FROM mock_mailbox ORDER BY created_at")]
    assert len(mails) == 2 and mails[1]["subject"].startswith("Re: Application") and "follow up" in mails[1]["body"]
    assert mails[1]["in_reply_to"] == our_id
    assert db.execute("SELECT status FROM followups").fetchone()[0] == "sent"


async def test_no_followup_after_a_reply_or_on_a_locked_thread(db, inbox):
    w, gmail, oid, our_id = inbox
    app = dict(db.execute("SELECT * FROM applications WHERE id='app1'").fetchone())
    opp = dict(db.execute("SELECT * FROM opportunities WHERE id=?", (oid,)).fetchone())
    values, _ = fu.schedule_values(db, app, opp)
    t = db.execute("SELECT id FROM email_threads WHERE application_id='app1'").fetchone()["id"]
    with tx(db):
        db.execute("INSERT INTO followups(id, application_id, opportunity_id, to_addr, due_at, created_at, updated_at) "
                   "VALUES ('f1','app1',?,?,?,'x','x')", (oid, values["to_addr"], values["due_at"]))
        db.execute("UPDATE email_threads SET notify_only_lock=1, lock_reason='interview' WHERE id=?", (t,))
    later = timeutil.parse_iso(values["due_at"]) + timedelta(hours=1)
    assert (await fu.run_due(db, None, now=later))[0][0] == "blocked"
    assert db.execute("SELECT COUNT(*) FROM mock_mailbox").fetchone()[0] == 1
    with tx(db):
        db.execute("UPDATE followups SET status='scheduled'")
        db.execute("UPDATE email_threads SET notify_only_lock=0 WHERE id=?", (t,))
        db.execute("INSERT INTO email_messages(id, gmail_message_id, thread_id, direction, from_addr, date, "
                   "classification) VALUES ('m1','g1',?, 'inbound', 'careers@fakeco.ai', ?, 'info_request')",
                   (t, timeutil.now_iso()))
    assert await fu.run_due(db, None, now=later) == [("skipped", "replied")]


def test_ats_application_without_recruiter_address_gets_no_followup(db):
    ok, why = fu.schedule_values(db, {"id": "a", "channel": "ats_form", "submitted_at": "2026-09-01T00:00:00Z"},
                                 {"id": "o", "apply_email": None})
    assert ok is None and "ATS" in why


# ── notifications ────────────────────────────────────────────────────────────────────────────────────
async def test_notifications_are_stored_and_mac_delivery_uses_argv(db, monkeypatch):
    from hq import notify

    with tx(db):
        notify.create(db, "alert", 'Interview: "Fakeco"', "reply yourself; $(rm -rf ~)", "/inbox")
        assert notify.create(db, "alert", 'Interview: "Fakeco"', "dup", dedupe_open=True) is None
    assert await notify.deliver_pending(db) == 0                    # not macOS here → marked not applicable
    assert db.execute("SELECT mac_delivered FROM notifications").fetchone()[0] == 2
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(notify.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None)
    argv = notify.mac_command('Interview: "Fakeco"', "reply yourself; $(rm -rf ~)", "/inbox")
    assert argv[0] == "/usr/bin/osascript" and argv[-2:] == ['Interview: "Fakeco"', "reply yourself; $(rm -rf ~)"]
    assert "rm -rf" not in argv[2]                                   # text is data (argv), never script


def test_notification_routes(authed, db):
    from hq import notify

    with tx(db):
        nid = notify.create(db, "warn", "Gmail needs reconnecting")
    r = authed.get("/api/notifications").json()
    assert r["unacked"] == 1 and r["items"][0]["id"] == nid
    assert authed.post(f"/api/notifications/{nid}/ack", headers=MUTATE).json()["unacked"] == 0


# ── go-live ──────────────────────────────────────────────────────────────────────────────────────────
def test_golive_checklist_gates_every_step(authed, db, monkeypatch):
    st = authed.get("/api/golive").json()
    assert st["mode"] == "dry_run" and not st["ready_for_live"]
    assert {i["id"] for i in st["items"]} >= {"gmail", "profile", "reviewed", "golden", "caps", "cloud", "send_scope",
                                              "env", "self_test"}
    assert authed.post("/api/golive/golden", headers=MUTATE).json()["items"][3]["ok"] is True
    assert authed.post("/api/golive/env", headers=MUTATE).status_code == 409
    assert authed.post("/api/gmail/connect", json={"purpose": "send"}, headers=MUTATE).status_code == 409
    r = authed.post("/api/golive/confirm", json={"confirm": "go live"}, headers=MUTATE)
    assert r.status_code == 422
    r = authed.post("/api/golive/confirm", json={"confirm": "GO LIVE"}, headers=MUTATE)
    assert r.status_code == 409 and "missing" in json.dumps(r.json())
    assert get_settings(db)["mode"] == "dry_run"


def test_golive_routes_are_loopback_only(app, db):
    from fastapi.testclient import TestClient

    from conftest import PASSCODE

    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as local:
        assert local.post("/api/auth/setup", json={"passcode": PASSCODE}, headers=MUTATE).status_code == 200
        cookie = local.cookies.get("hq_session")
    with TestClient(app, base_url="http://localhost", client=("192.168.1.20", 50000)) as phone:
        phone.cookies.set("hq_session", cookie)
        for path, body in (("/api/golive/env", None), ("/api/golive/confirm", {"confirm": "GO LIVE"}),
                           ("/api/golive/self-test", None), ("/api/gmail/connect", {"purpose": "readonly"}),
                           ("/api/gmail/disconnect", None)):
            r = phone.post(path, json=body, headers=MUTATE)
            assert r.status_code == 403, (path, r.status_code, r.text)
        assert phone.post("/api/golive/dry-run", json={}, headers=MUTATE).status_code == 200   # safer: always ok


def test_marking_dry_run_applications_reviewed(authed, db):
    from hq.db import repo

    with tx(db):
        oid = repo.insert_opportunity(db, {"canonical_key": "t:r", "company_name": "R", "title": "T"}, is_simulated=False)
        db.execute("INSERT INTO applications(id, opportunity_id, channel, status, mode, created_at, updated_at) VALUES "
                   "('a1', ?, 'email', 'submitted', 'dry_run', 'x', 'x')", (oid,))
    assert authed.post("/api/applications/a1/review", headers=MUTATE).json() == {"ok": True, "reviewed": 1}
    item = next(i for i in authed.get("/api/golive").json()["items"] if i["id"] == "reviewed")
    assert item["detail"] == "1/5 reviewed" and not item["ok"]
