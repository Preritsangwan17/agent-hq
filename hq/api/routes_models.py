"""Models, roles and budget routes (CONTRACT_B §3). The worker owns model servers, benchmarks and the Claude
runner; these routes read what it publishes and queue commands for it."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from hq.api import auth
from hq.api.auth import ApiError
from hq.api.routes import Conn, _addr
from hq.db import repo
from hq.db.conn import tx
from hq.db.seed import get_settings
from hq.db.serializers import _loads
from hq.models import memory as mem
from hq.models import roles as roles_mod
from hq.util.timeutil import parse_iso, utcnow
from hq.worker import budget as budget_mod

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_session)])


class BenchmarkBody(BaseModel):
    model_id: str | None = None
    suite: str = "quick"


class RoleBody(BaseModel):
    role: str
    model_id: str | None = None
    reset: bool = False


class PinBody(BaseModel):
    pinned: bool


def _latest_bench(conn: sqlite3.Connection) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for r in conn.execute(
            "SELECT b.* FROM benchmarks b JOIN (SELECT model_id, task, MAX(created_at) AS m FROM benchmarks "
            "GROUP BY model_id, task) l ON l.model_id=b.model_id AND l.task=b.task AND l.m=b.created_at"):
        out.setdefault(r["model_id"], {})[r["task"]] = {
            k: r[k] for k in ("n", "accuracy", "precision", "recall", "f1", "json_valid_first",
                              "json_valid_after_repair", "tok_s_gen", "tok_s_prompt", "ttft_ms", "peak_footprint_gb")
        } | {"created_at": r["created_at"]}
    return out


def model_json(row: dict[str, Any], bench: dict[str, dict[str, Any]], role_map: dict[str, list[tuple[str, int]]],
               role_scores: dict[str, float]) -> dict[str, Any]:
    meta = _loads(row.get("fingerprint"), {})
    last = max((b["created_at"] for b in bench.values()), default=None)
    return {
        "id": row["id"], "runtime": row["runtime"], "name": row["name"], "modality": row["modality"],
        "complete": bool(row["complete"]), "incomplete_reason": row["incomplete_reason"],
        "runtime_supported": bool(row["runtime_supported"]),
        "size_gb": round(row["size_bytes"] / 1e9, 2) if row["size_bytes"] else None, "params_b": row["params_b"],
        "quant": row["quant"], "ctx_len": row["ctx_len"], "est_ram_gb": row["est_ram_gb"],
        "measured_ram_gb": row["measured_ram_gb"], "status": row["status"], "pinned": bool(row["pinned"]),
        "model_type": row["model_type"], "path": row["path"],
        "roles": [r for r, rank in role_map.get(row["id"], []) if rank == 0],
        "ranked_in": {r: rank for r, rank in role_map.get(row["id"], [])},
        "scores": {t: {k: v for k, v in b.items() if k != "created_at"} for t, b in bench.items()},
        "role_scores": role_scores, "last_benchmark_at": last, "served_id": meta.get("served_id"),
        "note": meta.get("server"),
    }


def memory_state(conn: sqlite3.Connection, s: dict[str, Any]) -> dict[str, Any]:
    published = s.get("model_manager_state") or {}
    at = parse_iso(published.get("at")) if isinstance(published, dict) else None
    if at and (utcnow() - at).total_seconds() < 60:
        return published
    sysm = mem.system_memory()
    return {"total_gb": sysm.total_gb, "available_gb": sysm.available_gb, "pool_used_gb": 0.0,
            "pool_budget_gb": float(s.get("model_pool_budget_gb", 30)), "pressure": sysm.pressure,
            "user_active": mem.user_active(), "on_battery": mem.on_battery(),
            "usability_mode": bool(s.get("usability_mode", True)), "usability_reason": None, "servers": [],
            "stale": True}


@router.get("/models")
def models(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    s = get_settings(conn)
    bench = _latest_bench(conn)
    role_map: dict[str, list[tuple[str, int]]] = {}
    scores: dict[str, dict[str, float]] = {}
    for r in conn.execute("SELECT role, model_id, rank, score FROM role_assignments"):
        role_map.setdefault(r["model_id"], []).append((r["role"], r["rank"]))
        if r["score"] is not None:
            scores.setdefault(r["model_id"], {})[r["role"]] = r["score"]
    rows = [dict(r) for r in conn.execute("SELECT * FROM models ORDER BY runtime, name")]
    servers = [dict(r) for r in conn.execute(
        "SELECT model_id, pid, port, started_at, last_used_at, footprint_gb, status FROM model_servers "
        "WHERE status IN ('starting','running') ORDER BY started_at")]
    claude = s.get("claude_state") or {"available": None, "logged_in": False, "reason": "not checked yet",
                                       "model": s.get("claude_model"), "signoff_model": s.get("claude_signoff_model")}
    return {
        "models": [model_json(r, bench.get(r["id"], {}), role_map, scores.get(r["id"], {})) for r in rows],
        "roles": roles_mod.roles_json(conn),
        "servers": servers,
        "memory": memory_state(conn, s),
        "benchmark": s.get("benchmark_state") or {"running": False},
        "claude": claude,
        "local_enabled": True,
    }


@router.post("/models/rescan")
def rescan(request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        repo.add_command(conn, "models_rescan", {})
        repo.audit(conn, "prerit", "models.rescan", None, remote_addr=_addr(request))
    return {"queued": True}


@router.post("/models/benchmark")
def benchmark(body: BenchmarkBody, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    if body.suite not in ("quick", "full"):
        raise ApiError(400, "suite must be quick or full")
    if body.model_id and not conn.execute("SELECT 1 FROM models WHERE id=?", (body.model_id,)).fetchone():
        raise ApiError(404, "unknown model")
    with tx(conn):
        repo.add_command(conn, "models_benchmark", {"model_id": body.model_id, "suite": body.suite})
        repo.audit(conn, "prerit", "models.benchmark", body.model_id, after={"suite": body.suite},
                   remote_addr=_addr(request))
    return {"queued": True}


@router.patch("/roles")
def patch_roles(body: RoleBody, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    if body.role not in roles_mod.ROLE_TASKS:
        raise ApiError(400, f"unknown role '{body.role}'", {"roles": list(roles_mod.ROLE_TASKS)})
    try:
        if body.reset:
            roles_mod.reset_override(conn, body.role, float(get_settings(conn).get("model_pool_budget_gb", 30)))
        elif body.model_id:
            roles_mod.set_override(conn, body.role, body.model_id)
        else:
            raise ApiError(400, "give model_id or reset:true")
    except roles_mod.IndependenceError as exc:
        raise ApiError(409, "independence", str(exc)) from None
    except ValueError as exc:
        raise ApiError(400, str(exc)) from None
    with tx(conn):
        repo.audit(conn, "prerit", "roles.override" if not body.reset else "roles.reset", body.role,
                   after={"model_id": body.model_id}, remote_addr=_addr(request))
        repo.add_command(conn, "roles_changed", {"role": body.role})
    return {"roles": roles_mod.roles_json(conn)}


@router.post("/models/{model_id:path}/pin")
def pin(model_id: str, body: PinBody, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        cur = conn.execute("UPDATE models SET pinned=? WHERE id=?", (int(body.pinned), model_id))
        if not cur.rowcount:
            raise ApiError(404, "unknown model")
        repo.audit(conn, "prerit", "models.pin", model_id, after={"pinned": body.pinned}, remote_addr=_addr(request))
        repo.emit(conn, "model.status", f"{model_id} {'pinned' if body.pinned else 'unpinned'}",
                  data={"model_id": model_id, "pinned": body.pinned})
    return next(m for m in models(conn)["models"] if m["id"] == model_id)


@router.post("/models/{model_id:path}/unload")
def unload(model_id: str, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        repo.add_command(conn, "model_unload", {"model_id": model_id})
        repo.audit(conn, "prerit", "models.unload", model_id, remote_addr=_addr(request))
    return {"ok": True}


@router.get("/budget")
def budget(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    s = get_settings(conn)
    return budget_mod.budget_state(conn, s, s.get("claude_state") or {})


@router.post("/claude/recheck")
def claude_recheck(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        repo.add_command(conn, "claude_recheck", {})
    return {"queued": True}
