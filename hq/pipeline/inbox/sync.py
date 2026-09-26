"""Inbox sync (CONTRACT_D §2): new message ids since the stored historyId (404 → full sync of the last 30 days),
the scope filter, and linking a message to an application.

Scope is deliberately narrow — only these are ever stored: threads HQ already knows, replies to HQ's own Message-IDs,
mail from the domains of organisations Prerit applied to, ATS / assessment senders and job-alert senders. Everything
else in the mailbox is never read past its headers and never written anywhere.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hq import settings as paths
from hq.gmail.api import GmailMessage, GmailNotFound
from hq.pipeline.inbox.rules import sender_kind, sender_parts
from hq.util import netguard

FULL_SYNC_QUERY = "newer_than:30d -in:chats -in:drafts"
FULL_SYNC_MAX = 500


def mail_dir() -> Path:
    d = paths.DATA / "mail"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def new_message_ids(gmail: Any, history_id: str | None) -> tuple[list[str], str | None, bool]:
    """(message ids added since `history_id`, the latest history id, whether a full sync was needed)."""
    if history_id:
        try:
            ids: list[str] = []
            page, latest = None, history_id
            while True:
                res = await gmail.history(history_id, page)
                for h in res.get("history") or []:
                    for added in h.get("messagesAdded") or []:
                        m = added.get("message") or {}
                        if m.get("id") and "DRAFT" not in (m.get("labelIds") or []):
                            ids.append(m["id"])
                latest = res.get("historyId") or latest
                page = res.get("nextPageToken")
                if not page:
                    break
            return list(dict.fromkeys(ids)), str(latest), False
        except GmailNotFound:
            pass
    profile = await gmail.profile()
    ids, page = [], None
    while len(ids) < FULL_SYNC_MAX:
        res = await gmail.list_messages(FULL_SYNC_QUERY, page, 100)
        ids += [m["id"] for m in res.get("messages") or []]
        page = res.get("nextPageToken")
        if not page:
            break
    return list(dict.fromkeys(ids))[:FULL_SYNC_MAX], str(profile.get("historyId")), True


def _registrable(host: str) -> str:
    parts = host.lower().strip(".").split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "ac", "edu", "gov", "org", "com", "net") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


@dataclass
class Scope:
    thread_ids: dict[str, dict[str, Any]] = field(default_factory=dict)     # gmail thread id → thread row
    our_ids: dict[str, str | None] = field(default_factory=dict)             # our Message-ID → application id
    domains: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # registrable domain → [(opp, app)]
    companies: list[tuple[str, str, str]] = field(default_factory=list)      # (company core, opp, app)


def scope(conn: sqlite3.Connection) -> Scope:
    sc = Scope()
    for r in conn.execute("SELECT * FROM email_threads WHERE gmail_thread_id IS NOT NULL"):
        sc.thread_ids[r["gmail_thread_id"]] = dict(r)
    for r in conn.execute("SELECT message_id, application_id FROM outbound_log WHERE status IN ('sent','ambiguous')"):
        sc.our_ids[r["message_id"]] = r["application_id"]
    ats = {"greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "smartrecruiters.com", "workable.com"}
    for r in conn.execute("SELECT o.id AS opp, a.id AS app, o.url, o.apply_url, o.apply_email, o.company_domain, "
                          "o.company_name FROM applications a JOIN opportunities o ON o.id=a.opportunity_id WHERE "
                          "o.is_simulated=0 AND a.status NOT IN ('historical_frozen','withdrawn','skipped') "
                          "ORDER BY a.created_at DESC"):
        doms = {_registrable(r["apply_email"].split("@")[-1])} if r["apply_email"] else set()
        for u in (r["url"], r["apply_url"]):
            host = netguard.host_of(u or "")
            if host and not any(host.endswith(a) for a in ats) and not netguard.is_manual_lane(host):
                doms.add(_registrable(host))
        if r["company_domain"]:
            doms.add(_registrable(r["company_domain"]))
        for d in doms:
            sc.domains.setdefault(d, []).append((r["opp"], r["app"]))
        core = re.sub(r"[^a-z0-9]", "", (r["company_name"] or "").lower())
        if len(core) >= 3:
            sc.companies.append((core, r["opp"], r["app"]))
    return sc


def in_scope(msg: GmailMessage, sc: Scope) -> str | None:
    if msg.is_sent or "DRAFT" in msg.label_ids:
        return None
    if msg.thread_id in sc.thread_ids:
        return "thread"
    refs = f"{msg.in_reply_to or ''} {msg.references or ''}"
    if any(mid in refs for mid in sc.our_ids):
        return "reply"
    if _registrable(sender_parts(msg.from_addr)[1] or "x.invalid") in sc.domains:
        return "company"
    kind = sender_kind(msg.from_addr)
    return kind  # "ats" / "alert" / None


def link(conn: sqlite3.Connection, msg: GmailMessage, sc: Scope) -> tuple[str | None, str | None, str | None]:
    """(opportunity id, application id, existing thread row id)."""
    t = sc.thread_ids.get(msg.thread_id)
    if t:
        return t.get("opportunity_id"), t.get("application_id"), t["id"]
    refs = f"{msg.in_reply_to or ''} {msg.references or ''}"
    for mid, app_id in sc.our_ids.items():
        if mid in refs and app_id:
            opp = conn.execute("SELECT opportunity_id FROM applications WHERE id=?", (app_id,)).fetchone()
            return (opp["opportunity_id"] if opp else None), app_id, None
    hits = sc.domains.get(_registrable(sender_parts(msg.from_addr)[1] or "x.invalid"))
    if hits:
        return hits[0][0], hits[0][1], None
    if sender_kind(msg.from_addr) == "ats":
        text = re.sub(r"[^a-z0-9]", "", f"{msg.subject} {msg.body_text[:2000]}".lower())
        found = {(opp, app) for core, opp, app in sc.companies if core in text}
        if len(found) == 1:
            opp, app = found.pop()
            return opp, app, None
    return None, None, None


def save_body(msg: GmailMessage) -> str:
    path = mail_dir() / f"{re.sub(r'[^A-Za-z0-9_-]', '_', msg.id)}.txt"
    path.write_text(msg.body_text[:200_000])
    path.chmod(0o600)
    return str(path)
