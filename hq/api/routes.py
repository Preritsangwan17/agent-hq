"""REST routes (CONTRACT §3). Every route except health/auth-status/login/setup requires the session cookie.
Mutations only write rows (settings, commands, audit, events, tasks); the worker acts on them."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterator, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hq import settings as paths
from hq.agents.registry import AgentFileError, parse_agent_file, sync_file, write_agent_file
from hq.agents.schema import ADAPTERS, PALETTE, RESERVED_SIDE_EFFECTS, AgentConfig, capability_meta
from hq.api import auth
from hq.api.auth import ApiError
from hq.db import repo, serializers
from hq.db.conn import connect, tx
from hq.db.seed import SettingError, get_settings, set_settings, validate_patch
from hq.pipeline.state import priority_for
from hq.util.timeutil import iso_in, now_iso, utcnow
from hq.worker import queue


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


public = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_session)])
Conn = Depends(get_conn)


# ── bodies ────────────────────────────────────────────────────────────────────────────────────────────
class PasscodeBody(BaseModel):
    passcode: str = Field(max_length=256)


class StageBody(BaseModel):
    stage: str
    reason: str | None = Field(default=None, max_length=500)


class PauseBody(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class ResumeBody(BaseModel):
    confirm: str


class FreezeBody(BaseModel):
    on: bool


class NeedPatch(BaseModel):
    status: Literal["done", "snoozed", "dismissed", "open"]
    snooze_hours: float | None = Field(default=None, gt=0, le=24 * 30)
    choice: str | None = Field(default=None, max_length=40)  # decision items: one of payload.options[].value


class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paused: bool | None = None
    enabled: bool | None = None
    model: str | None = None
    concurrency: int | None = None
    schedule: dict[str, Any] | None = None
    name: str | None = None
    avatar: str | None = None
    color: str | None = None


def _addr(request: Request) -> str | None:
    return auth.client_ip(request)


# ── public: health + auth ────────────────────────────────────────────────────────────────────────────
@public.get("/health")
def health(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return serializers.health(conn)


@public.get("/auth/status")
def auth_status(request: Request) -> dict[str, Any]:
    return {"configured": auth.is_configured(), "authenticated": auth.is_authenticated(request),
            "loopback": auth.is_loopback(request)}


@public.post("/auth/setup")
def auth_setup(body: PasscodeBody, request: Request, response: Response,
               conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    auth.require_loopback(request)
    if auth.is_configured():
        raise ApiError(409, "passcode already configured")
    if len(body.passcode) < auth.MIN_PASSCODE_LEN:
        raise ApiError(400, f"passcode must be at least {auth.MIN_PASSCODE_LEN} characters")
    auth.set_passcode(body.passcode)
    with tx(conn):
        repo.audit(conn, "prerit", "auth.setup", "passcode", remote_addr=_addr(request))
        repo.emit(conn, "log", "Passcode configured", data={"auth": "setup"})
    auth.set_session_cookie(response)
    return {"ok": True}


@public.post("/auth/login")
def auth_login(body: PasscodeBody, request: Request, response: Response,
               conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    limiter: auth.RateLimiter = request.app.state.login_limiter
    if not limiter.allow(_addr(request) or "?"):
        raise ApiError(429, "too many login attempts; wait a minute")
    if not auth.is_configured():
        raise ApiError(409, "no passcode configured yet; set one up from the Mac")
    ok = auth.verify_passcode(body.passcode, auth.passcode_hash())
    with tx(conn):
        repo.audit(conn, "prerit" if ok else "unknown", "auth.login" if ok else "auth.login_failed", None,
                   remote_addr=_addr(request))
    if not ok:
        raise ApiError(401, "wrong passcode")
    auth.set_session_cookie(response)
    return {"ok": True}


@public.post("/auth/logout")
def auth_logout(response: Response) -> dict[str, Any]:
    auth.clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/me")
def auth_me() -> dict[str, Any]:
    return {"ok": True}


# ── snapshot / events / stats ────────────────────────────────────────────────────────────────────────
@router.get("/snapshot")
def snapshot(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return serializers.snapshot(conn)


@router.get("/events")
def events(conn: sqlite3.Connection = Conn, after: int | None = None, before: int | None = None,
           limit: int = Query(200, ge=1, le=500), agent: str | None = None, level: str | None = None,
           type: str | None = None, q: str | None = None) -> dict[str, Any]:
    return {"events": repo.list_events(conn, after=after, before=before, limit=limit, agent=agent, level=level,
                                       type_=type, q=q)}


@router.get("/stats")
def stats(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return serializers.stats(conn)


# ── opportunities ────────────────────────────────────────────────────────────────────────────────────
@router.get("/opportunities")
def opportunities(conn: sqlite3.Connection = Conn, stage: str | None = None, q: str | None = None,
                  sim: int | None = Query(None, ge=0, le=1), limit: int = Query(500, ge=1, le=2000)) -> dict:
    rows = repo.list_opportunity_rows(conn, stage=stage, q=q, sim=sim, limit=limit)
    return {"items": serializers.opp_summaries(conn, rows)}


@router.get("/opportunities/{opp_id}")
def opportunity(opp_id: str, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    detail = serializers.opp_detail(conn, opp_id)
    if detail is None:
        raise ApiError(404, "opportunity not found")
    return detail


@router.patch("/opportunities/{opp_id}/stage")
def override_stage(opp_id: str, body: StageBody, request: Request, conn: sqlite3.Connection = Conn) -> dict:
    """Display-only override: audited, emits opp.stage, cancels queued automation for the item, creates no tasks."""
    if body.stage not in repo.STAGES:
        raise ApiError(400, f"unknown stage '{body.stage}'", {"allowed": repo.STAGES})
    with tx(conn):
        opp = repo.get_opportunity_row(conn, opp_id)
        if opp is None:
            raise ApiError(404, "opportunity not found")
        old = opp["stage"]
        reason = (body.reason or "").strip() or "set manually by Prerit"
        repo.update_opportunity(conn, opp_id, {"stage": body.stage, "stage_reason": reason})
        conn.execute("UPDATE opportunities SET stage_override=1 WHERE id=?", (opp_id,))
        parked = conn.execute(
            "UPDATE tasks SET status='cancelled', last_error='stage overridden by Prerit', finished_at=?, updated_at=? "
            "WHERE opportunity_id=? AND status='queued'", (now_iso(), now_iso(), opp_id)).rowcount
        repo.audit(conn, "prerit", "opp.stage_override", opp_id, before={"stage": old, "reason": opp["stage_reason"]},
                   after={"stage": body.stage, "reason": reason, "cancelled_queued_tasks": parked},
                   remote_addr=_addr(request))
        summary = serializers.opp_summary_by_id(conn, opp_id)
        repo.emit(conn, "opp.stage", f"{summary['company_name']} — {summary['title']}: {old} → {body.stage} "
                  "(manual override; no actions triggered)", opportunity_id=opp_id,
                  data={"opp": summary, "from": old, "to": body.stage, "override": True})
    return summary


# ── agents ────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/agents")
def agents(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return {"agents": serializers.agents_json(conn)}


@router.get("/agents/meta")
def agents_meta() -> dict[str, Any]:
    return {"capabilities": capability_meta(), "adapters": ADAPTERS, "reserved_side_effects": RESERVED_SIDE_EFFECTS,
            "palette": PALETTE}


def _validation_error(exc: ValidationError) -> ApiError:
    errors = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
    return ApiError(400, "; ".join(f"{e['field'] or 'config'}: {e['message']}" for e in errors), errors)


@router.post("/agents", status_code=201)
def create_agent(body: dict[str, Any], request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    if body.get("builtin"):
        raise ApiError(400, "new agents cannot be built-in")
    reserved = [c for c in body.get("capabilities") or [] if c in RESERVED_SIDE_EFFECTS]
    if reserved:
        raise ApiError(400, f"side-effect capabilities are reserved for built-in agents: {', '.join(reserved)}")
    try:
        cfg = AgentConfig.model_validate({**body, "builtin": False})
    except ValidationError as exc:
        raise _validation_error(exc) from None
    if cfg.adapter == "script":
        auth.require_loopback(request)
    agents_dir = paths.AGENTS_DIR
    if (repo.agent_row(conn, cfg.id) or (agents_dir / f"{cfg.id}.yaml").exists()
            or (agents_dir / f"{cfg.id}.yaml.disabled").exists()):
        raise ApiError(409, f"an agent with id '{cfg.id}' already exists")
    path = write_agent_file(agents_dir, cfg)
    sync_file(conn, path)
    with tx(conn):
        conn.execute("UPDATE agents SET probation_runs_left=? WHERE id=?", (PROBATION_RUNS, cfg.id))
        repo.audit(conn, "prerit", "agent.create", cfg.id, after=cfg.to_yaml_dict(), remote_addr=_addr(request))
        repo.add_command(conn, "agent_changed", {"agent_id": cfg.id})
    return serializers.agent_json_by_id(conn, cfg.id)


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
PROBATION_RUNS = 5  # a wizard-created agent's first outputs wait for Prerit's approval


def _probe_endpoint(url: str) -> dict[str, Any]:
    """GET a local model/HTTP agent endpoint (loopback only — the wizard never contacts third parties)."""
    import httpx
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "") not in LOOPBACK_HOSTS:
        return {"ok": False, "url": url, "error": "only http(s)://localhost or 127.0.0.1 endpoints can be probed"}
    try:
        r = httpx.get(url, timeout=2.0)
    except httpx.HTTPError as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"[:200]}
    detail: Any = None
    try:
        body = r.json()
        if isinstance(body, dict) and isinstance(body.get("data"), list):
            detail = {"models": [m.get("id") for m in body["data"] if isinstance(m, dict)][:20]}
    except ValueError:
        pass
    return {"ok": r.status_code < 400, "url": url, "status": r.status_code, "detail": detail}


@router.post("/agents/validate")
def validate_agent(body: dict[str, Any], request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    """Dry run of POST /api/agents for the wizard's last step: validation errors, the YAML that would be written,
    an id clash check and, for endpoint adapters, a loopback-only reachability probe. Writes nothing."""
    import yaml

    reserved = [c for c in body.get("capabilities") or [] if c in RESERVED_SIDE_EFFECTS]
    errors: list[dict[str, str]] = []
    if reserved:
        errors.append({"field": "capabilities",
                       "message": f"side-effect capabilities are reserved for built-in agents: {', '.join(reserved)}"})
    try:
        cfg = AgentConfig.model_validate({**body, "builtin": False})
    except ValidationError as exc:
        errors += [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return {"ok": False, "errors": errors, "yaml": None, "probe": None}
    if (repo.agent_row(conn, cfg.id) or (paths.AGENTS_DIR / f"{cfg.id}.yaml").exists()
            or (paths.AGENTS_DIR / f"{cfg.id}.yaml.disabled").exists()):
        errors.append({"field": "id", "message": f"an agent with id '{cfg.id}' already exists"})
    if cfg.adapter == "script" and not auth.is_loopback(request):
        errors.append({"field": "adapter", "message": "script agents can only be created from this Mac"})
    probe = None
    endpoint = cfg.adapter_config.get("base_url") or cfg.adapter_config.get("endpoint")
    if cfg.adapter in ("openai_compatible", "http") and isinstance(endpoint, str) and endpoint:
        url = endpoint.rstrip("/") + ("/models" if cfg.adapter == "openai_compatible" else "/health")
        probe = _probe_endpoint(url)
    text = yaml.safe_dump(cfg.to_yaml_dict(), sort_keys=False, allow_unicode=True)
    return {"ok": not errors, "errors": errors, "yaml": text, "probe": probe}


@router.patch("/agents/{agent_id}")
def patch_agent(agent_id: str, body: AgentPatch, request: Request, conn: sqlite3.Connection = Conn) -> dict:
    row = repo.agent_row(conn, agent_id)
    if row is None:
        raise ApiError(404, "agent not found")
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ApiError(400, "nothing to change")
    flags = {k: changes.pop(k) for k in ("paused", "enabled") if k in changes}
    config_change = None
    if changes:
        path = paths.AGENTS_DIR / f"{agent_id}.yaml"
        if not path.exists():
            raise ApiError(409, "agent has no YAML file to edit")
        try:
            current, _ = parse_agent_file(path)
        except AgentFileError as exc:
            raise ApiError(409, f"current YAML is invalid, fix it first: {exc}") from None
        merged = {**current.to_yaml_dict(), **changes}
        try:
            cfg = AgentConfig.model_validate(merged)
        except ValidationError as exc:
            raise _validation_error(exc) from None
        config_change = cfg
    with tx(conn):
        if flags:
            sets = ",".join(f"{k}=?" for k in flags)
            conn.execute(f"UPDATE agents SET {sets}, updated_at=? WHERE id=?",
                         (*[int(v) for v in flags.values()], now_iso(), agent_id))
        repo.audit(conn, "prerit", "agent.update", agent_id,
                   before={k: bool(row[k]) for k in flags} | ({"config": serializers._loads(row["config_json"], {})}
                                                              if config_change else {}),
                   after=flags | ({"config": changes} if config_change else {}), remote_addr=_addr(request))
        repo.add_command(conn, "agent_changed", {"agent_id": agent_id})
    changed = None
    if config_change is not None:
        path = write_agent_file(paths.AGENTS_DIR, config_change)
        _, changed = sync_file(conn, path)
    if changed is None:
        with tx(conn):
            agent = serializers.agent_json_by_id(conn, agent_id)
            what = ", ".join(f"{k}={'on' if v else 'off'}" for k, v in flags.items()) or "no change"
            repo.emit(conn, "agent.updated", f"{agent['name']}: {what}", agent_id=agent_id, data={"agent": agent})
    return serializers.agent_json_by_id(conn, agent_id)


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    row = repo.agent_row(conn, agent_id)
    if row is None:
        raise ApiError(404, "agent not found")
    if serializers._loads(row["config_json"], {}).get("builtin"):
        raise ApiError(400, "built-in agents cannot be deleted, only disabled")
    path = paths.AGENTS_DIR / f"{agent_id}.yaml"
    if path.exists():
        target = path.with_name(path.name + ".disabled")
        if target.exists():
            target = path.with_name(f"{path.name}.{utcnow().strftime('%Y%m%d%H%M%S')}.disabled")
        path.rename(target)
    with tx(conn):
        conn.execute("UPDATE agents SET enabled=0, updated_at=? WHERE id=?", (now_iso(), agent_id))
        repo.audit(conn, "prerit", "agent.delete", agent_id, remote_addr=_addr(request))
        repo.add_command(conn, "rescan_agents", {"agent_id": agent_id})
        agent = serializers.agent_json_by_id(conn, agent_id)
        repo.emit(conn, "agent.updated", f"{agent['name']} is being removed (draining)", agent_id=agent_id,
                  data={"agent": agent})
    return {"ok": True}


# ── control ───────────────────────────────────────────────────────────────────────────────────────────
@router.post("/control/pause-all")
def pause_all(request: Request, body: PauseBody | None = None, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    reason = (body.reason if body else None) or "PAUSE ALL pressed"
    with tx(conn):
        set_settings(conn, {"global_pause": True}, by="prerit")
        repo.add_command(conn, "pause_all", {"reason": reason})
        repo.audit(conn, "prerit", "control.pause_all", None, after={"reason": reason}, remote_addr=_addr(request))
        repo.emit(conn, "control.pause", f"PAUSE ALL — {reason}", level="warn", data={"paused": True, "reason": reason})
    return {"paused": True}


@router.post("/control/resume-all")
def resume_all(body: ResumeBody, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    if body.confirm != "RESUME":
        raise ApiError(400, "type RESUME to confirm")
    with tx(conn):
        set_settings(conn, {"global_pause": False}, by="prerit")
        repo.add_command(conn, "resume_all", {})
        repo.audit(conn, "prerit", "control.resume_all", None, remote_addr=_addr(request))
        repo.emit(conn, "control.pause", "Resumed — agents back to work", data={"paused": False, "reason": None})
    return {"paused": False}


@router.post("/control/freeze-outbound")
def freeze_outbound(body: FreezeBody, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        set_settings(conn, {"freeze_outbound": body.on}, by="prerit")
        repo.add_command(conn, "freeze_outbound", {"on": body.on})
        repo.audit(conn, "prerit", "control.freeze_outbound", None, after={"on": body.on}, remote_addr=_addr(request))
        repo.emit(conn, "control.freeze", "Outbound frozen" if body.on else "Outbound unfrozen",
                  level="warn" if body.on else "info", data={"freeze_outbound": body.on})
    return {"freeze_outbound": body.on}


# ── settings ──────────────────────────────────────────────────────────────────────────────────────────
@router.get("/settings")
def get_all_settings(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    return {"settings": get_settings(conn)}


@router.patch("/settings")
def patch_settings(body: dict[str, Any], request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    try:
        cleaned = validate_patch(body)
    except SettingError as exc:
        raise ApiError(400, str(exc)) from None
    with tx(conn):
        before = get_settings(conn)
        set_settings(conn, cleaned, by="prerit")
        after = get_settings(conn)
        repo.add_command(conn, "settings_changed", {"keys": sorted(cleaned)})
        repo.audit(conn, "prerit", "settings.update", ",".join(sorted(cleaned)),
                   before={k: before.get(k) for k in cleaned}, after=cleaned, remote_addr=_addr(request))
        repo.emit(conn, "settings.updated", "Settings changed: " + ", ".join(sorted(cleaned)),
                  data={"settings": after, "changed": sorted(cleaned)})
    return {"settings": after}


# ── needs ─────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/needs")
def needs(conn: sqlite3.Connection = Conn, status: str = "open") -> dict[str, Any]:
    rows = repo.list_need_rows(conn, status=None if status == "all" else status)
    return {"items": [serializers.need_json(n) for n in rows]}


@router.patch("/needs/{need_id}")
def patch_need(need_id: str, body: NeedPatch, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        need = repo.get_need_row(conn, need_id)
        if need is None:
            raise ApiError(404, "need not found")
        now = now_iso()
        if need["kind"] == "decision" and body.status in ("done", "dismissed"):
            payload = serializers._loads(need.get("payload_json"), {})
            allowed = [o.get("value") for o in payload.get("options") or [] if isinstance(o, dict)]
            choice = body.choice if body.status == "done" else (body.choice or "drop")
            if choice not in allowed:
                raise ApiError(422, f"choice must be one of: {', '.join(map(str, allowed))}")
            conn.execute("UPDATE needs_prerit SET payload_json=? WHERE id=?",
                         (json.dumps({**payload, "choice": choice}), need_id))
            need = {**need, "payload_json": json.dumps({**payload, "choice": choice})}
        if body.status == "snoozed":
            until = iso_in((body.snooze_hours or 24) * 3600)
            conn.execute("UPDATE needs_prerit SET status='snoozed', snoozed_until=? WHERE id=?", (until, need_id))
        elif body.status == "open":
            conn.execute("UPDATE needs_prerit SET status='open', snoozed_until=NULL, resolved_at=NULL WHERE id=?",
                         (need_id,))
        else:
            conn.execute("UPDATE needs_prerit SET status=?, resolved_at=?, snoozed_until=NULL WHERE id=?",
                         (body.status, now, need_id))
        followups = _need_followups(conn, need, body.status) if need["status"] != body.status else []
        repo.audit(conn, "prerit", f"needs.{body.status}", need_id, before={"status": need["status"]},
                   after={"status": body.status, "followups": followups}, remote_addr=_addr(request))
        updated = serializers.need_json(repo.get_need_row(conn, need_id))
        repo.emit(conn, "needs.updated", f"{updated['title']}: {body.status}", opportunity_id=need["opportunity_id"],
                  data={"need": updated})
        if need["opportunity_id"]:
            opp = serializers.opp_summary_by_id(conn, need["opportunity_id"])
            if opp and "stage" not in {f.split(":")[0] for f in followups}:
                repo.emit(conn, "opp.updated", f"Updated {opp['company_name']} — {opp['title']}", level="debug",
                          opportunity_id=opp["id"], data={"opp": opp})
    return updated


def _need_followups(conn: sqlite3.Connection, need: dict[str, Any], status: str) -> list[str]:
    """What Prerit's answer means for the pipeline. `submit_form` done = he submitted the pack himself;
    `approve` done = explicit approval for the Applicant to proceed (autonomy approve_first)."""
    done: list[str] = []
    payload = serializers._loads(need.get("payload_json"), {})
    if payload.get("probation_task_id") and status in ("done", "dismissed"):
        repo.add_command(conn, "probation_release", {"task_id": payload["probation_task_id"],
                                                      "approved": status == "done"})
        return [f"probation:{'approved' if status == 'done' else 'discarded'}"]
    if need["kind"] == "decision" and payload.get("decision") == "outbound_ambiguous" and status in ("done", "dismissed"):
        from hq.pipeline.apply import guard

        guard.resolve_ambiguous(conn, payload.get("outbound_id", ""), sent=payload.get("choice") == "sent")
        return [f"outbound:{payload.get('choice')}"]
    if need["kind"] == "approve_reply" and status == "done" and payload.get("document_id"):
        from hq.api.routes_inbox import queue_reply

        doc = conn.execute("SELECT d.*, t.notify_only_lock FROM documents d LEFT JOIN email_threads t ON "
                           "t.id=d.email_thread_id WHERE d.id=?", (payload["document_id"],)).fetchone()
        if doc is None or doc["status"] not in ("draft", "approved") or doc["notify_only_lock"]:
            return ["reply:not_sent"]
        return ["task:reply.send"] if queue_reply(conn, dict(doc), bool(payload.get("attach_resume"))) else []
    opp_id, app_id = need.get("opportunity_id"), need.get("application_id")
    opp = repo.get_opportunity_row(conn, opp_id) if opp_id else None
    if need["kind"] == "decision" and opp is not None and status in ("done", "dismissed") and \
            opp["stage"] == "verified" and not opp["stage_override"]:
        # Prerit answered a keep/drop question: score again (it holds while any decision is still open)
        task_id = queue.enqueue(conn, "score.fit", opportunity_id=opp_id, priority=priority_for("score.fit"),
                                idempotency_key=f"decision:{need['id']}", source_agent="prerit")
        return [f"decision:{payload.get('choice')}"] + (["task:score.fit"] if task_id else [])
    if status != "done" or opp is None or opp["stage_override"]:
        return done
    if need["kind"] == "submit_form" and opp["stage"] == "checked":
        if app_id:
            conn.execute("UPDATE applications SET status='submitted', submitted_at=?, submission_ref='manual', "
                         "updated_at=? WHERE id=?", (now_iso(), now_iso(), app_id))
        repo.update_opportunity(conn, opp_id, {"stage": "applied", "stage_reason": "submitted by Prerit"})
        summary = serializers.opp_summary_by_id(conn, opp_id)
        repo.emit(conn, "opp.stage", f"{summary['company_name']} — {summary['title']}: checked → applied "
                  "(Prerit submitted the form)", opportunity_id=opp_id,
                  data={"opp": summary, "from": "checked", "to": "applied"})
        done.append("stage:applied")
    elif need["kind"] == "approve" and opp["stage"] == "checked":
        route = payload.get("route") or ("email" if opp["apply_channel"] == "email" else "pack")
        cap = {"email": "apply.email_send", "mock_ats": "apply.ats_submit"}.get(route, "apply.manual_pack")
        task_id = queue.enqueue(conn, cap, opportunity_id=opp_id, application_id=app_id, priority=priority_for(cap),
                                idempotency_key=f"approve:{need['id']}", source_agent="prerit")
        if app_id:  # the approval binds to the exact letter + résumé digest shown in the item
            conn.execute("UPDATE applications SET status='queued', approved_by='prerit', approved_at=?, updated_at=?, "
                         "approval_sha256=COALESCE(?, approval_sha256) WHERE id=?",
                         (now_iso(), now_iso(), payload.get("sha256"), app_id))
        repo.update_opportunity(conn, opp_id, {"stage_reason": "approved by Prerit"})
        if task_id:
            done.append(f"task:{cap}")
    return done


# ── sim ───────────────────────────────────────────────────────────────────────────────────────────────
@router.post("/sim/reset")
def sim_reset(request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        opp_ids = [r["id"] for r in conn.execute("SELECT id FROM opportunities WHERE is_simulated=1")]
        if opp_ids:
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS _purge(id TEXT PRIMARY KEY)")
            conn.execute("DELETE FROM _purge")
            conn.executemany("INSERT INTO _purge(id) VALUES (?)", [(i,) for i in opp_ids])
            sub = "SELECT id FROM _purge"
            apps = f"SELECT id FROM applications WHERE opportunity_id IN ({sub})"
            conn.execute(f"DELETE FROM mock_mailbox WHERE application_id IN ({apps})")
            conn.execute(f"DELETE FROM gate_results WHERE application_id IN ({apps})")
            conn.execute(f"DELETE FROM email_messages WHERE thread_id IN "
                         f"(SELECT id FROM email_threads WHERE opportunity_id IN ({sub}))")
            conn.execute(f"DELETE FROM email_threads WHERE opportunity_id IN ({sub})")
            conn.execute(f"DELETE FROM needs_prerit WHERE opportunity_id IN ({sub})")
            conn.execute(f"DELETE FROM tasks WHERE opportunity_id IN ({sub}) AND status NOT IN ('leased','running')")
            conn.execute(f"DELETE FROM opportunities WHERE id IN ({sub})")
            conn.execute("DELETE FROM _purge")
        repo.add_command(conn, "sim_reset", {"purged": len(opp_ids)})
        repo.audit(conn, "prerit", "sim.reset", None, after={"purged": len(opp_ids)}, remote_addr=_addr(request))
        repo.emit(conn, "log", f"Simulation reset: purged {len(opp_ids)} simulated opportunities",
                  level="warn", data={"sim_reset": True, "purged": len(opp_ids)})
    return {"ok": True, "purged": len(opp_ids)}
