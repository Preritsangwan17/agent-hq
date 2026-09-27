"""Career dossier keeps email evidence, prevents invented confirmation, and blocks suspicious mail."""
from __future__ import annotations

from types import SimpleNamespace

from conftest import MUTATE

from hq.db import repo
from hq.db.conn import tx
from hq.gmail.api import parse_message
from hq.pipeline.agents.inbox import merge
from hq.pipeline.inbox import career, rules
from hq.worker.effects import apply_effects


def _message(sender: str, body: str, auth: str = "dmarc=pass header.from=fakeco.ai") -> SimpleNamespace:
    return SimpleNamespace(from_addr=sender, subject="Offer letter", body_text=body,
                           headers={"authentication-results": auth})


def _opp() -> dict:
    return {"company_name": "Fakeco", "company_domain": "fakeco.ai", "apply_email": "hr@fakeco.ai",
            "url": "https://boards.greenhouse.io/fakeco/jobs/123", "apply_url": None,
            "canonical_key": "greenhouse:fakeco:123", "link_status": "live"}


def test_only_gmail_authentication_header_can_support_verification():
    raw = {"id": "m1", "threadId": "t1", "payload": {"headers": [
        {"name": "From", "value": "HR <hr@fakeco.ai>"},
        {"name": "Subject", "value": "Offer letter"},
        {"name": "Authentication-Results", "value": "untrusted.example; dmarc=pass header.from=fakeco.ai"},
        {"name": "Authentication-Results", "value": "mx.google.com; dmarc=pass header.from=fakeco.ai"},
    ]}, "snippet": "Offer letter"}
    assert career.assess(parse_message(raw), _opp())["verification"] == "Likely Legitimate"
    raw["payload"]["headers"][2]["value"] = "mx.google.com; dmarc=fail header.from=fakeco.ai"
    assert career.assess(parse_message(raw), _opp())["verification"] == "Potentially Suspicious"


def test_verification_requires_public_posting_domain_and_authentication():
    offer = "Offer letter\nJoining date: 12 October 2026"
    good = career.assess(_message("hr@fakeco.ai", offer), _opp())
    assert good["verification"] == "Verified Company"
    assert good["sources"][0]["kind"] == "public_posting"
    assert career.assess(_message("hr@fakeco.ai", offer, "dmarc=fail"), _opp())["verification"] == \
        "Potentially Suspicious"
    assert career.assess(_message("hr@fakeco.ai", offer, "dmarc=pass header.from=other.example"), _opp())[
        "verification"] == "Likely Legitimate"
    assert career.assess(_message("fakeco.hr@gmail.com", offer), _opp())["verification"] == \
        "Potentially Suspicious"
    bad = career.assess(_message("hr@fakeco.ai", offer + "\nPay a training fee at https://bit.ly/test"), _opp())
    assert bad["verification"] == "Potentially Suspicious"
    assert career.assess(_message("hr@fakeco.ai", offer + "\nhttps://unrelated.example/form"), _opp())[
        "verification"] == "Needs Review"
    ordinary = {**_opp(), "canonical_key": "manual:fakeco"}
    assert career.assess(_message("hr@fakeco.ai", offer), ordinary)["verification"] == "Likely Legitimate"


def test_selected_is_distinct_from_offer_and_conditional_selection_is_not_confirmed():
    assert rules.classify("Update", "You have been selected for the ML Intern role.", "hr@fakeco.ai").label == "selected"
    assert career.stage_for("selected", "You have been selected") == "Selected"
    conditional = rules.classify("Update", "If selected, we will send an offer later.", "hr@fakeco.ai")
    assert conditional.label != "selected"
    selected_rule = rules.classify("Update", "You have been selected for the ML Intern role.", "hr@fakeco.ai")
    label, locked, *_ = merge(selected_rule, {"label": "offer", "lock": True, "confidence": 0.99,
                                              "model_id": "wrong-model"})
    assert label == "selected" and locked
    assert career.stage_for("offer", "We confirm your acceptance of our offer.", "Offer") == "Accepted"
    assert career.stage_for("other", "Joining instructions are attached.", "Offer") is None
    assert career.stage_for("other", "Joining instructions are attached.", "Accepted") == "Joining/Onboarding"


def test_interview_and_assessment_details_require_explicit_email_text():
    body = "Interview date: 15 October 2026\nInterview time: 10:00 IST\nMeeting link: https://meet.google.com/abc"
    facts, checklist = career.extract(body, "m-interview", "2026-09-27T10:00:00Z", "Likely Legitimate")
    assert facts["interview_date"]["value"] == "15 October 2026"
    assert facts["interview_link"]["official"] is False
    assert next(x for x in checklist if x["key"] == "interview")["source_message_id"] == "m-interview"
    assert career.extract("Please review our process.", "m2", "2026-09-27T10:00:00Z", "Verified Company") == ({}, [])


def test_offer_dossier_checklist_progress_and_source_email(db, authed):
    with tx(db):
        oid = repo.insert_opportunity(db, {"canonical_key": "greenhouse:fakeco:123", "company_name": "Fakeco",
                                           "title": "ML Intern", "company_domain": "fakeco.ai",
                                           "url": "https://boards.greenhouse.io/fakeco/jobs/123",
                                           "apply_email": "hr@fakeco.ai", "link_status": "live", "stage": "applied"},
                                      is_simulated=False)
        db.execute("INSERT INTO applications(id, opportunity_id, channel, status, mode, created_at, updated_at) "
                   "VALUES ('app1', ?, 'email', 'submitted', 'dry_run', '2026-09-01', '2026-09-01')", (oid,))
        db.execute("INSERT INTO email_threads(id, gmail_thread_id, opportunity_id, application_id, subject, "
                   "last_message_at) VALUES ('t1','gmail-t1',?, 'app1','Offer letter','2026-09-27T10:00:00Z')", (oid,))
        body = ("Offer letter\nSalary: INR 40,000 per month\nJoining date: 12 October 2026\n"
                "Offer deadline: 30 September 2026\nDocuments required: Aadhaar and degree certificate\n"
                "Onboarding link: https://fakeco.ai/onboarding")
        db.execute("INSERT INTO email_messages(id, gmail_message_id, thread_id, direction, from_addr, to_addr, "
                   "date, subject, snippet, body_text) VALUES ('m1','gmail-m1','t1','inbound','hr@fakeco.ai',"
                   "'prerit@example.com','2026-09-27T10:00:00Z','Offer letter',?,?)", (body[:100], body))
        facts, checklist = career.extract(body, "m1", "2026-09-27T10:00:00Z", "Verified Company")
        assert facts["joining_date"]["official"] is True
        assert facts["onboarding_link"]["official"] is False  # links need independent inspection
        apply_effects(db, [{"op": "career.update", "opportunity_id": oid, "application_id": "app1",
                            "message_id": "m1", "occurred_at": "2026-09-27T10:00:00Z", "stage": "Offer",
                            "verification": career.assess(_message("hr@fakeco.ai", body), _opp()),
                            "recruiter_name": "Asha", "recruiter_email": "hr@fakeco.ai",
                            "facts": facts, "checklist": checklist}],
                      agent_id="inbox", task_id="task1", run_id="run1", opportunity_id=oid)
    r = authed.get(f"/api/career/{oid}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["selected"] is True and d["onboarding_mode"] is False
    assert d["offer_details"]["salary_or_stipend"]["value"] == "INR 40,000 per month"
    assert d["offer_details"]["joining_date"]["source_message_id"] == "m1"
    assert d["messages"][0]["body"] == body
    assert d["timeline"][0]["source"] == "gmail"
    item = next(i for i in d["checklist"] if i["item_key"] == "acceptance")
    assert item["due_text"] == "30 September 2026"
    changed = authed.patch(f"/api/career/{oid}/checklist/{item['id']}", json={"status": "done"}, headers=MUTATE)
    assert changed.status_code == 200
    assert next(i for i in changed.json()["checklist"] if i["id"] == item["id"])["status"] == "done"
    later = "Offer update\nJoining date: 19 October 2026"
    with tx(db):
        db.execute("INSERT INTO email_messages(id, gmail_message_id, thread_id, direction, from_addr, to_addr, "
                   "date, subject, snippet, body_text) VALUES ('m2','gmail-m2','t1','inbound','hr@fakeco.ai',"
                   "'prerit@example.com','2026-09-28T10:00:00Z','Offer update',?,?)", (later, later))
        later_facts, later_checklist = career.extract(later, "m2", "2026-09-28T10:00:00Z", "Verified Company")
        apply_effects(db, [{"op": "career.update", "opportunity_id": oid, "application_id": "app1",
                            "message_id": "m2", "occurred_at": "2026-09-28T10:00:00Z", "stage": "Offer",
                            "verification": career.assess(_message("hr@fakeco.ai", later), _opp()),
                            "recruiter_name": "Asha", "recruiter_email": "hr@fakeco.ai",
                            "facts": later_facts, "checklist": later_checklist}],
                      agent_id="inbox", task_id="task2", run_id="run2", opportunity_id=oid)
    conflicted = authed.get(f"/api/career/{oid}").json()
    assert conflicted["offer_details"]["joining_date"]["value"] == "12 October 2026"
    assert conflicted["offer_details"]["joining_date"]["conflicts"][0]["value"] == "19 October 2026"
    assert conflicted["offer_details"]["joining_date"]["conflicts"][0]["source_message_id"] == "m2"
    assert db.execute("SELECT COUNT(*) FROM notifications WHERE title='Conflicting offer details need review'").fetchone()[0] == 1
    assert authed.post(f"/api/career/{oid}/progress", json={"action": "accepted", "confirm": "yes"},
                       headers=MUTATE).status_code == 422
    accepted = authed.post(f"/api/career/{oid}/progress", json={"action": "accepted", "confirm": "I ACCEPTED"},
                           headers=MUTATE)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["onboarding_mode"] is True
    assert accepted.json()["acceptance_company_confirmed"] is False
    joined = authed.post(f"/api/career/{oid}/progress", json={"action": "joined", "confirm": "I JOINED"},
                         headers=MUTATE)
    assert joined.status_code == 200 and joined.json()["communication_stage"] == "Joined"
    assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action='career.progress_recorded'").fetchone()[0] == 2
