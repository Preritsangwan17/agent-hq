"""Gmail connection and the go-live path (CONTRACT_D §1, §5).

Everything that changes credentials or the mode is loopback-only (never from the phone): saving the OAuth client,
starting a consent, disconnecting, writing the live flags to .env, the self-test, and the typed GO LIVE. Going back to
DRY RUN is allowed from anywhere (it only makes HQ safer)."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from hq import settings as paths
from hq.api import auth
from hq.api.auth import ApiError
from hq.api.routes import Conn, _addr
from hq.db import repo
from hq.db.conn import tx
from hq.db.seed import get_settings, set_settings
from hq.gmail import auth as gauth
from hq.gmail.api import GmailAuthError
from hq.profile import owner
from hq.util.timeutil import now_iso, parse_iso, utcnow

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_session)])
MIN_REVIEWED = 5
CONFIRM_PHRASE = "GO LIVE"


def account_mismatch(state: dict[str, Any]) -> str | None:
    """The connected mailbox when it isn't the owner's (HQ only reads and sends as Prerit), else None."""
    got = (state.get("email") or "").strip().lower()
    return got if got and not owner.is_owner_address(got) else None


def gmail_json(conn: sqlite3.Connection) -> dict[str, Any]:
    s = get_settings(conn)
    scopes = gauth.granted_scopes()
    state = s.get("gmail_state") or {}
    return {"client_configured": bool(gauth.client_id() and gauth.client_secret()),
            "connected": gauth.connected(), "scopes": [x.rsplit("/", 1)[-1] for x in scopes],
            "send_scope": gauth.has_send_scope(scopes), "compose_scope": gauth.has_compose_scope(scopes),
            "state": state, "oauth": gauth.FLOW.state(), "forced_dry_run": gauth.forced_dry_run(),
            "refusal": s.get("worker_refusal"), "owner_email": owner.email(),
            "account_mismatch": account_mismatch(state)}


@router.get("/gmail")
def get_gmail(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return gmail_json(conn)


class ClientIn(BaseModel):
    """Either the ID + secret, or the whole `client_secret_….json` Google offers as a download."""
    model_config = ConfigDict(extra="forbid")
    client_id: str | None = Field(default=None, min_length=20, max_length=200)
    client_secret: str | None = Field(default=None, min_length=10, max_length=200)
    client_json: str | None = Field(default=None, min_length=20, max_length=20_000)


def client_from_json(raw: str) -> tuple[str, str]:
    """(client_id, client_secret) from Google's downloaded client file. Only Desktop ("installed") clients work with
    the loopback consent HQ uses."""
    try:
        data = json.loads(raw)
    except ValueError:
        raise ApiError(422, "that isn't the JSON file Google downloads (client_secret_….json)") from None
    if not isinstance(data, dict):
        raise ApiError(422, "that isn't the JSON file Google downloads (client_secret_….json)")
    if "installed" not in data:
        kind = next(iter(data), None)
        hint = " — this is a Web application client; create a Desktop app client instead" if kind == "web" else ""
        raise ApiError(422, f"no Desktop client in that file{hint}")
    inst = data["installed"] or {}
    cid, secret = str(inst.get("client_id") or ""), str(inst.get("client_secret") or "")
    if not cid or not secret:
        raise ApiError(422, "the file has no client_id / client_secret")
    return cid, secret


@router.put("/gmail/client")
def put_client(body: ClientIn, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    auth.require_loopback(request)
    if body.client_json:
        cid, secret = client_from_json(body.client_json)
    elif body.client_id and body.client_secret:
        cid, secret = body.client_id, body.client_secret
    else:
        raise ApiError(422, "paste the client ID and secret, or the downloaded client_secret_….json")
    cid, secret = cid.strip(), secret.strip()
    if not re.fullmatch(r"[\w.-]+\.apps\.googleusercontent\.com", cid):
        raise ApiError(422, "that doesn't look like a Desktop OAuth client ID (…apps.googleusercontent.com)")
    if not 10 <= len(secret) <= 200:
        raise ApiError(422, "that doesn't look like an OAuth client secret")
    paths.set_env_value("HQ_GMAIL_CLIENT_ID", cid)
    paths.set_env_value("HQ_GMAIL_CLIENT_SECRET", secret)
    with tx(conn):
        repo.audit(conn, "prerit", "gmail.client_saved", None, after={"client_id_suffix": cid[-24:],
                                                                      "from_json": bool(body.client_json)},
                   remote_addr=_addr(request))
    return gmail_json(conn)


class ConnectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: str = Field(default="readonly", pattern=r"^(readonly|send)$")


@router.post("/gmail/connect")
async def connect(body: ConnectIn, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    auth.require_loopback(request)
    if body.purpose == "send":
        st = golive_state(conn)
        if not st["ready_for_send_scope"]:
            raise ApiError(409, "finish the checklist before asking Google for send permission",
                           {"missing": [i["id"] for i in st["items"] if i["gate"] and not i["ok"]]})
    try:
        url = await gauth.FLOW.start(body.purpose)
    except GmailAuthError as exc:
        raise ApiError(409, str(exc)) from exc
    with tx(conn):
        repo.audit(conn, "prerit", "gmail.consent_started", None, after={"purpose": body.purpose},
                   remote_addr=_addr(request))
    return {"auth_url": url, "oauth": gauth.FLOW.state()}


@router.post("/gmail/disconnect")
def disconnect(request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    auth.require_loopback(request)
    gauth.disconnect()
    with tx(conn):
        s = get_settings(conn)
        set_settings(conn, {"gmail_state": {**(s.get("gmail_state") or {}), "connected": False, "healthy": False,
                                            "history_id": None}})
        repo.add_command(conn, "gmail_recheck", {})
        repo.audit(conn, "prerit", "gmail.disconnected", None, remote_addr=_addr(request))
    return gmail_json(conn)


@router.post("/gmail/recheck")
def recheck(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        repo.add_command(conn, "gmail_recheck", {})
    return {"queued": True}


# ── go-live ──────────────────────────────────────────────────────────────────────────────────────────
def golive_state(conn: sqlite3.Connection) -> dict[str, Any]:
    s = get_settings(conn)
    g = s.get("gmail_state") or {}
    missing = [r["label"] for r in conn.execute("SELECT label FROM profile_fields WHERE required_for_live=1 AND "
                                                "confirmed_by_prerit=0 ORDER BY key")]
    reviewed = conn.execute("SELECT COUNT(*) FROM applications WHERE reviewed_at IS NOT NULL AND mode='dry_run'"
                            ).fetchone()[0]
    golden = s.get("golden_state") or {}
    golden_fresh = bool(golden.get("passed")) and (parse_iso(golden.get("ran_at")) or utcnow()).timestamp() > \
        utcnow().timestamp() - 7 * 86400
    cap = int(s.get("email_daily_cap", 10))
    cloud = s.get("claude_state") or {}
    self_test = s.get("gmail_self_test") or {}
    wrong_account = account_mismatch(g)
    items = [
        {"id": "gmail", "gate": True, "label": f"Gmail connected and healthy (read-only) as {owner.email()}",
         "ok": bool(gauth.connected() and g.get("healthy")) and not wrong_account,
         "detail": (f"connected as {wrong_account} — disconnect and connect {owner.email()} instead"
                    if wrong_account else g.get("email") or g.get("error") or
                    ("connected — waiting for the first check" if gauth.connected() else "not connected"))},
        {"id": "profile", "gate": True, "label": "Required profile fields confirmed", "ok": not missing,
         "detail": "all confirmed" if not missing else "missing: " + ", ".join(missing)},
        {"id": "reviewed", "gate": True, "label": f"At least {MIN_REVIEWED} dry-run applications reviewed",
         "ok": reviewed >= MIN_REVIEWED, "detail": f"{reviewed}/{MIN_REVIEWED} reviewed"},
        {"id": "golden", "gate": True, "label": "Golden fact-gate tests green (last 7 days)", "ok": golden_fresh,
         "detail": (f"recall {golden.get('recall')} · {golden.get('gold')} gold pairs" if golden else "not run yet")},
        {"id": "caps", "gate": True, "label": "Caps set", "ok": 1 <= cap <= 10 and
         float(s.get("claude_daily_budget_usd", 0)) > 0,
         "detail": f"{cap} emails/day · 3 lab emails/day · 1 per domain per 14 days · "
                   f"${float(s.get('claude_daily_budget_usd', 0)):.2f} cloud/day"},
        {"id": "cloud", "gate": True, "label": "Cloud sign-off available (or the policy acknowledged)",
         "ok": bool(cloud.get("available")) or bool(s.get("signoff_policy_ack")),
         "detail": ("available" if cloud.get("available") else
                    "acknowledged: local checks only" if s.get("signoff_policy_ack") else
                    cloud.get("reason") or "not available")},
        {"id": "send_scope", "gate": False, "label": "Send permission granted (second Google consent)",
         "ok": gauth.has_send_scope(), "detail": ", ".join(x.rsplit("/", 1)[-1] for x in gauth.granted_scopes())
         or "—"},
        {"id": "env", "gate": False, "label": ".env switched to live and HQ restarted",
         "ok": s.get("worker_env_mode") == "live",
         "detail": "worker running in " + str(s.get("worker_env_mode") or "unknown") + " mode"},
        {"id": "self_test", "gate": False, "label": "Self-test email reached your own inbox", "ok": bool(self_test.get("ok")),
         "detail": self_test.get("error") or (f"sent {self_test.get('at', '')[:16].replace('T', ' ')}"
                                              if self_test.get("ok") else "not sent yet")},
    ]
    gates_ok = all(i["ok"] for i in items if i["gate"])
    return {"mode": s.get("mode", "dry_run"), "live_since": s.get("live_since"), "items": items,
            "ready_for_send_scope": gates_ok, "ready_for_env": gates_ok and gauth.has_send_scope(),
            "ready_for_live": gates_ok and all(i["ok"] for i in items), "confirm_phrase": CONFIRM_PHRASE,
            "env_file_live": paths.read_env_file().get("HQ_FORCE_DRY_RUN") == "0",
            "forced_dry_run": gauth.forced_dry_run()}


@router.get("/golive")
def get_golive(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return golive_state(conn)


@router.post("/golive/golden")
def run_golden(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    from hq.pipeline.gates import golden

    res = golden.run()
    with tx(conn):
        set_settings(conn, {"golden_state": res}, by="prerit")
    return golive_state(conn)


@router.post("/golive/env")
def write_env(request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    auth.require_loopback(request)
    st = golive_state(conn)
    if not st["ready_for_env"]:
        raise ApiError(409, "the checklist and the send permission come first")
    paths.set_env_value("HQ_FORCE_DRY_RUN", "0", export=False)   # takes effect only after a restart
    paths.set_env_value("HQ_MODE", "live", export=False)
    with tx(conn):
        repo.audit(conn, "prerit", "golive.env_written", None, after={"HQ_FORCE_DRY_RUN": "0", "HQ_MODE": "live"},
                   remote_addr=_addr(request))
    return {**golive_state(conn), "restart_required": True, "restart_command": "make down && make up"}


@router.post("/golive/self-test")
def self_test(request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    auth.require_loopback(request)
    s = get_settings(conn)
    if s.get("worker_env_mode") != "live" or not gauth.has_send_scope():
        raise ApiError(409, "the self-test needs the send permission and a restart with the live .env")
    with tx(conn):
        set_settings(conn, {"gmail_self_test": {"ok": False, "pending": True, "at": now_iso()}}, by="prerit")
        repo.add_command(conn, "gmail_self_test", {})
        repo.audit(conn, "prerit", "golive.self_test", None, remote_addr=_addr(request))
    return golive_state(conn)


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str


@router.post("/golive/confirm")
def confirm(body: ConfirmIn, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    auth.require_loopback(request)
    if body.confirm.strip() != CONFIRM_PHRASE:
        raise ApiError(422, f"type {CONFIRM_PHRASE} exactly")
    st = golive_state(conn)
    if not st["ready_for_live"]:
        raise ApiError(409, "not every checklist item is green yet",
                       {"missing": [i["id"] for i in st["items"] if not i["ok"]]})
    with tx(conn):
        before = get_settings(conn)
        set_settings(conn, {"mode": "live", "live_since": now_iso(), "autonomy": "approve_first"}, by="prerit")
        repo.audit(conn, "prerit", "golive.confirmed", None,
                   before={"mode": before.get("mode"), "autonomy": before.get("autonomy")},
                   after={"mode": "live", "autonomy": "approve_first"}, remote_addr=_addr(request))
        repo.emit(conn, "mode.changed", "Agent HQ is LIVE — approve-first for the first applications",
                  level="alert", data={"mode": "live"})
    return golive_state(conn)


class DryRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    env: bool = False


@router.post("/golive/dry-run")
def back_to_dry_run(body: DryRunIn, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    """Always allowed (safer). Writing .env back to forced dry run is loopback-only like every .env write."""
    if body.env:
        auth.require_loopback(request)
        paths.set_env_value("HQ_FORCE_DRY_RUN", "1")
        paths.set_env_value("HQ_MODE", "dry_run")
    with tx(conn):
        before = get_settings(conn).get("mode")
        set_settings(conn, {"mode": "dry_run"}, by="prerit")
        repo.audit(conn, "prerit", "golive.back_to_dry_run", None, before={"mode": before},
                   after={"mode": "dry_run", "env": body.env}, remote_addr=_addr(request))
        repo.emit(conn, "mode.changed", "Back to DRY RUN — nothing leaves the Mac", level="warn",
                  data={"mode": "dry_run"})
    return golive_state(conn)
