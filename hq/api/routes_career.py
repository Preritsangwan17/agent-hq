"""Company communication dossiers with source-linked offer and onboarding facts."""
from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from hq.api import auth
from hq.api.auth import ApiError
from hq.api.routes import Conn, _addr
from hq.db import repo, serializers
from hq.db.conn import tx
from hq.util.ids import new_id
from hq.util.timeutil import now_iso

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_session)])


@router.get("/career/{opportunity_id}")
def dossier(opportunity_id: str, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    opp = conn.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
    if opp is None:
        raise ApiError(404, "opportunity not found")
    app = conn.execute("SELECT id, status, submitted_at, channel, submission_ref FROM applications WHERE "
                       "opportunity_id=? ORDER BY created_at DESC LIMIT 1", (opportunity_id,)).fetchone()
    profile = conn.execute("SELECT * FROM career_profiles WHERE opportunity_id=?", (opportunity_id,)).fetchone()
    items = [dict(r) for r in conn.execute("SELECT i.*, m.subject AS source_subject, m.date AS source_date "
                                           "FROM onboarding_items i LEFT JOIN email_messages m ON "
                                           "m.id=i.source_message_id WHERE i.opportunity_id=? "
                                           "ORDER BY i.created_at, i.item_key", (opportunity_id,))]
    events = [dict(r) for r in conn.execute("SELECT e.*, m.subject AS source_subject, "
                                            "m.gmail_message_id FROM career_events e LEFT JOIN email_messages m ON "
                                            "m.id=e.message_id WHERE e.opportunity_id=? ORDER BY e.occurred_at, e.id",
                                            (opportunity_id,))]
    if app and app["submitted_at"]:
        events.insert(0, {"id": "application:" + app["id"], "stage": "Applied", "action": "application_sent",
                          "source": app["channel"], "detail": app["submission_ref"],
                          "occurred_at": app["submitted_at"], "message_id": None})
        events.sort(key=lambda x: x["occurred_at"] or "")
    threads = [dict(r) for r in conn.execute("SELECT id, subject, counterpart_addr, classification, "
                                             "last_message_at, notify_only_lock FROM email_threads WHERE "
                                             "opportunity_id=? ORDER BY last_message_at DESC", (opportunity_id,))]
    messages = [dict(r) for r in conn.execute("SELECT m.id, m.thread_id, m.direction, m.from_addr, m.to_addr, "
                                              "m.date, m.subject, m.classification, m.body_text, m.snippet, "
                                              "m.body_path FROM email_messages m JOIN email_threads t ON t.id=m.thread_id "
                                              "WHERE t.opportunity_id=? ORDER BY m.date, m.id", (opportunity_id,))]
    from hq.api.routes_inbox import _body

    for message in messages:
        message["body"] = message.pop("body_text") or _body(message.pop("body_path"), message["snippet"])
        message.pop("snippet", None)
    activity: list[dict[str, Any]] = [
        {"at": m["date"], "action": "email_received" if m["direction"] == "inbound" else "email_sent",
         "detail": m["subject"], "source": m["thread_id"]} for m in messages]
    activity += [{"at": e["occurred_at"], "action": e["action"], "detail": e["stage"],
                  "source": e["source"], "model_id": e.get("model_id")} for e in events]
    docs = [dict(r) for r in conn.execute("SELECT d.id, d.kind, d.status, d.created_at, d.author_model "
                                          "FROM documents d WHERE d.opportunity_id=? AND d.kind IN ('reply','followup')",
                                          (opportunity_id,))]
    activity += [{"at": d["created_at"], "action": "reply_generated" if d["kind"] == "reply" else "followup_prepared",
                  "detail": d["status"], "source": d["id"], "model_id": d["author_model"]} for d in docs]
    if docs:
        doc_ids = [d["id"] for d in docs]
        marks = ",".join("?" * len(doc_ids))
        activity += [{"at": r["ts"], "action": r["action"], "detail": r["target"], "source": "audit"} for r in
                     conn.execute(f"SELECT ts, action, target FROM audit_log WHERE target IN ({marks}) AND "
                                  "action IN ('inbox.reply_approved','inbox.draft_edited','inbox.draft_discarded')",
                                  doc_ids)]
    if app:
        activity += [{"at": r["ts"], "action": "outgoing_" + r["status"], "detail": r["subject"],
                      "source": r["channel"]} for r in conn.execute(
                          "SELECT ts, status, subject, channel FROM outbound_log WHERE application_id=?", (app["id"],))]
        activity += [{"at": r["created_at"], "action": "followup_scheduled", "detail": r["due_at"],
                      "source": r["status"]} for r in conn.execute(
                          "SELECT created_at, due_at, status FROM followups WHERE application_id=?", (app["id"],))]
    activity.sort(key=lambda x: (x["at"] or "", x["action"]))
    p = dict(profile) if profile else {}
    domain = opp["company_domain"] if "company_domain" in opp.keys() else None
    return {
        "opportunity_id": opportunity_id,
        "company": {"name": opp["company_name"], "website": f"https://{domain}" if domain else None,
                    "posting_url": opp["url"], "apply_url": opp["apply_url"], "title": opp["title"],
                    "kind": opp["kind"], "description": opp["summary"], "location": opp["location_raw"],
                    "city": opp["city"], "country": opp["country_iso2"], "work_mode": opp["work_mode"],
                    "pay": opp["pay_raw"], "application_source": opp["source_label"],
                    "notes": opp["notes_unverified"]},
        "application": dict(app) if app else None,
        "communication_stage": p.get("communication_stage") or "Applied",
        "verification": p.get("verification") or "Needs Review",
        "verification_reasons": serializers._loads(p.get("verification_reasons_json"), []),
        "verification_sources": serializers._loads(p.get("verification_sources_json"), []),
        "recruiter": {"name": p.get("recruiter_name"), "email": p.get("recruiter_email")},
        "offer_details": serializers._loads(p.get("offer_details_json"), {}),
        "selected": (p.get("communication_stage") in ("Selected", "Offer", "Accepted", "Joining/Onboarding", "Joined")),
        "onboarding_mode": (p.get("communication_stage") in ("Accepted", "Joining/Onboarding", "Joined")),
        "checklist": items, "timeline": events, "threads": threads, "messages": messages, "activity": activity,
        "next_expected_action": next((item["title"] for item in items if item["status"] == "pending"), None)
        if p.get("communication_stage") != "Rejected" else None,
        "last_company_communication": next((m["date"] for m in reversed(messages)
                                            if m["direction"] == "inbound"), None),
        "acceptance_company_confirmed": any(e["stage"] == "Accepted" and e["source"] == "gmail" for e in events),
    }


class ItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "done"]


@router.patch("/career/{opportunity_id}/checklist/{item_id}")
def patch_item(opportunity_id: str, item_id: str, body: ItemPatch, request: Request,
               conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        item = conn.execute("SELECT * FROM onboarding_items WHERE id=? AND opportunity_id=?",
                            (item_id, opportunity_id)).fetchone()
        if item is None:
            raise ApiError(404, "checklist item not found")
        at = now_iso()
        conn.execute("UPDATE onboarding_items SET status=?, completed_at=?, updated_at=? WHERE id=?",
                     (body.status, at if body.status == "done" else None, at, item_id))
        repo.audit(conn, "prerit", "career.checklist_updated", opportunity_id,
                   before={"item": item["item_key"], "status": item["status"]},
                   after={"item": item["item_key"], "status": body.status}, remote_addr=_addr(request))
    return dossier(opportunity_id, conn)


class ProgressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accepted", "joined"]
    confirm: str


@router.post("/career/{opportunity_id}/progress")
def record_progress(opportunity_id: str, body: ProgressIn, request: Request,
                    conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    """Record an action already taken by Prerit. This does not email the company or assert company confirmation."""
    required = "I ACCEPTED" if body.action == "accepted" else "I JOINED"
    if body.confirm.strip() != required:
        raise ApiError(422, f"type {required} to record progress already completed outside HQ")
    with tx(conn):
        profile = conn.execute("SELECT * FROM career_profiles WHERE opportunity_id=?", (opportunity_id,)).fetchone()
        if profile is None:
            raise ApiError(409, "no company communication has been recorded")
        before = profile["communication_stage"]
        if profile["verification"] == "Potentially Suspicious":
            raise ApiError(409, "review the suspicious company communication before recording progress")
        if body.action == "accepted" and before != "Offer":
            raise ApiError(409, "record acceptance only after an offer is detected")
        if body.action == "joined" and before not in ("Accepted", "Joining/Onboarding"):
            raise ApiError(409, "record joining only after acceptance or onboarding")
        stage = "Accepted" if body.action == "accepted" else "Joined"
        at = now_iso()
        conn.execute("UPDATE career_profiles SET communication_stage=?, updated_at=? WHERE opportunity_id=?",
                     (stage, at, opportunity_id))
        conn.execute("UPDATE opportunities SET stage_reason=?, updated_at=? WHERE id=?",
                     (f"{stage} (recorded by you; company confirmation pending)", at, opportunity_id))
        conn.execute("INSERT INTO career_events(id, opportunity_id, stage, action, source, detail, occurred_at, "
                     "created_at) VALUES (?,?,?,?,?,?,?,?)",
                     (new_id(), opportunity_id, stage, "user_recorded_" + body.action, "prerit_recorded",
                      "Recorded by you; company confirmation is shown separately.", at, at))
        repo.audit(conn, "prerit", "career.progress_recorded", opportunity_id,
                   before={"stage": before}, after={"stage": stage, "company_confirmed": False},
                   remote_addr=_addr(request))
    return dossier(opportunity_id, conn)
