from __future__ import annotations

from tests.conftest import MUTATE
import pytest

from hq import settings
from hq.db.seed import get_settings
from hq.email_module import EmailModule
from hq.email_module.bridge import mirror_live
from hq.gmail.fake import FakeGmail
from hq.pipeline.apply.guard import GuardBlocked, check_caps


def test_sandbox_api_full_workflow_and_persistent_mailbox(authed):
    base = "/api/email-module"
    form = {"company": "Acme", "role": "ML Intern", "contact_name": "Maya", "email": "maya@acme.example",
            "research": "Acme builds accessible data tools.", "job_description": "Python ML internship.",
            "profile": {"verified": "a Python recommendation project"}}
    r = authed.post(base + "/applications", json=form, headers=MUTATE)
    assert r.status_code == 200, r.text
    app_id = r.json()["id"]
    d = authed.post(base + f"/applications/{app_id}/draft", json={"kind": "application"}, headers=MUTATE)
    assert d.status_code == 200, d.text
    draft_id = d.json()["id"]
    refused = authed.post(base + f"/drafts/{draft_id}/send", json={}, headers=MUTATE)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "not_approved"
    assert authed.post(base + f"/drafts/{draft_id}/approve", json={}, headers=MUTATE).status_code == 200
    sent = authed.post(base + f"/drafts/{draft_id}/send", json={}, headers=MUTATE)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"
    assert authed.get(base).json()["applications"][0]["status"] == "applied"
    simulated = authed.post(base + "/sandbox/reply", json={"application_id": app_id,
                            "subject": "Interview invitation", "body": "Meet at https://meet.example/a by deadline 2026-10-05"}, headers=MUTATE)
    assert simulated.status_code == 200, simulated.text
    synced = authed.post(base + "/sync", json={}, headers=MUTATE)
    assert synced.status_code == 200 and synced.json()["imported"] == 1, synced.text
    detail = authed.get(base + f"/applications/{app_id}").json()
    assert detail["application"]["status"] == "interview"
    assert detail["application"]["reply_received"] is True
    assert len(detail["messages"]) == 2
    assert authed.post(base + "/sync", json={}, headers=MUTATE).json()["imported"] == 0


def test_live_api_stays_disconnected_without_oauth(authed):
    result = authed.get("/api/email-module?mode=live")
    assert result.status_code == 200
    assert result.json()["connected"] is False
    assert result.json()["live_send_enabled"] is False
    form = {"company": "Acme", "role": "Intern", "email": "hr@acme.example",
            "research": "Acme builds tools.", "job_description": "Python intern.",
            "profile": {"verified": "a Python project"}}
    created = authed.post("/api/email-module/applications?mode=live", json=form, headers=MUTATE)
    assert created.status_code == 200
    draft = authed.post(f"/api/email-module/applications/{created.json()['id']}/draft?mode=live",
                        json={}, headers=MUTATE).json()
    authed.post(f"/api/email-module/drafts/{draft['id']}/approve?mode=live", json={}, headers=MUTATE)
    blocked = authed.post(f"/api/email-module/drafts/{draft['id']}/send?mode=live", json={}, headers=MUTATE)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "gmail_disconnected"


@pytest.mark.asyncio
async def test_main_send_guard_sees_email_module_outreach(db):
    path = settings.DATA / "email-module" / "live.db"
    module = EmailModule(path, FakeGmail(address="owner@example.test", scopes=("gmail.send",)),
                         owner_email="owner@example.test")
    app = module.create_application({"company": "Acme", "role": "Intern", "email": "hr@acme.example",
                                     "research": "Acme builds tools.", "job_description": "Python intern.",
                                     "profile": {"project": "a Python project"}})
    draft = await module.draft(app["id"])
    module.approve(draft["id"])
    assert (await module.send(draft["id"]))["status"] == "sent"
    with pytest.raises(GuardBlocked, match="email module already contacted"):
        check_caps(db, get_settings(db), "other@acme.example", cold=True)


@pytest.mark.asyncio
async def test_confirmed_live_activity_can_mirror_into_main_opportunity(db, tmp_path):
    db.execute("INSERT INTO opportunities(id,canonical_key,company_name,title,first_seen_at,updated_at) VALUES (?,?,?,?,?,?)",
               ("opp-email-1", "test:opp-email-1", "Acme", "ML Intern", "2026-09-27T00:00:00Z", "2026-09-27T00:00:00Z"))
    gmail = FakeGmail(address="owner@example.test", scopes=("gmail.send",))
    module = EmailModule(tmp_path / "isolated.db", gmail, owner_email="owner@example.test")
    app = module.create_application({"source_opportunity_id": "opp-email-1", "company": "Acme",
                                     "role": "ML Intern", "email": "hr@acme.example", "research": "Acme builds ML tools.",
                                     "job_description": "Python ML internship.", "profile": {"verified": "a Python project"}})
    draft = await module.draft(app["id"])
    module.approve(draft["id"])
    await module.send(draft["id"])
    assert mirror_live(db, module.application(app["id"]))["linked"] is True
    assert db.execute("SELECT stage FROM opportunities WHERE id='opp-email-1'").fetchone()[0] == "applied"
    assert db.execute("SELECT COUNT(*) FROM email_messages WHERE direction='outbound'").fetchone()[0] == 1
    gmail.deliver(from_addr="hr@acme.example", subject="Interview invitation", body="Interview next week.",
                  thread_id=gmail.sent()[0].thread_id, in_reply_to=draft["message_id"])
    await module.sync()
    mirror_live(db, module.application(app["id"]))
    assert db.execute("SELECT stage FROM opportunities WHERE id='opp-email-1'").fetchone()[0] == "interview"
    assert db.execute("SELECT COUNT(*) FROM email_threads WHERE opportunity_id='opp-email-1'").fetchone()[0] == 1
