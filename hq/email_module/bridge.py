"""Mirror confirmed live email activity into the main opportunity and inbox views."""
from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from hq.db import repo
from hq.db.conn import tx
from hq.util.timeutil import now_iso

STAGES = {"applied": "applied", "replied": "replied", "interview": "interview",
          "assessment": "replied", "offer": "offer", "rejected": "rejected"}
ORDER = {"found": 0, "verified": 0, "drafted": 0, "checked": 0, "applied": 1,
         "replied": 2, "interview": 3, "offer": 4, "rejected": 5}


def mirror_live(conn: sqlite3.Connection, detail: dict[str, Any]) -> dict[str, Any]:
    """Only call after a confirmed live send or inbound sync, never for sandbox data."""
    app = detail["application"]
    opp_id = app.get("source_opportunity_id")
    if not opp_id:
        return {"linked": False}
    opp = conn.execute("SELECT id,stage,stage_override FROM opportunities WHERE id=?", (opp_id,)).fetchone()
    if opp is None:
        return {"linked": False, "reason": "opportunity no longer exists"}
    new_stage = STAGES.get(app["status"])
    at = now_iso()
    with tx(conn):
        if app.get("gmail_thread_id"):
            existing = conn.execute("SELECT id,opportunity_id FROM email_threads WHERE gmail_thread_id=?",
                                    (app["gmail_thread_id"],)).fetchone()
            if existing and existing["opportunity_id"] not in (None, opp_id):
                return {"linked": False, "reason": "Gmail thread belongs to a different opportunity"}
            if existing is None:
                thread_id = uuid.uuid4().hex
                conn.execute("INSERT INTO email_threads(id,gmail_thread_id,opportunity_id,subject,counterpart_domain,counterpart_addr,status,last_message_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (thread_id, app["gmail_thread_id"], opp_id,
                              f"Application for {app['role']} at {app['company']}", app["email"].split("@")[-1],
                              app["email"], "open", app.get("last_email_sent"), at))
            else:
                thread_id = existing["id"]
            for msg in detail["messages"]:
                if msg["direction"] != "sent":
                    continue
                conn.execute("INSERT OR IGNORE INTO email_messages(id,gmail_message_id,thread_id,direction,from_addr,to_addr,date,subject,snippet,body_text,rfc822_message_id,in_reply_to,classification) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             ("module:" + msg["gmail_id"], msg["gmail_id"], thread_id, "outbound",
                              msg["from_addr"], msg["to_addr"], msg["received_at"], msg["subject"],
                              msg["body"][:200], msg["body"], msg["rfc822_id"], msg["in_reply_to"],
                              msg["classification"]))
        if new_stage and not opp["stage_override"] and opp["stage"] not in {"frozen", "skipped", "filtered"} and ORDER.get(new_stage, 0) >= ORDER.get(opp["stage"], 0) and new_stage != opp["stage"]:
            conn.execute("UPDATE opportunities SET stage=?,stage_reason=?,updated_at=? WHERE id=?",
                         (new_stage, f"Email module: {app['status']}", at, opp_id))
            repo.audit(conn, "email_module", "opportunity.email_status_mirrored", opp_id,
                       before={"stage": opp["stage"]}, after={"stage": new_stage, "email_application_id": app["id"]})
    return {"linked": True, "opportunity_id": opp_id, "stage": new_stage or opp["stage"]}
