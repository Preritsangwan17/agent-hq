"""The outbound guard (PLAN "Orchestrator › PAUSE ALL / Freeze outbound", CONTRACT_C §6, CONTRACT_D §3).

EVERY outbound email — application, follow-up, info reply, self-test — goes through `prepare()` + `send()`:
1. One BEGIN IMMEDIATE transaction re-reads PAUSE ALL, freeze-outbound, the owning agent's pause, the mode, the
   approval hash (approve-first), notify-only thread locks, the recipient rule, idempotency and the caps, then writes
   the `outbound_log` intent with a deterministic RFC 5322 Message-ID.
2. DRY RUN: the mock mailbox is the only channel and the send completes inside that transaction.
   SELF_TEST / LIVE: the message goes out through Gmail after the transaction commits.
3. The outcome is recorded. A refusal from Gmail marks the intent failed. An unknown outcome (timeout, 5xx,
   connection reset) is checked against Sent (`rfc822msgid:`); if it isn't there it becomes `ambiguous` + a Needs
   Prerit item, and HQ never retries it by itself. After a crash, `recover()` resolves leftover intents the same way
   before any task can send again.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from hq.db import repo, serializers
from hq import settings as paths
from hq.db.conn import dumps, tx
from hq.db.seed import get_settings
from hq.profile import owner as owner_profile
from hq.util import netguard
from hq.util.ids import new_id
from hq.util.timeutil import IST, now_iso, parse_iso, to_iso, today_ist, utcnow

PRERIT_EMAIL = owner_profile.email()  # sangwanprerit40@gmail.com (config/resume.yaml), fixed for the process lifetime
DOMAIN_WINDOW_DAYS = 14
LAB_DAILY_CAP = 3
SIGNOFF_BLOCK = f"Best regards,\n{owner_profile.name()}\n"
KINDS = ("application", "followup", "reply", "self_test")
CHANNEL = {"application": "email", "followup": "followup", "reply": "reply", "self_test": "self_test"}
OWNER = {"application": "applicant", "followup": "followup", "reply": "inbox"}
COUNTED = ("email", "followup", "reply")
LIVE_STATES = ("intent", "sent", "ambiguous")


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


@dataclass
class Prepared:
    kind: str
    outbound_id: str
    message_id: str
    mode: str
    to_addr: str
    subject: str
    body: str
    attachments: list[dict[str, Any]]
    application_id: str | None
    opportunity_id: str | None
    thread_row_id: str | None
    gmail_thread_id: str | None
    in_reply_to: str | None
    references: str | None
    agent_id: str
    task_id: str | None
    extra: dict[str, Any] = field(default_factory=dict)


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


def _hash_addr(addr: str) -> str:
    return hashlib.sha256(addr.strip().lower().encode()).hexdigest()[:16]


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


def check_caps(conn: sqlite3.Connection, s: dict[str, Any], to_addr: str, *, cold: bool = True) -> None:
    """Daily cap over every outbound email; the per-domain (1 per 14 days) and lab caps apply to cold outreach —
    follow-ups and replies on an existing thread are exempt from those two."""
    since = _day_start_utc()
    marks = ",".join("?" * len(COUNTED))
    sent_today = conn.execute(f"SELECT COUNT(*) FROM outbound_log WHERE channel IN ({marks}) AND status IN "
                              "('intent','sent','ambiguous') AND ts >= ?", (*COUNTED, since)).fetchone()[0]
    lab_path = paths.DATA / "email-module" / "live.db"
    lab_today = lab_cold = lab_school = 0
    if lab_path.exists():
        try:
            with closing(sqlite3.connect(lab_path)) as lab:
                states = "('sending','sent','ambiguous')"
                lab_today = lab.execute(f"SELECT COUNT(*) FROM drafts WHERE status IN {states} AND sent_at>=?", (since,)).fetchone()[0]
                if cold:
                    window = to_iso(utcnow() - timedelta(days=DOMAIN_WINDOW_DAYS))
                    lab_cold = lab.execute(f"SELECT COUNT(*) FROM drafts d JOIN applications a ON a.id=d.application_id WHERE d.kind='application' AND d.status IN {states} AND d.sent_at>=? AND lower(substr(a.email,instr(a.email,'@')+1))=?", (window, to_addr.split('@')[-1].lower())).fetchone()[0]
                    lab_school = lab.execute(f"SELECT COUNT(*) FROM drafts d JOIN applications a ON a.id=d.application_id WHERE d.kind='application' AND d.status IN {states} AND d.sent_at>=? AND (a.email LIKE '%.edu%' OR a.email LIKE '%.ac.%')", (since,)).fetchone()[0]
        except sqlite3.Error as exc:
            raise GuardBlocked(f"cannot read the email module ledger ({type(exc).__name__})", kind="cap") from None
    sent_today += lab_today
    if sent_today >= int(s.get("email_daily_cap", 10)):
        raise GuardBlocked(f"daily email cap reached ({sent_today}/{s.get('email_daily_cap')})", kind="cap")
    if not cold:
        return
    dom = to_addr.split("@")[-1].lower()
    window = to_iso(utcnow() - timedelta(days=DOMAIN_WINDOW_DAYS))
    if conn.execute("SELECT 1 FROM outbound_log WHERE channel='email' AND recipient_domain=? AND status IN "
                    "('intent','sent','ambiguous') AND ts >= ?", (dom, window)).fetchone():
        raise GuardBlocked(f"already emailed {dom} in the last {DOMAIN_WINDOW_DAYS} days", kind="cap")
    if lab_cold:
        raise GuardBlocked(f"email module already contacted {dom} in the last {DOMAIN_WINDOW_DAYS} days", kind="cap")
    if re.search(r"\.(edu|ac)(\.[a-z]{2})?$|\.edu\.[a-z]{2}$", dom):
        labs = conn.execute("SELECT COUNT(*) FROM outbound_log WHERE channel='email' AND status IN "
                            "('intent','sent','ambiguous') AND ts >= ? AND (recipient_domain LIKE '%.edu%' OR "
                            "recipient_domain LIKE '%.ac.%')", (since,)).fetchone()[0]
        labs += lab_school
        if labs >= LAB_DAILY_CAP:
            raise GuardBlocked(f"daily cap of {LAB_DAILY_CAP} lab emails reached", kind="cap")


def effective_mode(s: dict[str, Any]) -> str:
    env = netguard.current_mode()
    return "dry_run" if env == "dry_run" else s.get("mode", "dry_run")


def _row(conn: sqlite3.Connection, sql: str, args: tuple) -> dict[str, Any] | None:
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


# ── step 1: checks + intent ──────────────────────────────────────────────────────────────────────────
def prepare(conn: sqlite3.Connection, *, kind: str, to_addr: str, subject: str, body: str,
            attachments: list[dict[str, Any]], content_sha: str, application_id: str | None = None,
            thread_id: str | None = None, agent_id: str = "applicant", task_id: str | None = None,
            require_dry_run: bool = False) -> Prepared | SendResult:
    if kind not in KINDS:
        raise ValueError(f"unknown outbound kind {kind!r}")
    to_addr = to_addr.strip()
    with tx(conn):
        s = get_settings(conn)
        if s.get("global_pause"):
            raise GuardBlocked("PAUSE ALL is on", kind="paused")
        if s.get("freeze_outbound"):
            raise GuardBlocked("outbound is frozen", kind="paused")
        owner = OWNER.get(kind)
        ag = _row(conn, "SELECT paused, enabled FROM agents WHERE id=?", (owner,)) if owner else None
        if ag and (ag["paused"] or not ag["enabled"]):
            raise GuardBlocked(f"the {owner} agent is paused", kind="paused")
        app = _row(conn, "SELECT * FROM applications WHERE id=?", (application_id,)) if application_id else None
        if kind in ("application", "followup") and app is None:
            raise GuardBlocked("application not found")
        thread = _row(conn, "SELECT * FROM email_threads WHERE id=?", (thread_id,)) if thread_id else (
            _row(conn, "SELECT * FROM email_threads WHERE application_id=? ORDER BY COALESCE(last_message_at,'') DESC "
                       "LIMIT 1", (application_id,)) if application_id else None)
        if kind == "reply" and thread is None:
            raise GuardBlocked("reply without a thread")
        opp_id = (app or {}).get("opportunity_id") or (thread or {}).get("opportunity_id")
        opp = _row(conn, "SELECT * FROM opportunities WHERE id=?", (opp_id,)) if opp_id else None
        if kind == "self_test":
            if netguard.current_mode() == "dry_run":
                raise GuardBlocked("the self-test needs the go-live .env step (HQ_FORCE_DRY_RUN=0) and a restart",
                                   kind="mode")
            mode = "self_test"
        else:
            mode = effective_mode(s)
        if require_dry_run and mode != "dry_run":
            raise GuardBlocked(f"mode {mode}: sends must go through guard.send()", kind="mode")
        key = application_id if kind == "application" else f"{kind}:{application_id or (thread or {}).get('id') or ''}"
        mid = message_id_for(key, content_sha)
        dup = _row(conn, "SELECT id, message_id FROM outbound_log WHERE message_id=? AND status IN "
                         "('intent','sent','ambiguous')", (mid,))
        if dup is None and kind in ("application", "followup"):
            dup = _row(conn, "SELECT id, message_id FROM outbound_log WHERE application_id=? AND channel=? AND status "
                             "IN ('intent','sent','ambiguous')", (application_id, CHANNEL[kind]))
        if dup:
            return SendResult("duplicate", dup["message_id"], mode, dup["id"])
        if kind == "application" and s.get("autonomy") == "approve_first" and app["approval_sha256"] != content_sha:
            raise GuardBlocked("waiting for Prerit's approval of this exact text", kind="approval")
        if thread and thread.get("notify_only_lock"):
            raise GuardBlocked(f"the thread is notify-only locked ({thread.get('lock_reason') or 'lock'}) — "
                               "HQ never writes on it", kind="locked")
        ok, why = _recipient_rule(conn, kind, opp, app, thread, to_addr)
        if not ok:
            raise GuardBlocked(why, kind="recipient")
        if mode == "self_test" and to_addr.lower() != PRERIT_EMAIL:
            raise GuardBlocked("SELF-TEST only sends to Prerit's own address", kind="mode")
        account = ((s.get("gmail_state") or {}).get("email") or "").strip().lower()
        if mode != "dry_run" and account and account != PRERIT_EMAIL:
            raise GuardBlocked(f"the connected Gmail account is {account}, not {PRERIT_EMAIL} — HQ only sends as "
                               "Prerit (reconnect Gmail with the right account)", kind="mode")
        if kind != "self_test":
            check_caps(conn, s, to_addr, cold=kind == "application")
        out_id = new_id()
        conn.execute("INSERT INTO outbound_log(id, channel, recipient_domain, recipient_hash, application_id, mode, "
                     "message_id, status, ts, thread_id, subject) VALUES (?,?,?,?,?,?,?, 'intent', ?,?,?)",
                     (out_id, CHANNEL[kind], to_addr.split("@")[-1].lower(), _hash_addr(to_addr), application_id,
                      mode, mid, now_iso(), (thread or {}).get("id"), subject[:200]))
        last_in = _row(conn, "SELECT rfc822_message_id, subject FROM email_messages WHERE thread_id=? AND "
                             "direction='inbound' ORDER BY COALESCE(date,'') DESC LIMIT 1",
                       ((thread or {}).get("id"),)) if thread else None
        first_out = _row(conn, "SELECT message_id FROM outbound_log WHERE application_id=? AND channel='email' AND "
                               "status='sent' ORDER BY ts LIMIT 1", (application_id,)) if kind == "followup" else None
        in_reply_to = (last_in or {}).get("rfc822_message_id") or (first_out or {}).get("message_id")
        p = Prepared(kind=kind, outbound_id=out_id, message_id=mid, mode=mode, to_addr=to_addr, subject=subject,
                     body=body, attachments=attachments, application_id=application_id, opportunity_id=opp_id,
                     thread_row_id=(thread or {}).get("id"), gmail_thread_id=_real_thread_id(thread),
                     in_reply_to=in_reply_to if kind in ("reply", "followup") else None,
                     references=in_reply_to if kind in ("reply", "followup") else None, agent_id=agent_id,
                     task_id=task_id)
        if mode == "dry_run":
            conn.execute("INSERT INTO mock_mailbox(id, to_addr, subject, body, attachments_json, in_reply_to, "
                         "application_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                         (new_id(), to_addr, subject, body, dumps(attachments), p.in_reply_to, application_id,
                          now_iso()))
            _record_sent(conn, p, gmail_id=None, gmail_thread_id=None)
            return SendResult("sent", mid, mode, out_id)
        return p


def _real_thread_id(thread: dict[str, Any] | None) -> str | None:
    """The Gmail thread to send into (dry-run threads are named mock-… and don't exist in Gmail)."""
    gid = (thread or {}).get("gmail_thread_id") or ""
    return gid if gid and not gid.startswith(("mock-", "sim-")) else None


def _recipient_rule(conn: sqlite3.Connection, kind: str, opp: dict[str, Any] | None, app: dict[str, Any] | None,
                    thread: dict[str, Any] | None, to_addr: str) -> tuple[bool, str]:
    to = to_addr.lower()
    if kind == "self_test":
        return (to == PRERIT_EMAIL, "the self-test only goes to Prerit's own address")
    if kind == "application":
        return recipient_ok(opp or {}, to_addr)
    if kind == "reply":
        want = ((thread or {}).get("counterpart_addr") or "").lower()
        return (bool(want) and to == want, "a reply only goes to the address that wrote to Prerit")
    first = _row(conn, "SELECT recipient_hash FROM outbound_log WHERE application_id=? AND channel='email' AND "
                       "status='sent' ORDER BY ts LIMIT 1", ((app or {}).get("id"),))
    if first and first["recipient_hash"] == _hash_addr(to):
        return True, "same address as the application"
    want = ((thread or {}).get("counterpart_addr") or "").lower()
    if want and to == want:
        return True, "the recruiter who wrote on this thread"
    return False, "a follow-up only goes to the address the application was sent to (or the recruiter on the thread)"


# ── step 3: record ───────────────────────────────────────────────────────────────────────────────────
def _record_sent(conn: sqlite3.Connection, p: Prepared, *, gmail_id: str | None, gmail_thread_id: str | None) -> None:
    """Caller owns the transaction."""
    now = now_iso()
    conn.execute("UPDATE outbound_log SET status='sent', gmail_id=?, error=NULL WHERE id=?", (gmail_id, p.outbound_id))
    thread_row = p.thread_row_id
    if p.kind in ("application", "followup") and p.application_id:
        existing = _row(conn, "SELECT id, gmail_thread_id FROM email_threads WHERE application_id=? ORDER BY "
                              "COALESCE(last_message_at,'') DESC LIMIT 1", (p.application_id,))
        if existing:
            thread_row = existing["id"]
            if gmail_thread_id and (existing["gmail_thread_id"] or "").startswith("mock-"):
                conn.execute("UPDATE email_threads SET gmail_thread_id=? WHERE id=?", (gmail_thread_id, thread_row))
        else:
            thread_row = new_id()
            conn.execute("INSERT INTO email_threads(id, gmail_thread_id, opportunity_id, application_id, subject, "
                         "counterpart_domain, counterpart_addr, status, created_at, last_message_at) VALUES "
                         "(?,?,?,?,?,?,?, 'open', ?, ?)",
                         (thread_row, gmail_thread_id or f"mock-{p.application_id}", p.opportunity_id,
                          p.application_id, p.subject[:300], p.to_addr.split("@")[-1].lower(), p.to_addr.lower(),
                          now, now))
    if thread_row:
        conn.execute("INSERT INTO email_messages(id, gmail_message_id, thread_id, direction, from_addr, to_addr, date, "
                     "subject, snippet, rfc822_message_id, in_reply_to, body_text) "
                     "VALUES (?,?,?, 'outbound', ?,?,?,?,?,?,?,?)",
                     (new_id(), gmail_id or f"mock-{p.outbound_id}", thread_row, PRERIT_EMAIL, p.to_addr, now,
                      p.subject[:300], p.body[:200], p.message_id, p.in_reply_to, p.body))
        conn.execute("UPDATE email_threads SET last_message_at=? WHERE id=?", (now, thread_row))
    if p.kind == "application" and p.application_id:
        conn.execute("UPDATE applications SET status='submitted', submitted_at=?, message_id=?, mode=?, "
                     "submission_ref=?, gmail_thread_id=COALESCE(?, gmail_thread_id), updated_at=? WHERE id=?",
                     (now, p.message_id, p.mode, "mock_mailbox" if p.mode == "dry_run" else f"gmail:{gmail_id}",
                      gmail_thread_id, now, p.application_id))
    if p.kind == "followup" and p.application_id:
        conn.execute("UPDATE followups SET status='sent', outbound_id=?, reason=NULL, updated_at=? WHERE "
                     "application_id=?", (p.outbound_id, now, p.application_id))
    how = "Mock mail" if p.mode == "dry_run" else "Sent"
    tail = " (dry run — nothing left this Mac)" if p.mode == "dry_run" else f" via Gmail ({p.mode.replace('_', '-')})"
    repo.emit(conn, "mail.mock_sent" if p.mode == "dry_run" else "mail.sent",
              f"{how} → {p.to_addr}: {p.subject}{tail}", agent_id=p.agent_id, task_id=p.task_id,
              opportunity_id=p.opportunity_id,
              data={"to": p.to_addr, "subject": p.subject, "application_id": p.application_id, "kind": p.kind,
                    "mode": p.mode, "message_id": p.message_id})


def _mark(conn: sqlite3.Connection, p: Prepared | dict[str, Any], status: str, error: str) -> None:
    out_id = p.outbound_id if isinstance(p, Prepared) else p["id"]
    conn.execute("UPDATE outbound_log SET status=?, error=? WHERE id=?", (status, error[:500], out_id))


def _ambiguous_need(conn: sqlite3.Connection, out: dict[str, Any], reason: str) -> None:
    title = f"Check Sent: did “{(out.get('subject') or 'an email')[:80]}” go out?"
    if conn.execute("SELECT 1 FROM needs_prerit WHERE status IN ('open','snoozed') AND "
                    "json_extract(payload_json,'$.outbound_id')=?", (out["id"],)).fetchone():
        return
    app = _row(conn, "SELECT opportunity_id FROM applications WHERE id=?", (out.get("application_id"),))
    need_id = repo.insert_need(conn, {
        "kind": "decision", "title": title, "priority": 85, "est_minutes": 1,
        "opportunity_id": (app or {}).get("opportunity_id"), "application_id": out.get("application_id"),
        "instructions_md": (f"Gmail didn't confirm this send ({reason}). HQ never resends on its own.\n\nOpen Gmail › "
                            f"Sent and search for:\n\n```\nrfc822msgid:{(out.get('message_id') or '').strip('<>')}\n```"
                            "\n\nThen tell HQ what you found."),
        "direct_url": "https://mail.google.com/mail/u/0/#sent",
        "payload_json": dumps({"decision": "outbound_ambiguous", "outbound_id": out["id"],
                               "options": [{"value": "sent", "label": "It was sent"},
                                           {"value": "not_sent", "label": "It wasn't sent"}]})})
    need = serializers.need_json(repo.get_need_row(conn, need_id))
    repo.emit(conn, "needs.created", need["title"], level="warn", data={"need": need})


# ── step 2: deliver ──────────────────────────────────────────────────────────────────────────────────
async def send(conn: sqlite3.Connection, gmail: Any, **kw: Any) -> SendResult:
    """prepare → (DRY RUN done) → Gmail → record. Raises GuardBlocked (kinds: paused, approval, locked, recipient,
    cap, mode, failed, ambiguous)."""
    from hq.gmail.api import GmailAuthError, GmailError
    from hq.gmail.sender import build_mime

    p = prepare(conn, **kw)
    if isinstance(p, SendResult):
        return p
    if gmail is None:
        with tx(conn):
            _mark(conn, p, "failed", "Gmail is not connected")
        raise GuardBlocked("Gmail is not connected", kind="failed")
    raw = build_mime(from_addr=PRERIT_EMAIL, to_addr=p.to_addr, subject=p.subject, body=p.body,
                     message_id=p.message_id, attachments=p.attachments, in_reply_to=p.in_reply_to,
                     references=p.references)
    try:
        res = await gmail.send(raw, thread_id=p.gmail_thread_id)
    except GmailAuthError as exc:  # the token refresh failed before anything was sent
        with tx(conn):
            _mark(conn, p, "failed", str(exc))
        raise GuardBlocked(str(exc), kind="failed") from exc
    except GmailError as exc:      # Gmail answered and refused: definitely not sent
        with tx(conn):
            _mark(conn, p, "failed", exc.reason)
        raise GuardBlocked(f"Gmail refused the message: {exc.reason}", kind="failed") from exc
    except Exception as exc:       # unknown outcome: look in Sent before anything else
        found = await _find_in_sent(gmail, p.message_id)
        with tx(conn):
            if found:
                _record_sent(conn, p, gmail_id=found["id"], gmail_thread_id=found.get("threadId"))
            else:
                _mark(conn, p, "ambiguous", str(exc) or type(exc).__name__)
                _ambiguous_need(conn, _row(conn, "SELECT * FROM outbound_log WHERE id=?", (p.outbound_id,)) or {},
                                str(exc) or type(exc).__name__)
        if found:
            return SendResult("sent", p.message_id, p.mode, p.outbound_id)
        raise GuardBlocked("Gmail didn't confirm the send — waiting for Prerit to check Sent", kind="ambiguous") \
            from exc
    with tx(conn):
        _record_sent(conn, p, gmail_id=res.get("id"), gmail_thread_id=res.get("threadId"))
    return SendResult("sent", p.message_id, p.mode, p.outbound_id)


async def _find_in_sent(gmail: Any, message_id: str, attempts: int = 2, delay_s: float = 1.5) -> dict | None:
    q = f"in:sent rfc822msgid:{message_id.strip('<>')}"
    for i in range(attempts):
        try:
            res = await gmail.list_messages(q, max_results=1)
        except Exception:  # noqa: BLE001 — search failure means "don't know", never "not sent"
            return None
        if res.get("messages"):
            return res["messages"][0]
        if i + 1 < attempts:
            await asyncio.sleep(delay_s)
    return None


def _prepared_from_row(conn: sqlite3.Connection, out: dict[str, Any]) -> Prepared:
    """Rebuild enough of a send from its outbound_log row to record it (the log keeps only a hash of the address;
    the thread keeps the counterpart)."""
    kind = {v: k for k, v in CHANNEL.items()}.get(out["channel"], "application")
    app = _row(conn, "SELECT opportunity_id FROM applications WHERE id=?", (out.get("application_id"),))
    thread = _row(conn, "SELECT counterpart_addr FROM email_threads WHERE id=?", (out.get("thread_id"),)) or {}
    return Prepared(kind=kind, outbound_id=out["id"], message_id=out["message_id"], mode=out["mode"],
                    to_addr=thread.get("counterpart_addr") or f"recipient@{out.get('recipient_domain')}",
                    subject=out.get("subject") or "", body="", attachments=[], application_id=out.get("application_id"),
                    opportunity_id=(app or {}).get("opportunity_id"), thread_row_id=out.get("thread_id"),
                    gmail_thread_id=None, in_reply_to=None, references=None, agent_id="system", task_id=None)


async def recover(conn: sqlite3.Connection, gmail: Any, *, older_than_s: float = 120.0) -> dict[str, int]:
    """Resolve intents left by a crash (status 'intent', not dry run): found in Sent → sent; not in Sent → failed,
    so the task's normal retry may send it (same Message-ID); Sent unreachable for over an hour → ambiguous + Needs."""
    cutoff = to_iso(utcnow() - timedelta(seconds=older_than_s))
    rows = [dict(r) for r in conn.execute("SELECT * FROM outbound_log WHERE status='intent' AND mode!='dry_run' AND "
                                          "ts <= ? ORDER BY ts", (cutoff,))]
    out = {"sent": 0, "failed": 0, "ambiguous": 0}
    for row in rows:
        found = None
        searched = False
        if gmail is not None:
            try:
                res = await gmail.list_messages(f"in:sent rfc822msgid:{row['message_id'].strip('<>')}", max_results=1)
                searched = True
                found = (res.get("messages") or [None])[0]
            except Exception:  # noqa: BLE001
                searched = False
        with tx(conn):
            if found:
                p = _prepared_from_row(conn, row)
                _record_sent(conn, p, gmail_id=found["id"], gmail_thread_id=found.get("threadId"))
                out["sent"] += 1
            elif searched:
                _mark(conn, row, "failed", "not in Sent after a crash — safe to send again")
                out["failed"] += 1
            elif (parse_iso(row["ts"]) or utcnow()) < utcnow() - timedelta(hours=1):
                _mark(conn, row, "ambiguous", "could not check Sent for an hour after a crash")
                _ambiguous_need(conn, row, "the worker stopped mid-send and Gmail couldn't be checked")
                out["ambiguous"] += 1
    return out


def resolve_ambiguous(conn: sqlite3.Connection, outbound_id: str, sent: bool) -> None:
    """Prerit's answer to a 'did it go out?' item. Caller owns the transaction."""
    row = _row(conn, "SELECT * FROM outbound_log WHERE id=?", (outbound_id,))
    if row is None or row["status"] != "ambiguous":
        return
    if sent:
        p = _prepared_from_row(conn, row)
        _record_sent(conn, p, gmail_id=None, gmail_thread_id=None)
    else:
        _mark(conn, row, "failed", "Prerit: not in Sent")


# ── wrappers ─────────────────────────────────────────────────────────────────────────────────────────
def send_email(conn: sqlite3.Connection, *, application_id: str, to_addr: str, subject: str, body: str,
               attachments: list[dict[str, str]], content_sha: str, agent_id: str = "applicant",
               task_id: str | None = None) -> SendResult:
    """Synchronous DRY-RUN application send (the mock mailbox). Other modes must use `send()`."""
    res = prepare(conn, kind="application", to_addr=to_addr, subject=subject, body=body, attachments=attachments,
                  content_sha=content_sha, application_id=application_id, agent_id=agent_id, task_id=task_id,
                  require_dry_run=True)
    assert isinstance(res, SendResult)
    return res


async def self_test(conn: sqlite3.Connection, gmail: Any) -> SendResult:
    sha = hashlib.sha256(f"self-test:{now_iso()}".encode()).hexdigest()
    body = ("This is Agent HQ's self-test. If you can read this, the Gmail send path works.\n\n"
            "SELF-TEST mode can only ever write to this address; nothing goes to anyone else until you type GO LIVE.\n"
            "\n– Agent HQ")
    return await send(conn, gmail, kind="self_test", to_addr=PRERIT_EMAIL, subject="Agent HQ self-test", body=body,
                      attachments=[], content_sha=sha, agent_id="system")


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
