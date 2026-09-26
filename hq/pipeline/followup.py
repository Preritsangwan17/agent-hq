"""Follow-ups (CONTRACT_D §4): exactly one per application (UNIQUE), 10 days after an email application with no
reply from a person; never on a locked thread; fully gated (fact + quality + caps + locks through the guard).
ATS applications get one only when a recruiter's own address is known from the thread."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from hq.db.conn import tx
from hq.pipeline.apply import guard
from hq.pipeline.inbox.replies import assemble, followup_sentences, gate, recipient_name
from hq.util import timeutil
from hq.util.ids import new_id

FOLLOWUP_DAYS = 10
NOT_A_REPLY = ("auto_ack", "job_alert", "other")


def schedule_values(conn: sqlite3.Connection, app: dict[str, Any], opp: dict[str, Any]) -> tuple[dict | None, str]:
    """(values for the followups row, or None + why not)."""
    submitted = timeutil.parse_iso(app.get("submitted_at"))
    if submitted is None:
        return None, "not submitted yet"
    to = None
    if app.get("channel") == "email" and opp.get("apply_email"):
        to = opp["apply_email"]
    else:
        r = conn.execute("SELECT t.counterpart_addr FROM email_threads t WHERE t.application_id=? AND "
                         "t.counterpart_addr IS NOT NULL AND t.counterpart_addr NOT LIKE '%noreply%' AND "
                         "t.counterpart_addr NOT LIKE '%no-reply%' AND t.counterpart_addr NOT LIKE '%notifications%' "
                         "ORDER BY t.last_message_at DESC LIMIT 1", (app["id"],)).fetchone()
        to = r["counterpart_addr"] if r else None
    if not to:
        return None, "ATS application without a recruiter's address — no follow-up"
    due = timeutil.to_iso(submitted + timedelta(days=FOLLOWUP_DAYS))
    return {"application_id": app["id"], "opportunity_id": opp["id"], "to_addr": to, "due_at": due}, f"due {due[:10]}"


def _person_replied(conn: sqlite3.Connection, app_id: str, since: str | None) -> bool:
    marks = ",".join("?" * len(NOT_A_REPLY))
    return conn.execute(
        f"SELECT 1 FROM email_messages m JOIN email_threads t ON t.id=m.thread_id WHERE t.application_id=? AND "
        f"m.direction='inbound' AND COALESCE(m.date,'') >= ? AND COALESCE(m.classification,'') NOT IN ({marks}) "
        "LIMIT 1", (app_id, since or "", *NOT_A_REPLY)).fetchone() is not None


def _set(conn: sqlite3.Connection, fid: str, status: str, reason: str) -> None:
    with tx(conn):
        conn.execute("UPDATE followups SET status=?, reason=?, updated_at=? WHERE id=?",
                     (status, reason[:300], timeutil.now_iso(), fid))


async def run_due(conn: sqlite3.Connection, gmail: Any, *, now: datetime | None = None, limit: int = 5,
                  task_id: str | None = None) -> list[tuple[str, str]]:
    """Send the follow-ups that are due at `now` (tests pass a simulated clock). Returns [(status, reason)]."""
    now_s = timeutil.to_iso(now or timeutil.utcnow())
    rows = [dict(r) for r in conn.execute(
        "SELECT f.id AS fid, f.to_addr, f.due_at, a.*, o.company_name, o.title AS role, o.stage AS opp_stage "
        "FROM followups f JOIN applications a ON a.id=f.application_id JOIN opportunities o ON o.id=a.opportunity_id "
        "WHERE f.status='scheduled' AND f.due_at <= ? ORDER BY f.due_at LIMIT ?", (now_s, limit))]
    out = []
    for r in rows:
        if r["opp_stage"] != "applied" or r["status"] != "submitted":
            _set(conn, r["fid"], "skipped", f"no follow-up: the role is {r['opp_stage']}")
            out.append(("skipped", "stage"))
            continue
        if _person_replied(conn, r["id"], r.get("submitted_at")):
            _set(conn, r["fid"], "skipped", "they replied")
            out.append(("skipped", "replied"))
            continue
        sentences = followup_sentences(recipient=recipient_name(None), company=r["company_name"], role=r["role"])
        ok, problems = gate(sentences, doc_kind="followup", org=r["company_name"])
        if not ok:
            _set(conn, r["fid"], "blocked", "gate: " + "; ".join(problems)[:250])
            out.append(("blocked", "gate"))
            continue
        text = assemble(sentences)
        subj_row = conn.execute("SELECT subject FROM outbound_log WHERE application_id=? AND channel='email' AND "
                                "status='sent' ORDER BY ts LIMIT 1", (r["id"],)).fetchone()
        subject = f"Re: {subj_row['subject']}" if subj_row and subj_row["subject"] else f"Following up: {r['role']}"
        doc_id = new_id()
        with tx(conn):
            conn.execute("INSERT INTO documents(id, application_id, opportunity_id, kind, version, content_text, sha256, "
                         "author_agent, author_model, status, created_at, subject) VALUES "
                         "(?,?,?, 'followup', 1, ?, ?, 'followup', 'template', 'passed', ?, ?)",
                         (doc_id, r["id"], r["opportunity_id"], text, hashlib.sha256(text.encode()).hexdigest(),
                          timeutil.now_iso(), subject))
            conn.execute("UPDATE followups SET document_id=?, updated_at=? WHERE id=?",
                         (doc_id, timeutil.now_iso(), r["fid"]))
        try:
            res = await guard.send(conn, gmail, kind="followup", to_addr=r["to_addr"], subject=subject, body=text,
                                   attachments=[], content_sha=hashlib.sha256(text.encode()).hexdigest(),
                                   application_id=r["id"], agent_id="followup", task_id=task_id)
        except guard.GuardBlocked as exc:
            if exc.kind in ("paused", "cap"):
                out.append(("waiting", exc.reason))   # stays scheduled; the next run tries again
                continue
            _set(conn, r["fid"], "blocked", exc.reason)  # locked / recipient / ambiguous (Prerit resolves) / failed
            out.append(("blocked", exc.kind))
            continue
        with tx(conn):
            conn.execute("UPDATE documents SET status='sent' WHERE id=?", (doc_id,))
            conn.execute("UPDATE followups SET status='sent', reason=?, updated_at=? WHERE id=?",
                         (f"{res.mode}: {res.status}", timeutil.now_iso(), r["fid"]))
        out.append(("sent", res.mode))
    return out
