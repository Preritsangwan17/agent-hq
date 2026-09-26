"""Settings-page routes: Profile & Facts, Security (passcode change, LAN status, audit log).

Profile edits are audited and mark the field confirmed; unconfirmed values never reach outbound text
(hq.profile.fields.confirmed_value). Changing the passcode is loopback-only, like the first-run setup.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from hq.api import auth
from hq.api.auth import ApiError
from hq.api.routes import Conn, _addr
from hq.db import repo
from hq.db.conn import tx
from hq.db.serializers import _loads
from hq.profile import fields as pfields

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_session)])

# Names only — values never leave the server.
SECRET_ENV_KEYS = ("HQ_PASSCODE_HASH", "HQ_SESSION_SECRET", "HQ_GMAIL_CLIENT_ID", "HQ_GMAIL_CLIENT_SECRET",
                   "HQ_GMAIL_REFRESH_TOKEN")


class FieldPatch(BaseModel):
    value: Any = None
    share_policy: str | None = None


class FactPatch(BaseModel):
    status: str


class PasscodeChange(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


def fact_json(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "category": row["category"], "project": row["project_key"], "text": row["text"],
            "phrasings": _loads(row["allowed_phrasings_json"], []), "evidence_url": row["evidence_url"],
            "evidence": row["evidence_quote"], "source": row["source"], "status": row["status"], "note": row["note"]}


@router.get("/profile")
def profile(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    facts = [fact_json(dict(r)) for r in conn.execute("SELECT * FROM profile_facts ORDER BY category, id")]
    fields = [pfields.field_json(r) for r in pfields.field_rows(conn)]
    missing = [f["key"] for f in fields if f["required_for_live"] and not f["confirmed"]]
    return {"facts": facts, "fields": fields, "required_missing": missing}


@router.patch("/profile/fields/{key}")
def patch_field(key: str, body: FieldPatch, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    if key not in pfields.DEFS:
        raise ApiError(404, f"unknown profile field '{key}'")
    with tx(conn):
        before = conn.execute("SELECT value, share_policy, confirmed_by_prerit FROM profile_fields WHERE key=?",
                              (key,)).fetchone()
        try:
            row = pfields.update_field(conn, key, body.value, body.share_policy)
        except pfields.FieldError as exc:
            raise ApiError(400, f"{pfields.DEFS[key].label}: {exc}") from None
        # values are personal: the audit records that a field changed, not what it changed to
        repo.audit(conn, "prerit", "profile.field_update", key,
                   before={"had_value": bool(before and before["value"]),
                           "share_policy": before["share_policy"] if before else None},
                   after={"has_value": row["value"] is not None, "share_policy": row["share_policy"],
                          "confirmed": bool(row["confirmed_by_prerit"])}, remote_addr=_addr(request))
        field = pfields.field_json(row)
        repo.emit(conn, "profile.updated", f"Profile: {field['label']} {'confirmed' if field['confirmed'] else 'cleared'}",
                  data={"field": {k: field[k] for k in ("key", "label", "confirmed", "share_policy")}})
    return field


@router.patch("/profile/facts/{fact_id}")
def patch_fact(fact_id: str, body: FactPatch, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    """Prerit confirms a pending fact or retires one (retired facts are never cited again)."""
    if body.status not in ("verified", "pending", "retired"):
        raise ApiError(400, "status must be verified, pending or retired")
    with tx(conn):
        row = conn.execute("SELECT * FROM profile_facts WHERE id=?", (fact_id,)).fetchone()
        if row is None:
            raise ApiError(404, "fact not found")
        conn.execute("UPDATE profile_facts SET status=?, verified_by='prerit', verified_at=datetime('now') WHERE id=?",
                     (body.status, fact_id))
        repo.audit(conn, "prerit", "profile.fact_status", fact_id, before={"status": row["status"]},
                   after={"status": body.status}, remote_addr=_addr(request))
        repo.emit(conn, "profile.updated", f"Fact {fact_id}: {row['status']} → {body.status}",
                  data={"fact_id": fact_id, "status": body.status})
        return fact_json(dict(conn.execute("SELECT * FROM profile_facts WHERE id=?", (fact_id,)).fetchone()))


@router.get("/security")
def security(request: Request) -> dict[str, Any]:
    return {
        "lan": os.environ.get("HQ_LAN") == "1",
        "allowed_hosts": sorted(auth.allowed_hosts()),
        "loopback": auth.is_loopback(request),
        "https": False,
        "session_days": auth.SESSION_MAX_AGE // 86400,
        "secrets_present": [k for k in SECRET_ENV_KEYS if os.environ.get(k)],
        "force_dry_run": os.environ.get("HQ_FORCE_DRY_RUN", "1") != "0",
    }


@router.post("/auth/change-passcode")
def change_passcode(body: PasscodeChange, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    auth.require_loopback(request)
    if not auth.verify_passcode(body.current, auth.passcode_hash()):
        with tx(conn):
            repo.audit(conn, "unknown", "auth.change_failed", None, remote_addr=_addr(request))
        raise ApiError(401, "current passcode is wrong")
    if len(body.new) < auth.MIN_PASSCODE_LEN:
        raise ApiError(400, f"passcode must be at least {auth.MIN_PASSCODE_LEN} characters")
    auth.set_passcode(body.new)
    with tx(conn):
        repo.audit(conn, "prerit", "auth.change", "passcode", remote_addr=_addr(request))
        repo.emit(conn, "log", "Passcode changed", level="warn", data={"auth": "change"})
    return {"ok": True}


@router.get("/audit")
def audit_log(conn: sqlite3.Connection = Conn, limit: int = Query(100, ge=1, le=500),
              action: str | None = None) -> dict[str, Any]:
    sql, params = "SELECT * FROM audit_log", []
    if action:
        sql += " WHERE action LIKE ?"
        params.append(f"{action}%")
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    items = []
    for r in conn.execute(sql, params):
        items.append({"id": r["id"], "ts": r["ts"], "actor": r["actor"], "action": r["action"], "target": r["target"],
                      "before": _loads(r["before_json"], None), "after": _loads(r["after_json"], None),
                      "remote_addr": r["remote_addr"]})
    return {"items": items}
