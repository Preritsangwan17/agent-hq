"""Inbox, reply drafts, notifications (the header bell) and dry-run application review (CONTRACT_D §6)."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from hq.api import auth
from hq.api.auth import ApiError
from hq.api.routes import Conn, _addr
from hq.db import repo, serializers
from hq.db.conn import tx
from hq.pipeline.gates.fact_deterministic import check_document, split_sentences
from hq.pipeline.state import priority_for
from hq.util.ids import new_id
from hq.util.timeutil import now_iso
from hq.worker import queue

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_session)])
ALERT_KINDS = ("interview_invite", "assessment", "offer", "selected", "legal", "scam")


def _thread_json(conn: sqlite3.Connection, t: dict[str, Any]) -> dict[str, Any]:
    last = conn.execute("SELECT direction, from_addr, snippet, date, classification FROM email_messages WHERE "
                        "thread_id=? ORDER BY COALESCE(date,'') DESC LIMIT 1", (t["id"],)).fetchone()
    counts = conn.execute("SELECT COUNT(*) AS n, SUM(direction='inbound') AS inbound FROM email_messages WHERE "
                          "thread_id=?", (t["id"],)).fetchone()
    drafts = conn.execute("SELECT COUNT(*) FROM documents WHERE email_thread_id=? AND kind='reply' AND status IN "
                          "('draft','approved')", (t["id"],)).fetchone()[0]
    opp = serializers.opp_summary_by_id(conn, t["opportunity_id"]) if t.get("opportunity_id") else None
    return {"id": t["id"], "gmail_thread_id": t.get("gmail_thread_id"), "subject": t.get("subject"),
            "counterpart": t.get("counterpart_addr") or t.get("counterpart_domain"),
            "classification": t.get("classification"), "locked": bool(t.get("notify_only_lock")),
            "verification": t.get("verification"),
            "verification_reasons": serializers._loads(t.get("verification_reasons_json"), []),
            "lock_reason": t.get("lock_reason"), "locked_at": t.get("locked_at"), "unlocked_at": t.get("unlocked_at"),
            "alert_ack_at": t.get("alert_ack_at"), "last_message_at": t.get("last_message_at"),
            "messages": counts["n"] or 0, "inbound": counts["inbound"] or 0, "drafts": drafts,
            "last": dict(last) if last else None,
            "opportunity": {"id": opp["id"], "company_name": opp["company_name"], "title": opp["title"],
                            "stage": opp["stage"], "is_simulated": opp["is_simulated"]} if opp else None,
            "simulated": bool(opp and opp["is_simulated"]) or (t.get("gmail_thread_id") or "").startswith("sim-"),
            "gmail_url": None if (t.get("gmail_thread_id") or "").startswith(("sim-", "mock-")) or
            not t.get("gmail_thread_id") else f"https://mail.google.com/mail/u/0/#all/{t['gmail_thread_id']}"}


@router.get("/inbox/threads")
def threads(filter: str = Query("all", pattern="^(all|locked|alerts|drafts|real)$"),
            limit: int = Query(200, ge=1, le=500), conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    where = {"all": "1=1", "locked": "t.notify_only_lock=1",
             "alerts": f"t.classification IN ({','.join('?' * len(ALERT_KINDS))})",
             "drafts": "EXISTS (SELECT 1 FROM documents d WHERE d.email_thread_id=t.id AND d.kind='reply' AND "
                       "d.status IN ('draft','approved'))",
             "real": "COALESCE(t.gmail_thread_id,'') NOT LIKE 'sim-%'"}[filter]
    args = ALERT_KINDS if filter == "alerts" else ()
    rows = [dict(r) for r in conn.execute(f"SELECT t.* FROM email_threads t WHERE {where} ORDER BY "
                                          "COALESCE(t.last_message_at,'') DESC LIMIT ?", (*args, limit))]
    items = [_thread_json(conn, t) for t in rows]
    counts = {k: conn.execute(q, a).fetchone()[0] for k, q, a in (
        ("all", "SELECT COUNT(*) FROM email_threads", ()),
        ("locked", "SELECT COUNT(*) FROM email_threads WHERE notify_only_lock=1", ()),
        ("alerts", f"SELECT COUNT(*) FROM email_threads WHERE classification IN ({','.join('?' * len(ALERT_KINDS))})",
         ALERT_KINDS),
        ("drafts", "SELECT COUNT(DISTINCT email_thread_id) FROM documents WHERE kind='reply' AND status IN "
                   "('draft','approved')", ()))}
    unacked = [i for i in items if i["locked"] and not i["alert_ack_at"] and
               i["classification"] in ("interview_invite", "interview", "offer")]
    return {"items": items, "counts": counts, "unacked_alerts": [i["id"] for i in unacked]}


def _body(path: str | None, fallback: str | None) -> str:
    if path and Path(path).exists():
        return Path(path).read_text(errors="replace")[:20_000]
    return fallback or ""


@router.get("/inbox/threads/{thread_id}")
def thread(thread_id: str, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    t = conn.execute("SELECT * FROM email_threads WHERE id=?", (thread_id,)).fetchone()
    if t is None:
        raise ApiError(404, "thread not found")
    msgs = [{"id": m["id"], "direction": m["direction"], "from_addr": m["from_addr"], "to_addr": m["to_addr"],
             "date": m["date"], "subject": m["subject"], "classification": m["classification"],
             "confidence": m["confidence"], "reason": m["reason"],
             "lock_terms": serializers._loads(m["lock_terms_json"], []),
             "body": m["body_text"] or _body(m["body_path"], m["snippet"])}
            for m in conn.execute("SELECT * FROM email_messages WHERE thread_id=? ORDER BY COALESCE(date,'')",
                                  (thread_id,))]
    drafts = [{"id": d["id"], "status": d["status"], "subject": d["subject"], "text": d["content_text"],
               "author": d["author_agent"], "created_at": d["created_at"]}
              for d in conn.execute("SELECT * FROM documents WHERE email_thread_id=? AND kind='reply' ORDER BY "
                                    "created_at DESC", (thread_id,))]
    return {**_thread_json(conn, dict(t)), "items": msgs, "reply_drafts": drafts}


class UnlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str


@router.post("/inbox/threads/{thread_id}/unlock")
def unlock(thread_id: str, body: UnlockIn, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    if body.confirm.strip() != "UNLOCK":
        raise ApiError(422, "type UNLOCK to let HQ write on this thread again")
    with tx(conn):
        t = conn.execute("SELECT * FROM email_threads WHERE id=?", (thread_id,)).fetchone()
        if t is None:
            raise ApiError(404, "thread not found")
        conn.execute("UPDATE email_threads SET notify_only_lock=0, unlocked_at=? WHERE id=?", (now_iso(), thread_id))
        repo.audit(conn, "prerit", "inbox.unlock", thread_id, before={"lock_reason": t["lock_reason"]},
                   after={"locked": False}, remote_addr=_addr(request))
        repo.emit(conn, "inbox.updated", f"Unlocked thread “{t['subject']}”", level="warn",
                  data={"thread_id": thread_id})
    return thread(thread_id, conn)


@router.post("/inbox/threads/{thread_id}/ack")
def ack_alert(thread_id: str, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        conn.execute("UPDATE email_threads SET alert_ack_at=COALESCE(alert_ack_at, ?) WHERE id=?", (now_iso(), thread_id))
    return {"ok": True}


def _draft(conn: sqlite3.Connection, doc_id: str) -> dict[str, Any]:
    d = conn.execute("SELECT d.*, t.notify_only_lock FROM documents d LEFT JOIN email_threads t ON "
                     "t.id=d.email_thread_id WHERE d.id=? AND d.kind='reply'", (doc_id,)).fetchone()
    if d is None:
        raise ApiError(404, "draft not found")
    return dict(d)


class DraftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=10, max_length=5000)


@router.patch("/inbox/drafts/{doc_id}")
def edit_draft(doc_id: str, body: DraftPatch, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    """Prerit's edits still go through the deterministic fact rules (no citations required: he wrote them)."""
    d = _draft(conn, doc_id)
    if d["status"] not in ("draft", "approved"):
        raise ApiError(409, f"this draft is {d['status']}")
    body_text = body.text.split("Best regards,")[0]
    report = check_document(split_sentences(body_text))
    bad = [{"text": r["text"], "rules": [v["rule"] for v in r["violations"]]}
           for r in report.sentences if not r["passed"]]
    if bad:
        raise ApiError(422, "the fact rules flagged part of this text", {"sentences": bad})
    with tx(conn):
        conn.execute("UPDATE documents SET content_text=?, sha256=?, status='draft', author_agent='prerit', "
                     "author_model='prerit' WHERE id=?", (body.text, hashlib.sha256(body.text.encode()).hexdigest(),
                                                          doc_id))
        conn.execute("DELETE FROM document_sentences WHERE document_id=?", (doc_id,))
        for i, sent in enumerate(split_sentences(body_text)):
            conn.execute("INSERT INTO document_sentences(id, document_id, idx, text, kind) VALUES (?,?,?,?, 'prerit')",
                         (new_id(), doc_id, i, sent))
        repo.audit(conn, "prerit", "inbox.draft_edited", doc_id, remote_addr=_addr(request))
    return {"ok": True}


def queue_reply(conn: sqlite3.Connection, doc: dict[str, Any], attach_resume: bool) -> str | None:
    """Caller owns the transaction."""
    conn.execute("UPDATE documents SET status='approved' WHERE id=?", (doc["id"],))
    return queue.enqueue(conn, "reply.send", payload={"document_id": doc["id"], "attach_resume": attach_resume},
                         opportunity_id=doc.get("opportunity_id"), priority=priority_for("reply.send"),
                         idempotency_key=f"reply:{doc['id']}", source_agent="prerit")


@router.post("/inbox/drafts/{doc_id}/send")
def send_draft(doc_id: str, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    d = _draft(conn, doc_id)
    if d["notify_only_lock"]:
        raise ApiError(409, "this thread is notify-only locked — reply from Gmail yourself (or unlock it first)")
    if d["status"] not in ("draft", "approved"):
        raise ApiError(409, f"this draft is {d['status']}")
    need = conn.execute("SELECT * FROM needs_prerit WHERE kind='approve_reply' AND status IN ('open','snoozed') AND "
                        "json_extract(payload_json,'$.document_id')=?", (doc_id,)).fetchone()
    attach = bool(serializers._loads(need["payload_json"], {}).get("attach_resume")) if need else False
    with tx(conn):
        task_id = queue_reply(conn, d, attach)
        if need:
            conn.execute("UPDATE needs_prerit SET status='done', resolved_at=? WHERE id=?", (now_iso(), need["id"]))
        repo.audit(conn, "prerit", "inbox.reply_approved", doc_id, remote_addr=_addr(request))
    return {"queued": bool(task_id)}


@router.delete("/inbox/drafts/{doc_id}")
def discard_draft(doc_id: str, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    _draft(conn, doc_id)
    with tx(conn):
        conn.execute("UPDATE documents SET status='discarded' WHERE id=?", (doc_id,))
        conn.execute("UPDATE needs_prerit SET status='dismissed', resolved_at=? WHERE kind='approve_reply' AND status IN "
                     "('open','snoozed') AND json_extract(payload_json,'$.document_id')=?", (now_iso(), doc_id))
        repo.audit(conn, "prerit", "inbox.draft_discarded", doc_id, remote_addr=_addr(request))
    return {"ok": True}


# ── notifications ────────────────────────────────────────────────────────────────────────────────────
@router.get("/notifications")
def notifications(limit: int = Query(50, ge=1, le=200), conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    rows = [dict(r) for r in conn.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?", (limit,))]
    unacked = conn.execute("SELECT COUNT(*) FROM notifications WHERE acknowledged_at IS NULL").fetchone()[0]
    return {"items": rows, "unacked": unacked}


@router.post("/notifications/{nid}/ack")
def ack(nid: str, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        conn.execute("UPDATE notifications SET acknowledged_at=COALESCE(acknowledged_at, ?) WHERE id=?", (now_iso(), nid))
    return notifications(50, conn)


@router.post("/notifications/ack-all")
def ack_all(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        conn.execute("UPDATE notifications SET acknowledged_at=? WHERE acknowledged_at IS NULL", (now_iso(),))
    return notifications(50, conn)


# ── dry-run review (go-live checklist) ───────────────────────────────────────────────────────────────
@router.post("/applications/{app_id}/review")
def review(app_id: str, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        a = conn.execute("SELECT id, mode, reviewed_at FROM applications WHERE id=?", (app_id,)).fetchone()
        if a is None:
            raise ApiError(404, "application not found")
        if a["mode"] != "dry_run":
            raise ApiError(409, "only dry-run applications are reviewed for the go-live checklist")
        conn.execute("UPDATE applications SET reviewed_at=COALESCE(reviewed_at, ?) WHERE id=?", (now_iso(), app_id))
        repo.audit(conn, "prerit", "application.reviewed", app_id, remote_addr=_addr(request))
        n = conn.execute("SELECT COUNT(*) FROM applications WHERE reviewed_at IS NOT NULL AND mode='dry_run'"
                         ).fetchone()[0]
    return {"ok": True, "reviewed": n}
