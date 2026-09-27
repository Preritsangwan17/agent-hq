"""The email module runs entirely against a throwaway SQLite DB and FakeGmail."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hq.email_module import EmailModule, EmailModuleError
from hq.gmail.fake import FakeGmail
from hq.email_module.file_fake import FileFakeGmail

OWNER = "applicant@example.test"
CONTACT = "maya@acme.example"


@pytest.fixture
def rig(tmp_path):
    clock = [datetime(2026, 9, 27, 10, tzinfo=timezone.utc)]
    gmail = FakeGmail(address=OWNER, scopes=("gmail.readonly", "gmail.send", "gmail.compose"))
    module = EmailModule(tmp_path / "email-lab.db", gmail, owner_email=OWNER, owner_name="Alex Example",
                         now=lambda: clock[0])
    return module, gmail, clock


def add(module, *, company="Acme", email=CONTACT):
    return module.create_application({"company": company, "role": "ML Intern", "contact_name": "Maya",
                                      "email": email, "research": "Acme builds accessible data tools.",
                                      "job_description": "ML Intern role using Python and evaluation.",
                                      "profile": {"verified_project": "a Python data analysis project"}})


@pytest.mark.asyncio
async def test_full_application_reply_and_dashboard(rig):
    module, gmail, clock = rig
    app = add(module)
    draft = await module.draft(app["id"])
    assert "Acme" in draft["body"] and "ML Intern" in draft["body"]
    assert "Python data analysis project" in draft["body"]
    with pytest.raises(EmailModuleError, match="approve"):
        await module.send(draft["id"])
    module.approve(draft["id"])
    sent = await module.send(draft["id"])
    assert sent["status"] == "sent" and len(gmail.sent()) == 1
    assert (await module.send(draft["id"]))["status"] == "sent"
    assert len(gmail.sent()) == 1
    row = module.dashboard()["applications"][0]
    assert row["status"] == "applied" and row["next_followup_at"]
    assert row["last_email_sent"]
    gmail.deliver(from_addr=CONTACT, subject="Interview for ML Intern", body="Please use https://meet.example/interview by deadline 2026-10-05.",
                  thread_id=sent["gmail_message_id"] and gmail.sent()[0].thread_id,
                  in_reply_to=sent["message_id"])
    report = await module.sync()
    assert report["imported"] == 1
    assert (await module.sync())["imported"] == 0
    item = module.application(app["id"])
    assert item["application"]["status"] == "interview"
    assert item["application"]["reply_received"] is True
    assert item["application"]["next_followup_at"] is None
    assert "https://meet.example/interview" in item["application"]["links"]
    assert "2026-10-05" in item["application"]["deadlines"]
    assert len(item["messages"]) == 2
    assert module.due_followups() == []


@pytest.mark.asyncio
async def test_followup_due_only_after_seven_days_and_never_after_reply(rig):
    module, gmail, clock = rig
    app = add(module)
    first = await module.draft(app["id"])
    module.approve(first["id"])
    await module.send(first["id"])
    with pytest.raises(EmailModuleError, match="not due"):
        await module.draft(app["id"], "followup")
    clock[0] += timedelta(days=7, minutes=1)
    assert len(module.due_followups()) == 1
    follow = await module.draft(app["id"], "followup")
    module.approve(follow["id"])
    await module.send(follow["id"])
    assert module.application(app["id"])["application"]["followup_count"] == 1
    assert len(gmail.sent()) == 2
    clock[0] += timedelta(days=7, minutes=1)
    gmail.deliver(from_addr=CONTACT, subject="Re: ML Intern", body="Thanks, we will review your application.",
                  thread_id=gmail.sent()[0].thread_id, in_reply_to=first["message_id"])
    await module.sync()
    assert module.due_followups() == []
    with pytest.raises(EmailModuleError, match="not due"):
        await module.draft(app["id"], "followup")


@pytest.mark.asyncio
async def test_unrelated_mail_and_wrong_sender_cannot_change_status(rig):
    module, gmail, _ = rig
    app = add(module)
    d = await module.draft(app["id"])
    module.approve(d["id"])
    await module.send(d["id"])
    gmail.deliver(from_addr="stranger@other.example", subject="Interview!", body="Visit https://bad.example")
    gmail.deliver(from_addr="other@acme.example", subject="Interview!", body="Visit https://bad.example",
                  thread_id=gmail.sent()[0].thread_id, in_reply_to=d["message_id"])
    result = await module.sync()
    assert result["imported"] == 0
    assert module.application(app["id"])["application"]["status"] == "applied"


@pytest.mark.asyncio
async def test_ambiguous_delivery_is_never_retried_and_reconciles(rig):
    module, gmail, _ = rig
    app = add(module)
    d = await module.draft(app["id"])
    module.approve(d["id"])
    gmail.fail_next_send = "crash_after_send"
    result = await module.send(d["id"])
    assert result["status"] == "sent"
    assert len(gmail.sent()) == 1
    assert (await module.send(d["id"]))["status"] == "sent"
    other = add(module, company="Other", email="hr@other.example")
    other_d = await module.draft(other["id"])
    module.approve(other_d["id"])
    gmail.fail_next_send = "timeout"
    # Advance the clock to satisfy the global send gap.
    module.now = lambda: datetime(2026, 9, 27, 10, 2, tzinfo=timezone.utc)
    ambiguous = await module.send(other_d["id"])
    assert ambiguous["status"] == "ambiguous" and len(gmail.sent()) == 1
    with pytest.raises(EmailModuleError, match="approve"):
        await module.send(other_d["id"])
    assert (await module.reconcile(other_d["id"]))["status"] == "ambiguous"


@pytest.mark.asyncio
async def test_live_policy_and_owner_match(tmp_path):
    gmail = FakeGmail(address=OWNER, scopes=("gmail.readonly", "gmail.send"))
    module = EmailModule(tmp_path / "live.db", gmail, owner_email=OWNER, mode="live")
    app = add(module)
    d = await module.draft(app["id"])
    module.approve(d["id"])
    with pytest.raises(EmailModuleError, match="disabled"):
        await module.send(d["id"])
    module.allow_send = lambda: True
    gmail.address = "someone-else@example.test"
    with pytest.raises(EmailModuleError, match="match"):
        await module.send(d["id"])
    gmail.address = OWNER
    with pytest.raises(EmailModuleError, match="verified"):
        await module.send(d["id"])
    assert gmail.sent() == []


@pytest.mark.asyncio
async def test_duplicate_contact_and_grounding(rig):
    module, _, _ = rig
    app = add(module)
    with pytest.raises(EmailModuleError, match="already"):
        add(module, company="ACME!", email=CONTACT.upper())
    assert app["company"] == "Acme"
    bare = module.create_application({"company": "Other", "role": "Intern", "email": "hr@other.example"})
    with pytest.raises(EmailModuleError, match="research"):
        await module.draft(bare["id"])
    with pytest.raises(EmailModuleError, match="recipient"):
        add(module, company="Third", email="x@example.com\nBcc: stolen@example.com")


@pytest.mark.asyncio
async def test_approved_followup_is_cancelled_if_reply_arrives(rig):
    module, gmail, clock = rig
    app = add(module)
    initial = await module.draft(app["id"])
    module.approve(initial["id"])
    await module.send(initial["id"])
    clock[0] += timedelta(days=8)
    follow = await module.draft(app["id"], "followup")
    module.approve(follow["id"])
    gmail.deliver(from_addr=CONTACT, subject="Application update", body="We are reviewing it.",
                  thread_id=gmail.sent()[0].thread_id, in_reply_to=initial["message_id"])
    await module.sync()
    with pytest.raises(EmailModuleError, match="no longer eligible"):
        await module.send(follow["id"])
    assert len(gmail.sent()) == 1


@pytest.mark.asyncio
async def test_company_cooldown_and_global_gap(rig):
    module, gmail, clock = rig
    one = add(module)
    d1 = await module.draft(one["id"])
    module.approve(d1["id"])
    await module.send(d1["id"])
    two = add(module, company="Acme", email="other@acme.example")
    d2 = await module.draft(two["id"])
    module.approve(d2["id"])
    with pytest.raises(EmailModuleError, match="one minute"):
        await module.send(d2["id"])
    clock[0] += timedelta(minutes=2)
    with pytest.raises(EmailModuleError, match="company"):
        await module.send(d2["id"])
    assert len(gmail.sent()) == 1


@pytest.mark.asyncio
async def test_file_sandbox_survives_reopening(tmp_path):
    path = tmp_path / "mailbox.json"
    gmail = FileFakeGmail(path, OWNER)
    module = EmailModule(tmp_path / "ledger.db", gmail, owner_email=OWNER)
    app = add(module)
    d = await module.draft(app["id"])
    module.approve(d["id"])
    await module.send(d["id"])
    reopened = FileFakeGmail(path, OWNER)
    assert len(reopened.sent()) == 1
    reopened.deliver(from_addr=CONTACT, subject="Interview", body="Interview next week",
                     thread_id=reopened.sent()[0].thread_id, in_reply_to=d["message_id"])
    next_open = FileFakeGmail(path, OWNER)
    module = EmailModule(tmp_path / "ledger.db", next_open, owner_email=OWNER)
    assert (await module.sync())["imported"] == 1
    assert module.application(app["id"])["application"]["status"] == "interview"


@pytest.mark.asyncio
async def test_search_and_rejection_stays_terminal(rig):
    module, gmail, _ = rig
    app = add(module)
    d = await module.draft(app["id"])
    module.approve(d["id"])
    await module.send(d["id"])
    gmail.deliver(from_addr=CONTACT, subject="Application decision", body="Unfortunately we are not proceeding.",
                  thread_id=gmail.sent()[0].thread_id, in_reply_to=d["message_id"])
    assert len((await module.search("decision"))["messages"]) == 1
    await module.sync()
    assert module.application(app["id"])["application"]["status"] == "rejected"
    gmail.deliver(from_addr=CONTACT, subject="Automatic reply", body="Out of office",
                  thread_id=gmail.sent()[0].thread_id, in_reply_to=d["message_id"])
    await module.sync()
    assert module.application(app["id"])["application"]["status"] == "rejected"


@pytest.mark.asyncio
async def test_history_detects_reply_without_job_keywords(rig):
    module, gmail, _ = rig
    app = add(module)
    draft = await module.draft(app["id"])
    module.approve(draft["id"])
    await module.send(draft["id"])
    assert (await module.sync())["full_scan"] is True
    gmail.deliver(from_addr=CONTACT, subject="Next steps", body="Can we speak tomorrow?",
                  thread_id=gmail.sent()[0].thread_id, in_reply_to=draft["message_id"])
    result = await module.sync()
    assert result["full_scan"] is False and result["imported"] == 1
    assert module.application(app["id"])["application"]["status"] == "replied"


@pytest.mark.asyncio
async def test_draft_selects_relevant_verified_fact(rig):
    module, _, _ = rig
    app = module.create_application({"company": "Data Lab", "role": "Python ML Intern",
                                     "email": "team@datalab.example", "research": "Data Lab builds ML tools.",
                                     "job_description": "Python machine learning model evaluation.",
                                     "profile": {"first": "a customer support writing project",
                                                 "second": "a Python machine learning model project"}})
    draft = await module.draft(app["id"])
    assert "a Python machine learning model project" in draft["body"]
    assert "a customer support writing project" not in draft["body"]


@pytest.mark.asyncio
async def test_reply_uses_recruiters_message_as_parent(rig):
    module, gmail, clock = rig
    app = add(module)
    initial = await module.draft(app["id"])
    module.approve(initial["id"])
    await module.send(initial["id"])
    incoming_id = gmail.deliver(from_addr=CONTACT, subject="Re: ML Intern", body="Please send your availability.",
                                thread_id=gmail.sent()[0].thread_id, in_reply_to=initial["message_id"])
    await module.sync()
    reply = await module.draft(app["id"], "reply")
    module.approve(reply["id"])
    clock[0] += timedelta(minutes=2)
    assert (await module.send(reply["id"]))["status"] == "sent"
    incoming_rfc_id = (await gmail.get_message(incoming_id)).rfc822_id
    assert gmail.sent()[-1].in_reply_to == incoming_rfc_id
