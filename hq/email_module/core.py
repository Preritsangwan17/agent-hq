"""Opt-in email workflow with its own SQLite ledger and an injected Gmail API.

The default transport is FakeGmail. Live delivery needs both an injected Gmail
client and a caller supplied policy gate; creating a draft never sends mail.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from hq.gmail.api import GmailError, GmailMessage, GmailNotFound, GmailTransient
from hq.gmail.fake import FakeGmail

UTC = timezone.utc
MAX_PER_DAY = 10
MIN_GAP_SECONDS = 60
FOLLOWUP_DAYS = 7
MAX_FOLLOWUPS = 2
COMPANY_COOLDOWN_DAYS = 14
SEARCH_QUERY = '(job OR internship OR application OR recruiter OR interview OR assessment OR follow-up) -in:chats -in:drafts'
TERMINAL = {"rejected", "withdrawn", "accepted", "unsubscribed", "bounced"}
STATUSES = {"found", "researching", "prepared", "drafted", "applied", "replied", "interview", "assessment", "offer", *TERMINAL}
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
DATE_RE = re.compile(r"\b(?:deadline|due(?: by)?|complete by)\s*[:\-]?\s*([A-Za-z]+\s+\d{1,2}(?:,?\s+20\d{2})?|20\d{2}-\d{2}-\d{2})", re.I)


class EmailModuleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _utc(value: datetime | None = None) -> datetime:
    return (value or datetime.now(UTC)).astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _email(value: str) -> str:
    name, addr = parseaddr(value.strip())
    if name or addr != value.strip() or len(addr) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", addr):
        raise EmailModuleError("invalid_recipient", "Enter one valid recipient email address")
    return addr.lower()


def _clean(value: Any, limit: int = 2000) -> str:
    text = str(value or "").strip()
    if len(text) > limit or "\r" in text or "\x00" in text:
        raise EmailModuleError("invalid_text", "A field is too long or contains invalid characters")
    return text


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for field in ("links", "deadlines", "profile"):
        if field in item:
            item[field] = json.loads(item[field] or ("{}" if field == "profile" else "[]"))
    if "approved" in item:
        item["approved"] = bool(item["approved"])
    if "reply_received" in item:
        item["reply_received"] = bool(item["reply_received"])
    return item


def _classify(msg: GmailMessage) -> str:
    text = (msg.subject + "\n" + msg.body_text[:5000]).lower()
    if msg.headers.get("list-unsubscribe") or re.search(r"\b(?:unsubscribe|do not contact|remove me)\b", text):
        return "unsubscribed"
    if re.search(r"\b(?:delivery failed|undeliverable|address not found|mail delivery subsystem)\b", text):
        return "bounced"
    if re.search(r"\b(?:out of office|automatic reply|auto-reply|autoreply)\b", text):
        return "auto_reply"
    if re.search(r"\b(?:we regret|unfortunately|not (?:moving|proceeding|selected)|other candidates)\b", text):
        return "rejected"
    if re.search(r"\b(?:offer letter|pleased to offer|job offer)\b", text):
        return "offer"
    if re.search(r"\b(?:assessment|coding test|take-home|online test)\b", text):
        return "assessment"
    if re.search(r"\b(?:interview|schedule a call|meet with)\b", text):
        return "interview"
    return "replied"


def _relevant_fact(profile: dict[str, str], role: str, job_description: str) -> str:
    """Choose only among supplied facts; no new experience is synthesized."""
    stop = {"the", "and", "for", "with", "using", "role", "work", "intern", "internship", "job", "at", "in", "on"}
    wanted = {w for w in re.findall(r"[a-z]{3,}", f"{role} {job_description}".lower()) if w not in stop}
    return max(profile.values(), key=lambda fact: len(wanted & set(re.findall(r"[a-z]{3,}", fact.lower()))))


class EmailModule:
    def __init__(self, db_path: Path | str, gmail: Any = None, *, owner_email: str = "sandbox@example.test",
                 owner_name: str = "Applicant", mode: str = "sandbox", now: Callable[[], datetime] | None = None,
                 allow_send: Callable[[], bool] | None = None,
                 recipient_policy: Callable[[dict[str, Any]], bool] | None = None):
        if mode not in ("sandbox", "live"):
            raise ValueError("mode must be sandbox or live")
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        self.owner_email = _email(owner_email)
        self.owner_name = _clean(owner_name, 100)
        self.mode = mode
        self.gmail = gmail if gmail is not None else (FakeGmail(address=self.owner_email, scopes=("gmail.readonly", "gmail.send", "gmail.compose")) if mode == "sandbox" else None)
        self.now = now or (lambda: datetime.now(UTC))
        self.allow_send = allow_send or (lambda: False)
        self.recipient_policy = recipient_policy or (lambda app: False)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS applications (
                  id TEXT PRIMARY KEY, source_opportunity_id TEXT UNIQUE, company TEXT NOT NULL,
                  company_key TEXT NOT NULL, role TEXT NOT NULL, contact_name TEXT NOT NULL,
                  email TEXT NOT NULL, status TEXT NOT NULL, research TEXT NOT NULL,
                  job_description TEXT NOT NULL, profile TEXT NOT NULL, last_email_sent TEXT,
                  reply_received INTEGER NOT NULL DEFAULT 0, next_followup_at TEXT,
                  followup_count INTEGER NOT NULL DEFAULT 0, links TEXT NOT NULL DEFAULT '[]',
                  deadlines TEXT NOT NULL DEFAULT '[]', gmail_thread_id TEXT,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_email_contact ON applications(company_key,email);
                CREATE TABLE IF NOT EXISTS drafts (
                  id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
                  kind TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
                  content_sha TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'draft', message_id TEXT UNIQUE,
                  gmail_message_id TEXT, error TEXT, created_at TEXT NOT NULL, sent_at TEXT);
                CREATE TABLE IF NOT EXISTS messages (
                  gmail_id TEXT PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
                  thread_id TEXT, direction TEXT NOT NULL, from_addr TEXT NOT NULL,
                  to_addr TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
                  rfc822_id TEXT, in_reply_to TEXT, classification TEXT,
                  received_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, application_id TEXT,
                  kind TEXT NOT NULL, detail TEXT NOT NULL, at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_messages_app ON messages(application_id,received_at);
                CREATE INDEX IF NOT EXISTS idx_drafts_app ON drafts(application_id,created_at);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            yield db
        finally:
            db.close()

    def _at(self) -> str:
        return _iso(self.now())

    def _event(self, db: sqlite3.Connection, app_id: str | None, kind: str, detail: str) -> None:
        db.execute("INSERT INTO events(application_id,kind,detail,at) VALUES (?,?,?,?)", (app_id, kind, detail, self._at()))

    def create_application(self, data: dict[str, Any]) -> dict[str, Any]:
        company = _clean(data.get("company"), 200)
        role = _clean(data.get("role"), 200)
        contact = _clean(data.get("contact_name"), 100)
        if not company or not role:
            raise EmailModuleError("missing_fields", "Company and role are required")
        addr = _email(str(data.get("email") or ""))
        research = _clean(data.get("research"), 6000)
        jd = _clean(data.get("job_description"), 12000)
        profile = data.get("profile") or {}
        if not isinstance(profile, dict):
            raise EmailModuleError("invalid_profile", "Profile must contain verified facts")
        profile = {str(k): _clean(v, 500) for k, v in profile.items() if v}
        source_id = _clean(data.get("source_opportunity_id"), 100) or None
        key = re.sub(r"[^a-z0-9]", "", company.casefold())
        if len(key) < 2:
            raise EmailModuleError("invalid_company", "Enter a company name")
        app_id, at = uuid.uuid4().hex, self._at()
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO applications(id,source_opportunity_id,company,company_key,role,contact_name,email,status,research,job_description,profile,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (app_id, source_id, company, key, role, contact, addr, "found", research, jd, json.dumps(profile), at, at))
                self._event(db, app_id, "found", "Application contact recorded")
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                raise EmailModuleError("duplicate_contact", "This company and contact already have an application record") from None
        return self.application(app_id)["application"]

    def application(self, app_id: str) -> dict[str, Any]:
        with self._db() as db:
            app = _row(db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone())
            if app is None:
                raise EmailModuleError("not_found", "Application not found")
            return {"application": app,
                    "drafts": [_row(r) for r in db.execute("SELECT * FROM drafts WHERE application_id=? ORDER BY created_at DESC", (app_id,))],
                    "messages": [dict(r) for r in db.execute("SELECT * FROM messages WHERE application_id=? ORDER BY received_at,gmail_id", (app_id,))],
                    "events": [dict(r) for r in db.execute("SELECT * FROM events WHERE application_id=? ORDER BY id", (app_id,))]}

    def dashboard(self) -> dict[str, Any]:
        with self._db() as db:
            apps = [_row(r) for r in db.execute("SELECT * FROM applications ORDER BY updated_at DESC,company")]
            counts = {"applications": len(apps), "waiting": sum(a["status"] == "applied" for a in apps),
                      "replies": sum(a["reply_received"] for a in apps),
                      "followups_due": len(self.due_followups())}
        return {"mode": self.mode, "connected": self.gmail is not None, "applications": apps,
                "counts": counts, "policy": {"per_day": MAX_PER_DAY, "minimum_gap_seconds": MIN_GAP_SECONDS,
                "followup_after_days": FOLLOWUP_DAYS, "maximum_followups": MAX_FOLLOWUPS,
                "company_cooldown_days": COMPANY_COOLDOWN_DAYS, "approval_required": True}}

    def due_followups(self) -> list[dict[str, Any]]:
        with self._db() as db:
            return [_row(r) for r in db.execute("SELECT * FROM applications WHERE next_followup_at<=? AND status='applied' AND reply_received=0 AND followup_count<? ORDER BY next_followup_at", (self._at(), MAX_FOLLOWUPS))]

    def update_application(self, app_id: str, data: dict[str, Any]) -> dict[str, Any]:
        allowed = {"contact_name", "research", "job_description", "profile", "status"}
        if set(data) - allowed:
            raise EmailModuleError("invalid_update", "Only contact, research, job description, profile and status may be edited")
        old = self.application(app_id)["application"]
        values = {}
        for k, v in data.items():
            if k == "status":
                if v not in STATUSES:
                    raise EmailModuleError("invalid_status", "Unknown application status")
                values[k] = v
            elif k == "profile":
                if not isinstance(v, dict):
                    raise EmailModuleError("invalid_profile", "Profile must contain verified facts")
                values[k] = json.dumps({str(a): _clean(b, 500) for a, b in v.items() if b})
            else:
                values[k] = _clean(v, 12000 if k == "job_description" else 6000)
        if not values:
            return old
        values["updated_at"] = self._at()
        if values.get("status") in TERMINAL or values.get("status") in {"replied", "interview", "assessment", "offer"}:
            values["next_followup_at"] = None
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE applications SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?", (*values.values(), app_id))
            self._event(db, app_id, "updated", ", ".join(data))
            db.commit()
        return self.application(app_id)["application"]

    def _draft_content(self, app: dict[str, Any], kind: str) -> tuple[str, str]:
        if kind not in ("application", "followup", "reply"):
            raise EmailModuleError("invalid_kind", "Draft kind must be application, followup or reply")
        if kind == "followup" and (app["status"] != "applied" or app["reply_received"] or app["followup_count"] >= MAX_FOLLOWUPS or not app["next_followup_at"] or _parse(app["next_followup_at"]) > _utc(self.now())):
            raise EmailModuleError("followup_not_due", "A follow-up is not due for this application")
        if app["status"] in TERMINAL:
            raise EmailModuleError("terminal", "No email may be drafted for a closed application")
        greeting = f"Dear {app['contact_name'].split()[0]}," if app["contact_name"] else "Dear Hiring Team,"
        signoff = f"Best regards,\n{self.owner_name}"
        subject = f"Application for {app['role']} at {app['company']}"
        if kind == "application":
            if not app["research"] or not app["job_description"] or not app["profile"]:
                raise EmailModuleError("insufficient_context", "Add company research, the job description and verified profile facts before drafting")
            research = re.split(r"[.!?\n]", app["research"])[0].strip()[:240]
            requirement = re.split(r"[.!?\n]", app["job_description"])[0].strip()[:240]
            fact = _relevant_fact(app["profile"], app["role"], app["job_description"])
            body = f"{greeting}\n\nI am writing about the {app['role']} opportunity at {app['company']}. Your work caught my attention: {research.rstrip('.')}. I noted that the role asks for {requirement.rstrip('.')}.\n\nMy background includes {fact.rstrip('.')}. I would welcome the chance to discuss how this relates to the role.\n\nThank you for considering my application.\n\n{signoff}"
        elif kind == "followup":
            subject = f"Re: {subject}"
            body = f"{greeting}\n\nI wanted to follow up on my application for the {app['role']} role at {app['company']}. I remain interested and would be glad to share any other information you need.\n\nThank you for your time.\n\n{signoff}"
        else:
            if not app["reply_received"]:
                raise EmailModuleError("no_reply", "There is no company reply to answer")
            subject = f"Re: {subject}"
            body = f"{greeting}\n\nThank you for your message about the {app['role']} role at {app['company']}. I have received it and will review the details.\n\n{signoff}"
        return subject, body

    async def draft(self, application_id: str, kind: str = "application") -> dict[str, Any]:
        app = self.application(application_id)["application"]
        subject, body = self._draft_content(app, kind)
        draft_id, at = uuid.uuid4().hex, self._at()
        sha = hashlib.sha256((app["email"] + "\0" + subject + "\0" + body).encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO drafts(id,application_id,kind,subject,body,content_sha,created_at) VALUES (?,?,?,?,?,?,?)",
                       (draft_id, application_id, kind, subject, body, sha, at))
            if app["status"] in {"found", "researching", "prepared"}:
                db.execute("UPDATE applications SET status='drafted',updated_at=? WHERE id=?", (at, application_id))
            self._event(db, application_id, "drafted", kind)
            db.commit()
        return self.draft_record(draft_id)

    def draft_record(self, draft_id: str) -> dict[str, Any]:
        with self._db() as db:
            item = _row(db.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone())
        if item is None:
            raise EmailModuleError("not_found", "Draft not found")
        return item

    def approve(self, draft_id: str) -> dict[str, Any]:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
            if row is None:
                db.rollback()
                raise EmailModuleError("not_found", "Draft not found")
            if row["status"] != "draft":
                db.rollback()
                raise EmailModuleError("not_draft", "Only an unsent draft can be approved")
            db.execute("UPDATE drafts SET approved=1,status='approved' WHERE id=?", (draft_id,))
            self._event(db, row["application_id"], "approved", draft_id)
            db.commit()
        return self.draft_record(draft_id)

    async def _sent_match(self, rfc_id: str) -> GmailMessage | None:
        result = await self.gmail.list_messages("in:sent rfc822msgid:" + rfc_id.strip("<>"), max_results=20)
        for item in result.get("messages") or []:
            msg = await self.gmail.get_message(item["id"])
            if msg.is_sent and msg.rfc822_id == rfc_id and self.owner_email == msg.from_addr:
                return msg
        return None

    async def send(self, draft_id: str) -> dict[str, Any]:
        if self.gmail is None:
            raise EmailModuleError("gmail_disconnected", "Connect Gmail before sending")
        if self.mode == "live":
            if not self.allow_send():
                raise EmailModuleError("send_disabled", "Live send is disabled by the application policy")
            profile = await self.gmail.profile()
            if (profile.get("emailAddress") or "").lower() != self.owner_email:
                raise EmailModuleError("account_mismatch", "Connected Gmail account does not match the owner")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            draft = db.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
            if draft is None:
                db.rollback()
                raise EmailModuleError("not_found", "Draft not found")
            if draft["status"] == "sent":
                db.rollback()
                return self.draft_record(draft_id)
            if draft["status"] != "approved" or not draft["approved"]:
                db.rollback()
                raise EmailModuleError("not_approved", "Review and approve this exact draft before sending")
            app = db.execute("SELECT * FROM applications WHERE id=?", (draft["application_id"],)).fetchone()
            if self.mode == "live" and not self.recipient_policy(dict(app)):
                db.rollback()
                raise EmailModuleError("recipient_unverified", "Recipient must match a verified email on the linked job posting")
            if app["status"] in TERMINAL or (draft["kind"] == "application" and app["status"] not in {"found", "researching", "prepared", "drafted"}) or (draft["kind"] == "followup" and (app["status"] != "applied" or app["reply_received"] or app["followup_count"] >= MAX_FOLLOWUPS or not app["next_followup_at"] or _parse(app["next_followup_at"]) > _utc(self.now()))):
                db.rollback()
                raise EmailModuleError("no_longer_eligible", "Application is no longer eligible for this email")
            if draft["kind"] == "application" and db.execute("SELECT 1 FROM drafts WHERE application_id=? AND kind='application' AND status IN ('sent','sending','ambiguous') LIMIT 1", (app["id"],)).fetchone():
                db.rollback()
                raise EmailModuleError("duplicate_application", "An application email has already been sent or may have been sent")
            if draft["kind"] == "followup" and db.execute("SELECT 1 FROM drafts WHERE application_id=? AND kind='followup' AND status IN ('sending','ambiguous') LIMIT 1", (app["id"],)).fetchone():
                db.rollback()
                raise EmailModuleError("duplicate_followup", "Another follow-up may already be in progress")
            now = _utc(self.now())
            day_start = _iso(now.replace(hour=0, minute=0, second=0, microsecond=0))
            total = db.execute("SELECT COUNT(*) FROM drafts WHERE status IN ('sending','sent','ambiguous') AND sent_at>=?", (day_start,)).fetchone()[0]
            if total >= MAX_PER_DAY:
                db.rollback()
                raise EmailModuleError("daily_limit", "Daily email limit reached")
            last = db.execute("SELECT MAX(sent_at) FROM drafts WHERE status IN ('sending','sent','ambiguous')").fetchone()[0]
            if _parse(last) and (now - _parse(last)).total_seconds() < MIN_GAP_SECONDS:
                db.rollback()
                raise EmailModuleError("send_gap", "Wait at least one minute between emails")
            company_last = db.execute("SELECT MAX(d.sent_at) FROM drafts d JOIN applications a ON a.id=d.application_id WHERE a.company_key=? AND d.status IN ('sending','sent','ambiguous') AND d.kind='application'", (app["company_key"],)).fetchone()[0]
            if draft["kind"] == "application" and _parse(company_last) and now - _parse(company_last) < timedelta(days=COMPANY_COOLDOWN_DAYS):
                db.rollback()
                raise EmailModuleError("company_cooldown", "A recent application email to this company already exists")
            if draft["kind"] == "followup" and app["last_email_sent"] and now - _parse(app["last_email_sent"]) < timedelta(days=FOLLOWUP_DAYS):
                db.rollback()
                raise EmailModuleError("followup_early", "Wait seven days after the last email")
            rfc_id = f"<email-module-{draft_id}@agenthq.local>"
            db.execute("UPDATE drafts SET status='sending',message_id=?,sent_at=? WHERE id=?", (rfc_id, self._at(), draft_id))
            self._event(db, app["id"], "send_reserved", draft_id)
            db.commit()
        msg = EmailMessage()
        msg["From"] = self.owner_email
        msg["To"] = app["email"]
        msg["Subject"] = draft["subject"]
        msg["Message-ID"] = rfc_id
        if draft["kind"] != "application":
            parent_direction = "received" if draft["kind"] == "reply" else "sent"
            with self._db() as db:
                prior = db.execute("SELECT rfc822_id FROM messages WHERE application_id=? AND direction=? ORDER BY received_at DESC LIMIT 1", (app["id"], parent_direction)).fetchone()
            if prior and prior[0]:
                msg["In-Reply-To"] = prior[0]
                msg["References"] = prior[0]
        msg.set_content(draft["body"])
        try:
            result = await self.gmail.send(msg.as_bytes(), thread_id=app["gmail_thread_id"])
        except GmailTransient as exc:
            try:
                found = await self._sent_match(rfc_id)
            except Exception:
                found = None
            if found:
                result = {"id": found.id, "threadId": found.thread_id}
            else:
                with self._db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("UPDATE drafts SET status='ambiguous',error=? WHERE id=?", (str(exc)[:200], draft_id))
                    self._event(db, app["id"], "send_ambiguous", draft_id)
                    db.commit()
                return self.draft_record(draft_id)
        except GmailError as exc:
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE drafts SET status='failed',error=? WHERE id=?", (str(exc)[:200], draft_id))
                self._event(db, app["id"], "send_failed", draft_id)
                db.commit()
            return self.draft_record(draft_id)
        sent_at = self._at()
        next_at = _iso(_utc(self.now()) + timedelta(days=FOLLOWUP_DAYS)) if draft["kind"] in ("application", "followup") else None
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE drafts SET status='sent',gmail_message_id=?,sent_at=?,error=NULL WHERE id=?", (result.get("id"), sent_at, draft_id))
            db.execute("UPDATE applications SET status=CASE WHEN status IN ('found','researching','prepared','drafted') THEN 'applied' ELSE status END, last_email_sent=?,next_followup_at=CASE WHEN reply_received=1 OR status!='applied' AND status NOT IN ('found','researching','prepared','drafted') THEN NULL ELSE ? END,followup_count=followup_count+?,gmail_thread_id=COALESCE(gmail_thread_id,?),updated_at=? WHERE id=?",
                       (sent_at, next_at, int(draft["kind"] == "followup"), result.get("threadId"), sent_at, app["id"]))
            db.execute("INSERT OR IGNORE INTO messages(gmail_id,application_id,thread_id,direction,from_addr,to_addr,subject,body,rfc822_id,in_reply_to,classification,received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (result.get("id"), app["id"], result.get("threadId"), "sent", self.owner_email, app["email"], draft["subject"], draft["body"], rfc_id, msg.get("In-Reply-To"), draft["kind"], sent_at))
            self._event(db, app["id"], "sent", draft["kind"])
            db.commit()
        return self.draft_record(draft_id)

    async def reconcile(self, draft_id: str) -> dict[str, Any]:
        draft = self.draft_record(draft_id)
        if draft["status"] not in ("sending", "ambiguous"):
            return draft
        found = await self._sent_match(draft["message_id"])
        if not found:
            return draft  # absence from search is not proof of non-delivery
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE drafts SET status='sent',gmail_message_id=?,error=NULL WHERE id=?", (found.id, draft_id))
            next_at = _iso((_parse(draft["sent_at"]) or _utc(self.now())) + timedelta(days=FOLLOWUP_DAYS)) if draft["kind"] in ("application", "followup") else None
            db.execute("UPDATE applications SET status=CASE WHEN status IN ('found','researching','prepared','drafted') THEN 'applied' ELSE status END,last_email_sent=?,next_followup_at=CASE WHEN reply_received=1 OR status NOT IN ('found','researching','prepared','drafted','applied') THEN NULL ELSE ? END,followup_count=followup_count+?,gmail_thread_id=COALESCE(gmail_thread_id,?),updated_at=? WHERE id=?", (draft["sent_at"], next_at, int(draft["kind"] == "followup"), found.thread_id, self._at(), draft["application_id"]))
            app = db.execute("SELECT email FROM applications WHERE id=?", (draft["application_id"],)).fetchone()
            db.execute("INSERT OR IGNORE INTO messages(gmail_id,application_id,thread_id,direction,from_addr,to_addr,subject,body,rfc822_id,in_reply_to,classification,received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (found.id, draft["application_id"], found.thread_id, "sent", self.owner_email, app["email"], draft["subject"], draft["body"], draft["message_id"], None, draft["kind"], draft["sent_at"]))
            self._event(db, draft["application_id"], "send_reconciled", draft_id)
            db.commit()
        return self.draft_record(draft_id)

    async def sync(self) -> dict[str, Any]:
        if self.gmail is None:
            raise EmailModuleError("gmail_disconnected", "Connect Gmail before syncing")
        profile = await self.gmail.profile()
        if (profile.get("emailAddress") or "").lower() != self.owner_email:
            raise EmailModuleError("account_mismatch", "Connected Gmail account does not match the owner")
        with self._db() as db:
            cursor_row = db.execute("SELECT value FROM metadata WHERE key='gmail_history_id'").fetchone()
        cursor = cursor_row[0] if cursor_row else None
        ids: list[str] = []
        latest: str | None = None
        full_scan = not bool(cursor)
        if cursor:
            try:
                page = None
                while True:
                    result = await self.gmail.history(cursor, page)
                    for record in result.get("history") or []:
                        for added in record.get("messagesAdded") or []:
                            mid = (added.get("message") or {}).get("id")
                            if mid:
                                ids.append(mid)
                    latest = str(result.get("historyId") or latest or cursor)
                    page = result.get("nextPageToken")
                    if not page:
                        break
            except GmailNotFound:
                full_scan = True
                ids = []
        truncated = False
        if full_scan:
            profile = await self.gmail.profile()
            latest = str(profile.get("historyId") or "")
            page = None
            while True:
                result = await self.gmail.list_messages("newer_than:30d -in:chats -in:drafts", page, 100)
                ids.extend(item["id"] for item in result.get("messages") or [] if item.get("id"))
                page = result.get("nextPageToken")
                if not page or len(ids) >= 500:
                    truncated = bool(page)
                    break
        fetched = []
        for mid in dict.fromkeys(ids[:500]):
            msg = await self.gmail.get_message(mid)
            if "DRAFT" not in msg.label_ids:
                fetched.append(msg)
        fetched.sort(key=lambda m: (m.internal_date or "", m.id))
        imported = 0
        for msg in fetched:
            if msg.is_sent or self.owner_email not in msg.to_addrs:
                continue
            with self._db() as db:
                if db.execute("SELECT 1 FROM messages WHERE gmail_id=?", (msg.id,)).fetchone():
                    continue
                apps = db.execute("SELECT * FROM applications WHERE email=?", (msg.from_addr,)).fetchall()
                app = next((a for a in apps if a["gmail_thread_id"] and a["gmail_thread_id"] == msg.thread_id), None)
                if app is None:
                    refs = {v for v in (msg.in_reply_to, *(re.findall(r"<[^>]+>", msg.references or ""))) if v}
                    for candidate in apps:
                        if db.execute("SELECT 1 FROM messages WHERE application_id=? AND rfc822_id IN (" + ",".join("?" * len(refs)) + ")", (candidate["id"], *refs)).fetchone() if refs else False:
                            app = candidate
                            break
                if app is None:
                    continue
                classification = _classify(msg)
                at = msg.internal_date or self._at()
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT OR IGNORE INTO messages(gmail_id,application_id,thread_id,direction,from_addr,to_addr,subject,body,rfc822_id,in_reply_to,classification,received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (msg.id, app["id"], msg.thread_id, "received", msg.from_addr, self.owner_email, msg.subject, msg.body_text[:20000], msg.rfc822_id, msg.in_reply_to, classification, at))
                if db.execute("SELECT changes()").fetchone()[0]:
                    imported += 1
                    if classification != "auto_reply":
                        old = app["status"]
                        new = old if old in TERMINAL else classification
                        if old == "offer" and classification in {"replied", "assessment", "interview"}:
                            new = old
                        links = json.loads(app["links"])
                        deadlines = json.loads(app["deadlines"])
                        if classification in {"interview", "assessment"}:
                            links += [u.rstrip(".,)") for u in URL_RE.findall(msg.body_text) if u.rstrip(".,)") not in links][:10]
                            deadlines += [d for d in DATE_RE.findall(msg.body_text) if d not in deadlines][:10]
                        db.execute("UPDATE applications SET status=?,reply_received=1,next_followup_at=NULL,links=?,deadlines=?,gmail_thread_id=COALESCE(gmail_thread_id,?),updated_at=? WHERE id=?",
                                   (new, json.dumps(links), json.dumps(deadlines), msg.thread_id, self._at(), app["id"]))
                    self._event(db, app["id"], "received", classification)
                db.commit()
        if latest and not truncated:
            with self._db() as db:
                db.execute("INSERT INTO metadata(key,value) VALUES ('gmail_history_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (latest,))
        return {"fetched": len(fetched), "imported": imported, "ignored": len(fetched) - imported,
                "full_scan": full_scan, "truncated": truncated}

    async def search(self, query: str) -> dict[str, Any]:
        if self.gmail is None:
            raise EmailModuleError("gmail_disconnected", "Connect Gmail before searching")
        q = _clean(query, 300)
        if not q:
            q = SEARCH_QUERY
        result = await self.gmail.list_messages(q, max_results=100)
        messages = []
        for item in result.get("messages") or []:
            msg = await self.gmail.get_message(item["id"])
            if self.mode == "sandbox" and q != SEARCH_QUERY and q.casefold() not in (msg.subject + " " + msg.body_text + " " + msg.from_addr).casefold():
                continue
            messages.append({"id": msg.id, "thread_id": msg.thread_id, "from": msg.from_addr,
                             "subject": msg.subject, "snippet": msg.snippet, "date": msg.internal_date,
                             "sent": msg.is_sent})
        return {"query": q, "messages": messages}
