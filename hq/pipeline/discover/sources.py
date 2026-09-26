"""Source registry: seed `sources` from config/sources.yaml, pick the ones due for a poll, and keep per-source
health (circuit breaker: 5 consecutive errors → disabled for 6 h; the Strategist is told)."""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from hq import settings as paths
from hq.db import repo
from hq.db.conn import dumps
from hq.util.timeutil import now_iso, parse_iso, to_iso, utcnow

BREAKER_ERRORS = 5
BREAKER_HOURS = 6
ATS_KINDS = ("greenhouse", "lever", "ashby")
ATS_LABEL = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby"}


@lru_cache(maxsize=2)
def _config(path: str, mtime: float) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text()) or {}


def config() -> dict[str, Any]:
    p = paths.CONFIG_DIR / "sources.yaml"
    return _config(str(p), p.stat().st_mtime) if p.exists() else {}


def seed_sources(conn: sqlite3.Connection) -> int:
    """Insert configured sources that don't exist yet (never overwrites Prerit's toggles). Caller owns tx."""
    cfg = config()
    default_interval = int((cfg.get("defaults") or {}).get("poll_interval_min", 360))
    added = 0
    now = now_iso()
    for kind, spec in (cfg.get("ats") or {}).items():
        for slug in spec.get("slugs", []):
            sid = f"{kind}:{slug}"
            cur = conn.execute(
                "INSERT OR IGNORE INTO sources(id, name, kind, config_json, automation, tos_status, tos_url, "
                "tos_reviewed_at, poll_interval_min, enabled, added_by, created_at) "
                "VALUES (?,?,?,?, 'discover_only', 'allowed', ?, ?, ?, 1, 'config', ?)",
                (sid, f"{ATS_LABEL.get(kind, kind)} · {slug}", kind, dumps({"slug": slug, "tos_note": spec.get("tos_note")}),
                 spec.get("tos_url"), now, default_interval, now))
            added += cur.rowcount
    mock = cfg.get("mock_ats")
    if mock:
        cur = conn.execute(
            "INSERT OR IGNORE INTO sources(id, name, kind, config_json, automation, tos_status, tos_url, "
            "tos_reviewed_at, poll_interval_min, enabled, added_by, created_at) "
            "VALUES (?, 'Mock ATS (local, dev)', 'greenhouse', ?, 'auto', 'allowed', NULL, ?, 30, 0, 'config', ?)",
            (f"greenhouse:{mock['slug']}", dumps({"slug": mock["slug"], "base": mock["base"],
                                                  "tos_note": "Local test server (python -m mock_ats)."}), now, now))
        added += cur.rowcount
    for feed_id, spec in (cfg.get("feeds") or {}).items():
        cur = conn.execute(
            "INSERT OR IGNORE INTO sources(id, name, kind, config_json, automation, tos_status, tos_url, "
            "tos_reviewed_at, poll_interval_min, enabled, added_by, created_at) "
            "VALUES (?,?, 'feed', ?, 'discover_only', 'allowed', ?, ?, ?, ?, 'config', ?)",
            (f"feed:{feed_id}", spec["name"], dumps({"feed": feed_id, "tos_note": spec.get("tos_note")}),
             spec.get("tos_url"), now, int(spec.get("poll_interval_min", default_interval)),
             int(bool(spec.get("enabled", True))), now))
        added += cur.rowcount
    for prog in cfg.get("programs") or []:
        cur = conn.execute(
            "INSERT OR IGNORE INTO sources(id, name, kind, config_json, automation, tos_status, tos_url, "
            "poll_interval_min, enabled, added_by, created_at) VALUES (?,?, 'program_page', ?, 'discover_only', "
            "'unreviewed', ?, ?, 0, 'config', ?)",
            (f"program:{prog['id']}", prog["name"], dumps({k: v for k, v in prog.items() if k not in ("id", "name")}),
             prog.get("tos_url"), int(prog.get("poll_interval_min", default_interval)), now))
        added += cur.rowcount
    return added


def source_json(r: sqlite3.Row | dict) -> dict[str, Any]:
    d = dict(r)
    cfgj = json.loads(d.get("config_json") or "{}")
    return {"id": d["id"], "name": d["name"], "kind": d["kind"], "config": cfgj, "automation": d["automation"],
            "tos_status": d["tos_status"], "tos_url": d["tos_url"], "tos_reviewed_at": d["tos_reviewed_at"],
            "poll_interval_min": d["poll_interval_min"], "last_polled_at": d["last_polled_at"],
            "last_ok_at": d["last_ok_at"], "consecutive_errors": d["consecutive_errors"],
            "disabled_until": d["disabled_until"], "enabled": bool(d["enabled"]), "added_by": d["added_by"]}


def due_sources(conn: sqlite3.Connection, kinds: tuple[str, ...], limit: int = 6) -> list[dict[str, Any]]:
    """Enabled, ToS-allowed sources whose interval has passed and whose breaker isn't open, oldest first."""
    now = utcnow()
    out = []
    marks = ",".join("?" * len(kinds))
    for r in conn.execute(f"SELECT * FROM sources WHERE enabled=1 AND tos_status='allowed' AND kind IN ({marks}) "
                          "ORDER BY COALESCE(last_polled_at, '') ASC", kinds):
        if r["disabled_until"] and parse_iso(r["disabled_until"]) > now:
            continue
        last = parse_iso(r["last_polled_at"])
        if last and (now - last).total_seconds() < r["poll_interval_min"] * 60:
            continue
        out.append(source_json(r))
        if len(out) >= limit:
            break
    return out


def record_poll(conn: sqlite3.Connection, source_id: str, *, ok: bool, error: str | None = None,
                found: int = 0) -> None:
    """Caller owns tx."""
    now = now_iso()
    if ok:
        conn.execute("UPDATE sources SET last_polled_at=?, last_ok_at=?, consecutive_errors=0, disabled_until=NULL "
                     "WHERE id=?", (now, now, source_id))
        return
    row = conn.execute("SELECT consecutive_errors, name FROM sources WHERE id=?", (source_id,)).fetchone()
    errors = (row["consecutive_errors"] if row else 0) + 1
    until = to_iso(utcnow() + timedelta(hours=BREAKER_HOURS)) if errors >= BREAKER_ERRORS else None
    conn.execute("UPDATE sources SET last_polled_at=?, consecutive_errors=?, disabled_until=COALESCE(?, disabled_until) "
                 "WHERE id=?", (now, errors, until, source_id))
    repo.emit(conn, "fetch.error", f"{row['name'] if row else source_id}: {error}"
              + (f" — paused for {BREAKER_HOURS} h after {errors} errors" if until else ""),
              level="warn" if until else "info", data={"source_id": source_id, "errors": errors, "until": until})
