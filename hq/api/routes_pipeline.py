"""Phase (c) routes: paste-a-link, sources (Settings › Sources), the fetch log, generated files, and the verdict
audit export. Mutations only write rows; the worker picks up the queued tasks."""
from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from hq import settings as paths
from hq.api import auth
from hq.api.auth import ApiError
from hq.api.routes import Conn, _addr
from hq.db import repo, serializers
from hq.db.conn import tx
from hq.pipeline.discover import sources as src_mod
from hq.pipeline.discover.manual import manual_posting
from hq.pipeline.discover.postings import opportunity_values
from hq.util import netguard
from hq.util.timeutil import now_iso
from hq.worker import queue
from hq.pipeline.state import priority_for

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_session)])


# ── paste a link ──────────────────────────────────────────────────────────────────────────────────────
class ManualIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=2000, pattern=r"^https?://")
    text: str | None = Field(default=None, max_length=60_000)
    company: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=200)


@router.post("/opportunities/manual", status_code=201)
def add_manual(body: ManualIn, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    lane = netguard.is_manual_lane(body.url)
    if lane and not (body.text or "").strip():
        raise ApiError(422, f"{netguard.host_of(body.url)} is a manual-lane site: HQ never opens it, so paste the "
                            "posting text too")
    p = manual_posting(body.url, body.text, company=body.company, title=body.title)
    with tx(conn):
        existing = conn.execute("SELECT id FROM opportunities WHERE canonical_key=?", (p.canonical_key,)).fetchone()
        if existing:
            raise ApiError(409, "already in the pipeline", {"id": existing["id"]})
        values = opportunity_values(p, source_label="Pasted by Prerit")
        values["apply_channel"] = "manual"
        opp_id = repo.insert_opportunity(conn, values, is_simulated=False)
        now = now_iso()
        conn.execute("INSERT OR IGNORE INTO opportunity_sources(opportunity_id, source_id, external_id, source_url, "
                     "first_seen, last_seen) VALUES (?,?,?,?,?,?)", (opp_id, p.source_id, p.external_id, p.url, now, now))
        queue.enqueue(conn, "parse.job", opportunity_id=opp_id, priority=priority_for("parse.job"),
                      idempotency_key=f"manual:{opp_id}", source_agent="prerit")
        repo.audit(conn, "prerit", "opportunity.manual", opp_id, after={"url": body.url, "manual_lane": lane},
                   remote_addr=_addr(request))
        opp = serializers.opp_summary_by_id(conn, opp_id)
        repo.emit(conn, "opp.created", f"New (pasted): {opp['company_name']} — {opp['title']}", opportunity_id=opp_id,
                  data={"opp": opp})
    return opp


# ── sources ───────────────────────────────────────────────────────────────────────────────────────────
@router.get("/sources")
def list_sources(conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM sources ORDER BY kind, name").fetchall()
    counts = {r["source_id"]: r["n"] for r in conn.execute(
        "SELECT source_id, COUNT(DISTINCT opportunity_id) AS n FROM opportunity_sources GROUP BY source_id")}
    items = [{**src_mod.source_json(r), "opportunities": counts.get(r["id"], 0)} for r in rows]
    return {"items": items, "manual_lane": sorted(netguard.manual_lane_domains()), "mode": netguard.current_mode()}


class SourcePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    tos_status: str | None = Field(default=None, pattern=r"^(unreviewed|allowed|restricted|prohibited)$")
    poll_interval_min: int | None = Field(default=None, ge=30, le=7 * 24 * 60)


@router.patch("/sources/{source_id:path}")
def patch_source(source_id: str, body: SourcePatch, request: Request, conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    with tx(conn):
        row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise ApiError(404, "source not found")
        before = src_mod.source_json(row)
        tos = body.tos_status or row["tos_status"]
        if body.enabled and tos != "allowed":
            raise ApiError(409, "read the site's terms first and mark them allowed before enabling this source")
        sets: dict[str, Any] = {}
        if body.enabled is not None:
            sets["enabled"] = int(body.enabled)
            if body.enabled:
                sets.update(consecutive_errors=0, disabled_until=None)
        if body.tos_status is not None:
            sets.update(tos_status=body.tos_status, tos_reviewed_at=now_iso())
            if body.tos_status in ("restricted", "prohibited"):
                sets["enabled"] = 0
        if body.poll_interval_min is not None:
            sets["poll_interval_min"] = body.poll_interval_min
        if sets:
            conn.execute(f"UPDATE sources SET {','.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), source_id))
        after = src_mod.source_json(conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone())
        repo.audit(conn, "prerit", "source.update", source_id, before={k: before[k] for k in sets if k in before},
                   after={k: after[k] for k in sets if k in after}, remote_addr=_addr(request))
    return after


@router.get("/fetch-log")
def fetch_log(limit: int = Query(100, ge=1, le=1000), domain: str | None = None,
              conn: sqlite3.Connection = Conn) -> dict[str, Any]:
    q = "SELECT * FROM fetch_log" + (" WHERE domain=?" if domain else "") + " ORDER BY id DESC LIMIT ?"
    rows = [dict(r) for r in conn.execute(q, ((domain,) if domain else ()) + (limit,))]
    methods = {r["method"]: r["n"] for r in conn.execute("SELECT method, COUNT(*) AS n FROM fetch_log GROUP BY method")}
    return {"items": rows, "methods": methods}


# ── files (documents and pack attachments; only under data/artifacts) ────────────────────────────────
def _safe_file(path: str | None) -> Path:
    if not path:
        raise ApiError(404, "no file")
    p = Path(path).resolve()
    root = paths.ARTIFACTS.resolve()
    if root not in p.parents or not p.is_file():
        raise ApiError(404, "file not available")
    return p


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: str, conn: sqlite3.Connection = Conn) -> FileResponse:
    row = conn.execute("SELECT content_path FROM documents WHERE id=?", (doc_id,)).fetchone()
    if row is None:
        raise ApiError(404, "document not found")
    p = _safe_file(row["content_path"])
    return FileResponse(p, filename=p.name)


@router.get("/needs/{need_id}/files/{idx}")
def need_file(need_id: str, idx: int, conn: sqlite3.Connection = Conn) -> FileResponse:
    row = conn.execute("SELECT files_json FROM needs_prerit WHERE id=?", (need_id,)).fetchone()
    if row is None:
        raise ApiError(404, "need not found")
    files = serializers._loads(row["files_json"], [])
    if not 0 <= idx < len(files):
        raise ApiError(404, "no such file")
    p = _safe_file(files[idx].get("path"))
    return FileResponse(p, filename=files[idx].get("name") or p.name)


# ── audit export (first 20 eligibility + pay verdicts) ────────────────────────────────────────────────
AUDIT_COLUMNS = ["opportunity_id", "company", "title", "url", "eligibility_status", "eligibility_confidence",
                 "eligibility_method", "eligibility_quotes", "pay_status", "pay_raw", "pay_monthly_inr_min",
                 "living_cost_monthly_inr", "pay_ratio", "stage", "stage_reason", "correct_eligibility(y/n)",
                 "correct_pay(y/n)"]


def audit_rows(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    out = []
    for o in conn.execute("SELECT * FROM opportunities WHERE is_simulated=0 AND eligibility_status IS NOT NULL "
                          "ORDER BY first_seen_at LIMIT ?", (limit,)):
        chk = conn.execute("SELECT method, quotes_json FROM eligibility_checks WHERE opportunity_id=? "
                           "ORDER BY created_at DESC LIMIT 1", (o["id"],)).fetchone()
        quotes = " | ".join(q.get("quote", "") if isinstance(q, dict) else str(q)
                            for q in serializers._loads(chk["quotes_json"] if chk else None, [])[:3])
        out.append({"opportunity_id": o["id"], "company": o["company_name"], "title": o["title"], "url": o["url"],
                    "eligibility_status": o["eligibility_status"], "eligibility_confidence": o["eligibility_confidence"],
                    "eligibility_method": chk["method"] if chk else None, "eligibility_quotes": quotes,
                    "pay_status": o["pay_status"], "pay_raw": o["pay_raw"],
                    "pay_monthly_inr_min": o["pay_monthly_inr_min"],
                    "living_cost_monthly_inr": o["living_cost_monthly_inr"], "pay_ratio": o["pay_ratio"],
                    "stage": o["stage"], "stage_reason": o["stage_reason"], "correct_eligibility(y/n)": "",
                    "correct_pay(y/n)": ""})
    return out


def audit_csv(conn: sqlite3.Connection, limit: int = 20) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=AUDIT_COLUMNS)
    w.writeheader()
    w.writerows(audit_rows(conn, limit))
    return buf.getvalue()


@router.get("/audit/verdicts.csv")
def verdicts_csv(limit: int = Query(20, ge=1, le=500), conn: sqlite3.Connection = Conn) -> Response:
    return Response(audit_csv(conn, limit), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=verdicts.csv"})
