"""The outbound guard (PLAN "Orchestrator › PAUSE ALL / Freeze outbound", CONTRACT_C §6). EVERY send goes through
`send_email()`: in one BEGIN IMMEDIATE transaction it re-reads PAUSE ALL, freeze-outbound, the Applicant's pause,
the mode, the approval hash (approve-first), the caps and idempotency, validates the recipient, writes the
`outbound_log` intent with a deterministic Message-ID and then sends through the channel for the current mode.
In DRY RUN the only channel is the mock mailbox; nothing leaves the Mac.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from hq.db import repo
from hq.db.conn import dumps, tx
from hq.db.seed import get_settings
from hq.util import netguard
from hq.util.ids import new_id
from hq.util.timeutil import IST, now_iso, to_iso, today_ist, utcnow

PRERIT_EMAIL = "sangwanprerit40@gmail.com"
DOMAIN_WINDOW_DAYS = 14
LAB_DAILY_CAP = 3
SIGNOFF_BLOCK = "Best regards,\nPrerit Sangwan\n"


class GuardBlocked(Exception):
    def __init__(self, reason: str, *, kind: str = "blocked"):
        super().__init__(reason)
        self.reason, self.kind = reason, kind


@dataclass
class SendResult:
    status: str               # sent | duplicate
    message_id: str
    mode: str
    outbound_id: str


def approval_sha(letter_text: str, resume_sha: str | None, answers: list[dict[str, Any]] | None) -> str:
    """Binds an approval to the exact letter, résumé and answers; any rewrite invalidates it."""
    h = hashlib.sha256()
    h.update((letter_text or "").encode())
    h.update(b"\x00" + (resume_sha or "").encode())
    h.update(b"\x00" + json.dumps(answers or [], sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()


def message_id_for(application_id: str, content_sha: str) -> str:
    return f"<hq-{hashlib.sha256(f'{application_id}:{content_sha}'.encode()).hexdigest()[:24]}@agenthq.local>"


def _registrable(host: str) -> str:
    parts = host.lower().split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "ac", "edu", "gov", "org", "com", "net") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def recipient_ok(opp: dict[str, Any], to_addr: str) -> tuple[bool, str]:
    """Only an address quoted on the official page, whose domain belongs to the organisation."""
    email = (opp.get("apply_email") or "").strip().lower()
    quote = opp.get("apply_email_quote") or ""
    if not email or to_addr.strip().lower() != email:
        return False, "recipient is not the address found on the posting"
    if email not in quote.lower():
        return False, "the address is not an exact quote from the posting"
    edom = _registrable(email.split("@")[-1])
    hosts = {_registrable(netguard.host_of(u)) for u in (opp.get("url"), opp.get("apply_url")) if u}
    if opp.get("company_domain"):
        hosts.add(_registrable(opp["company_domain"]))
    if edom in hosts:
        return True, "address domain matches the organisation's site"
    tokens = {t for t in re.findall(r"[a-z]{3,}", (opp.get("company_name") or "").lower())} | \
             {"".join(w[0] for w in re.findall(r"[A-Za-z]+", opp.get("company_name") or "") if w[0].isupper()).lower()}
    core = edom.split(".")[0]
    if any(t and (t == core or (len(t) >= 4 and t in core)) for t in tokens):
        return True, "address domain matches the organisation name"
    return False, f"{edom} doesn't match {', '.join(sorted(hosts)) or 'the organisation'}"


def _day_start_utc() -> str:
    from datetime import datetime, time

    return to_iso(datetime.combine(today_ist(), time.min, tzinfo=IST))


def check_caps(conn: sqlite3.Connection, s: dict[str, Any], to_addr: str) -> None:
    since = _day_start_utc()
    sent_today = conn.execute("SELECT COUNT(*) FROM outbound_log WHERE channel='email' AND status IN ('intent','sent') "
                              "AND ts >= ?", (since,)).fetchone()[0]
    if sent_today >= int(s.get("email_daily_cap", 10)):
        raise GuardBlocked(f"daily email cap reached ({sent_today}/{s.get('email_daily_cap')})", kind="cap")
    dom = to_addr.split("@")[-1].lower()
    window = to_iso(utcnow() - timedelta(days=DOMAIN_WINDOW_DAYS))
    if conn.execute("SELECT 1 FROM outbound_log WHERE channel='email' AND recipient_domain=? AND status IN "
                    "('intent','sent') AND ts >= ?", (dom, window)).fetchone():
        raise GuardBlocked(f"already emailed {dom} in the last {DOMAIN_WINDOW_DAYS} days", kind="cap")
    if re.search(r"\.(edu|ac)(\.[a-z]{2})?$|\.edu\.[a-z]{2}$", dom):
        labs = conn.execute("SELECT COUNT(*) FROM outbound_log WHERE channel='email' AND status IN ('intent','sent') "
                            "AND ts >= ? AND (recipient_domain LIKE '%.edu%' OR recipient_domain LIKE '%.ac.%')",
                            (since,)).fetchone()[0]
        if labs >= LAB_DAILY_CAP:
            raise GuardBlocked(f"daily cap of {LAB_DAILY_CAP} lab emails reached", kind="cap")


def effective_mode(s: dict[str, Any]) -> str:
    env = netguard.current_mode()
    return "dry_run" if env == "dry_run" else s.get("mode", "dry_run")


def send_email(conn: sqlite3.Connection, *, application_id: str, to_addr: str, subject: str, body: str,
               attachments: list[dict[str, str]], content_sha: str, agent_id: str = "applicant",
               task_id: str | None = None) -> SendResult:
    with tx(conn):
        s = get_settings(conn)
        if s.get("global_pause"):
            raise GuardBlocked("PAUSE ALL is on", kind="paused")
        if s.get("freeze_outbound"):
            raise GuardBlocked("outbound is frozen", kind="paused")
        ag = conn.execute("SELECT paused, enabled FROM agents WHERE id='applicant'").fetchone()
        if ag and (ag["paused"] or not ag["enabled"]):
            raise GuardBlocked("the Applicant is paused", kind="paused")
        app = conn.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
        if app is None:
            raise GuardBlocked("application not found")
        opp = dict(conn.execute("SELECT * FROM opportunities WHERE id=?", (app["opportunity_id"],)).fetchone())
        mode = effective_mode(s)
        mid = message_id_for(application_id, content_sha)
        dup = conn.execute("SELECT id, status, message_id FROM outbound_log WHERE application_id=? AND channel='email' "
                           "AND status IN ('intent','sent','ambiguous')", (application_id,)).fetchone()
        if dup:
            return SendResult("duplicate", dup["message_id"], mode, dup["id"])
        if s.get("autonomy") == "approve_first" and app["approval_sha256"] != content_sha:
            raise GuardBlocked("waiting for Prerit's approval of this exact text", kind="approval")
        ok, why = recipient_ok(opp, to_addr)
        if not ok:
            raise GuardBlocked(why, kind="recipient")
        if mode == "self_test" and to_addr.lower() != PRERIT_EMAIL:
            raise GuardBlocked("SELF-TEST only sends to Prerit's own address", kind="mode")
        check_caps(conn, s, to_addr)
        out_id = new_id()
        conn.execute("INSERT INTO outbound_log(id, channel, recipient_domain, recipient_hash, application_id, mode, "
                     "message_id, status, ts) VALUES (?, 'email', ?, ?, ?, ?, ?, 'intent', ?)",
                     (out_id, to_addr.split("@")[-1].lower(), hashlib.sha256(to_addr.lower().encode()).hexdigest()[:16],
                      application_id, mode, mid, now_iso()))
        if mode != "dry_run":
            # real sending arrives with Gmail (phase d); until then nothing but the mock mailbox exists
            raise GuardBlocked(f"mode {mode} needs the Gmail sender, which isn't connected", kind="mode")
        conn.execute("INSERT INTO mock_mailbox(id, to_addr, subject, body, attachments_json, application_id, created_at) "
                     "VALUES (?,?,?,?,?,?,?)", (new_id(), to_addr, subject, body, dumps(attachments), application_id,
                                                now_iso()))
        conn.execute("UPDATE outbound_log SET status='sent' WHERE id=?", (out_id,))
        conn.execute("UPDATE applications SET status='submitted', submitted_at=?, message_id=?, mode=?, "
                     "submission_ref='mock_mailbox', updated_at=? WHERE id=?",
                     (now_iso(), mid, mode, now_iso(), application_id))
        repo.emit(conn, "mail.mock_sent", f"Mock mail → {to_addr}: {subject} (dry run — nothing left this Mac)",
                  agent_id=agent_id, task_id=task_id, opportunity_id=opp["id"],
                  data={"to": to_addr, "subject": subject, "application_id": application_id})
        return SendResult("sent", mid, mode, out_id)


def precheck(conn: sqlite3.Connection, opp: dict[str, Any], s: dict[str, Any]) -> list[str]:
    """Pre-submit recheck reasons (empty = go). Link and deadline are re-verified by the caller within 24 h."""
    reasons = []
    if s.get("global_pause"):
        reasons.append("PAUSE ALL is on")
    if s.get("freeze_outbound"):
        reasons.append("outbound is frozen")
    if opp.get("scam_status") in ("scam", "suspicious"):
        reasons.append(f"scam check: {opp['scam_status']}")
    if opp.get("link_status") == "dead":
        reasons.append("posting is no longer live")
    if opp.get("eligibility_status") == "ineligible":
        reasons.append("ineligible")
    return reasons
