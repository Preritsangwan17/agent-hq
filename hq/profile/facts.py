"""Atomic facts from `config/facts.yaml` — the only claims agents may make about Prerit.

`load_facts()` parses the YAML into `Fact` records (used by the fact gate, the Writer and the benchmark);
`seed_facts(conn)` upserts them into `profile_facts`. Facts Prerit retired or confirmed in the UI keep their
status: seeding only refreshes the text, phrasings and evidence.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from hq import settings as paths
from hq.db.conn import dumps
from hq.util.timeutil import now_iso


@dataclass(frozen=True)
class Fact:
    id: str
    category: str
    text: str
    project: str | None = None
    evidence: str | None = None
    evidence_url: str | None = None
    phrasings: tuple[str, ...] = ()
    note: str | None = None
    status: str = "verified"


@dataclass(frozen=True)
class FactSheet:
    facts: tuple[Fact, ...]
    repos: dict[str, dict[str, Any]] = field(default_factory=dict)

    def by_id(self) -> dict[str, Fact]:
        return {f.id: f for f in self.facts}

    def get(self, fact_id: str) -> Fact | None:
        return self.by_id().get(fact_id)


def facts_path() -> Path:
    return paths.CONFIG_DIR / "facts.yaml"


def parse_facts(raw: dict[str, Any]) -> FactSheet:
    repos = raw.get("repos") or {}
    out: list[Fact] = []
    for item in raw.get("facts") or []:
        project = item.get("project")
        repo = repos.get(project) if project else None
        url = f"{repo['url']}/tree/{repo['sha']}" if repo and repo.get("sha") else None
        out.append(Fact(
            id=str(item["id"]), category=str(item.get("category", "other")), text=str(item["text"]),
            project=project, evidence=item.get("evidence"), evidence_url=url,
            phrasings=tuple(item.get("phrasings") or ()), note=item.get("note"),
            status=str(item.get("status", "verified")),
        ))
    return FactSheet(tuple(out), repos)


@lru_cache(maxsize=4)
def _load_cached(path: str, mtime: float) -> FactSheet:
    return parse_facts(yaml.safe_load(Path(path).read_text()) or {})


def load_facts(path: Path | None = None) -> FactSheet:
    p = path or facts_path()
    return _load_cached(str(p), p.stat().st_mtime)


def seed_facts(conn: sqlite3.Connection, sheet: FactSheet | None = None) -> int:
    """Upsert every fact; returns how many were new. Caller owns the transaction."""
    sheet = sheet or load_facts()
    added = 0
    now = now_iso()
    for f in sheet.facts:
        cur = conn.execute(
            "INSERT OR IGNORE INTO profile_facts(id, category, project_key, text, allowed_phrasings_json, evidence_url, "
            "evidence_quote, source, status, verified_by, verified_at, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f.id, f.category, f.project, f.text, dumps(list(f.phrasings)), f.evidence_url, f.evidence, "fact_sheet",
             f.status, "fact_sheet", now, f.note))
        if cur.rowcount:
            added += 1
        else:
            conn.execute(
                "UPDATE profile_facts SET category=?, project_key=?, text=?, allowed_phrasings_json=?, evidence_url=?, "
                "evidence_quote=?, note=? WHERE id=? AND source='fact_sheet'",
                (f.category, f.project, f.text, dumps(list(f.phrasings)), f.evidence_url, f.evidence, f.note, f.id))
    return added


def verified_facts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Facts agents may use right now (status verified), as plain dicts."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM profile_facts WHERE status='verified' ORDER BY category, id")]
