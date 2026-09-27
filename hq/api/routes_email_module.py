"""Optional email lab API. It uses a separate ledger and never starts a worker."""
from __future__ import annotations

import os
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from hq import settings
from hq.api import auth
from hq.api.auth import ApiError
from hq.db.conn import connect
from hq.db.seed import get_settings
from hq.email_module import EmailModule, EmailModuleError
from hq.email_module.file_fake import FileFakeGmail
from hq.email_module.bridge import mirror_live
from hq.gmail import auth as gauth
from hq.gmail.client import GmailClient
from hq.pipeline.apply.guard import recipient_ok
from hq.profile import owner
from hq.util.netguard import current_mode

router = APIRouter(prefix="/api/email-module", dependencies=[Depends(auth.require_session)])
Mode = Literal["sandbox", "live"]
log = logging.getLogger(__name__)


def _mirror(module: EmailModule, application_id: str) -> dict[str, Any]:
    db = connect()
    try:
        return mirror_live(db, module.application(application_id))
    finally:
        db.close()


def _module(mode: Mode) -> EmailModule:
    data_dir = settings.DATA / "email-module"
    gmail = FileFakeGmail(data_dir / "sandbox-mailbox.json", owner.email()) if mode == "sandbox" else (
        GmailClient() if gauth.connected() else None)

    def live_allowed() -> bool:
        if os.environ.get("HQ_EMAIL_MODULE_LIVE") != "1" or current_mode() != "live" or not gauth.connected() or not gauth.has_send_scope():
            return False
        db = connect()
        try:
            s = get_settings(db)
            if s.get("global_pause") or s.get("freeze_outbound") or s.get("mode") != "live":
                return False
            since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
            main_count = db.execute("SELECT COUNT(*) FROM outbound_log WHERE channel IN ('email','followup','reply') AND status IN ('intent','sent','ambiguous') AND ts>=?", (since,)).fetchone()[0]
            module_count = 0
            if (data_dir / "live.db").exists():
                with sqlite3.connect(data_dir / "live.db") as lab:
                    module_count = lab.execute("SELECT COUNT(*) FROM drafts WHERE status IN ('sending','sent','ambiguous') AND sent_at>=?", (since,)).fetchone()[0]
            return main_count + module_count < min(10, int(s.get("email_daily_cap", 10)))
        finally:
            db.close()

    def recipient_verified(app: dict[str, Any]) -> bool:
        if not app.get("source_opportunity_id"):
            return False
        db = connect()
        try:
            opp = db.execute("SELECT * FROM opportunities WHERE id=?", (app["source_opportunity_id"],)).fetchone()
            if not opp or opp["is_simulated"] or opp["scam_status"] != "clean" or opp["eligibility_status"] == "ineligible":
                return False
            ok, _ = recipient_ok(dict(opp), app["email"])
            if not ok:
                return False
            if db.execute("SELECT 1 FROM applications WHERE opportunity_id=? AND status='submitted' LIMIT 1", (app["source_opportunity_id"],)).fetchone():
                return False
            since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat(timespec="seconds").replace("+00:00", "Z")
            return db.execute("SELECT 1 FROM outbound_log WHERE recipient_domain=? AND status IN ('intent','sent','ambiguous') AND ts>=? LIMIT 1", (app["email"].split("@")[-1], since)).fetchone() is None
        finally:
            db.close()

    return EmailModule(data_dir / f"{mode}.db", gmail, owner_email=owner.email(), owner_name=owner.name(),
                       mode=mode, allow_send=live_allowed, recipient_policy=recipient_verified)


def _run(fn):
    try:
        return fn()
    except EmailModuleError as exc:
        code = 404 if exc.code == "not_found" else 422 if exc.code.startswith("invalid") or exc.code in {"missing_fields", "insufficient_context"} else 409
        raise ApiError(code, str(exc), {"code": exc.code}) from None


async def _await(awaitable):
    try:
        return await awaitable
    except EmailModuleError as exc:
        code = 404 if exc.code == "not_found" else 422 if exc.code.startswith("invalid") or exc.code in {"missing_fields", "insufficient_context"} else 409
        raise ApiError(code, str(exc), {"code": exc.code}) from None


class ApplicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str = Field(max_length=200)
    role: str = Field(max_length=200)
    contact_name: str = Field(default="", max_length=100)
    email: str = Field(max_length=254)
    research: str = Field(default="", max_length=6000)
    job_description: str = Field(default="", max_length=12000)
    profile: dict[str, str] = Field(default_factory=dict)
    source_opportunity_id: str | None = None


class ApplicationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contact_name: str | None = None
    research: str | None = None
    job_description: str | None = None
    profile: dict[str, str] | None = None
    status: str | None = None


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["application", "followup", "reply"] = "application"


@router.get("")
def dashboard(mode: Mode = "sandbox") -> dict[str, Any]:
    module = _module(mode)
    data = module.dashboard()
    data["gmail_configured"] = gauth.connected()
    data["live_send_enabled"] = mode == "live" and module.allow_send()
    return data


@router.post("/applications")
def create(body: ApplicationIn, mode: Mode = "sandbox") -> dict[str, Any]:
    return _run(lambda: _module(mode).create_application(body.model_dump()))


@router.post("/import/{opportunity_id}")
def import_opportunity(opportunity_id: str, mode: Mode = "sandbox") -> dict[str, Any]:
    db = connect()
    try:
        row = db.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
        if row is None:
            raise ApiError(404, "opportunity not found")
        opp = dict(row)
    finally:
        db.close()
    if not opp.get("apply_email"):
        raise ApiError(409, "this opportunity has no email contact")
    data = {"source_opportunity_id": opportunity_id, "company": opp["company_name"], "role": opp["title"],
            "contact_name": "", "email": opp["apply_email"], "research": "",
            "job_description": opp.get("summary") or "", "profile": {}}
    return _run(lambda: _module(mode).create_application(data))


@router.get("/applications/{application_id}")
def detail(application_id: str, mode: Mode = "sandbox") -> dict[str, Any]:
    return _run(lambda: _module(mode).application(application_id))


@router.patch("/applications/{application_id}")
def update(application_id: str, body: ApplicationPatch, mode: Mode = "sandbox") -> dict[str, Any]:
    return _run(lambda: _module(mode).update_application(application_id, body.model_dump(exclude_unset=True)))


@router.post("/applications/{application_id}/draft")
async def draft(application_id: str, body: DraftIn, mode: Mode = "sandbox") -> dict[str, Any]:
    return await _await(_module(mode).draft(application_id, body.kind))


@router.post("/drafts/{draft_id}/approve")
def approve(draft_id: str, mode: Mode = "sandbox") -> dict[str, Any]:
    return _run(lambda: _module(mode).approve(draft_id))


@router.post("/drafts/{draft_id}/send")
async def send(draft_id: str, mode: Mode = "sandbox") -> dict[str, Any]:
    module = _module(mode)
    result = await _await(module.send(draft_id))
    if mode == "live" and result["status"] == "sent":
        try:
            result["integration"] = _mirror(module, result["application_id"])
        except Exception:
            log.exception("confirmed live email was sent, but main opportunity mirror failed")
            result["integration"] = {"linked": False, "reason": "main opportunity update failed; email remains sent"}
    return result


@router.post("/drafts/{draft_id}/reconcile")
async def reconcile(draft_id: str, mode: Mode = "sandbox") -> dict[str, Any]:
    module = _module(mode)
    result = await _await(module.reconcile(draft_id))
    if mode == "live" and result["status"] == "sent":
        try:
            result["integration"] = _mirror(module, result["application_id"])
        except Exception:
            log.exception("reconciled email was sent, but main opportunity mirror failed")
            result["integration"] = {"linked": False, "reason": "main opportunity update failed"}
    return result


@router.post("/sync")
async def sync(mode: Mode = "sandbox") -> dict[str, Any]:
    module = _module(mode)
    result = await _await(module.sync())
    if mode == "live":
        linked, failed = 0, 0
        for app in module.dashboard()["applications"]:
            if app["source_opportunity_id"] and app["status"] in {"applied", "replied", "interview", "assessment", "offer", "rejected"}:
                try:
                    linked += int(_mirror(module, app["id"])["linked"])
                except Exception:
                    failed += 1
                    log.exception("live email status mirror failed for application %s", app["id"])
        result["opportunities_linked"] = linked
        result["integration_failures"] = failed
    return result


@router.get("/search")
async def search(q: str = Query("", max_length=300), mode: Mode = "sandbox") -> dict[str, Any]:
    return await _await(_module(mode).search(q))


class SimulateReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application_id: str
    subject: str = Field(max_length=300)
    body: str = Field(max_length=5000)


@router.post("/sandbox/reply")
def sandbox_reply(body: SimulateReply, request: Request) -> dict[str, Any]:
    auth.require_loopback(request)
    module = _module("sandbox")
    app = _run(lambda: module.application(body.application_id))["application"]
    if not app["gmail_thread_id"]:
        raise ApiError(409, "send a sandbox application email before simulating a reply")
    gmail: FileFakeGmail = module.gmail
    sent = module.application(app["id"])["messages"]
    outbound = next((m for m in reversed(sent) if m["direction"] == "sent"), None)
    mid = gmail.deliver(from_addr=app["email"], subject=body.subject, body=body.body,
                        thread_id=app["gmail_thread_id"], in_reply_to=outbound["rfc822_id"] if outbound else None)
    return {"gmail_message_id": mid, "sandbox": True}
