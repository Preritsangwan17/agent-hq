"""Roles and model assignment (CONTRACT_B §2, PLAN "Model manager › Role assignment").

role_score = 0.60·quality + 0.15·json_valid + 0.15·min(1, tok_s/target) + 0.10·(1 − ram/pool)
with per-role floors. The fact-checker is assigned FIRST (it must catch invented claims), then the writer from
the remaining models, preferring a different family. Overrides (source='override') survive re-benchmarks, and
`validate_assignment` rejects any state where the top writer is the top fact-checker. `checker_allowed` enforces
independence per document lineage: the checker must differ from every model that authored any version.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from hq.db import repo
from hq.db.conn import tx
from hq.models.discovery.base import model_family
from hq.util.timeutil import now_iso

ROLE_TASKS: dict[str, tuple[str, ...]] = {
    "fact_checker": ("factcheck",),
    "writer": ("write_paragraph",),
    "parser": ("parse_job",),
    "eligibility": ("eligibility",),
    "title_filter": ("title_filter",),
    "classifier": ("classify_email",),
    "summarizer": ("parse_job", "write_paragraph"),
}
ROLE_ORDER = ("fact_checker", "writer", "parser", "eligibility", "title_filter", "classifier", "summarizer")
TARGET_TOK_S = {"fact_checker": 40, "writer": 30, "parser": 40, "eligibility": 40, "title_filter": 80,
                "classifier": 60, "summarizer": 40}
ROLE_LABEL = {"fact_checker": "Fact-checker", "writer": "Writer", "parser": "Job parser", "eligibility": "Eligibility",
              "title_filter": "Title filter", "classifier": "Email classifier", "summarizer": "Summarizer"}
# agent role → model role (agent YAML `role` values)
AGENT_ROLE = {"scout": "parser", "verifier": "eligibility", "writer": "writer", "factchecker": "fact_checker",
              "inbox": "classifier", "strategist": "summarizer", "resume": "writer", "followup": "writer"}


class IndependenceError(ValueError):
    pass


@dataclass
class Bench:
    task: str
    accuracy: float | None
    precision: float | None
    recall: float | None
    f1: float | None
    json_valid: float | None
    tok_s: float | None
    ram_gb: float | None


def latest_benchmarks(conn: sqlite3.Connection) -> dict[str, dict[str, Bench]]:
    out: dict[str, dict[str, Bench]] = {}
    for r in conn.execute(
            "SELECT b.* FROM benchmarks b JOIN (SELECT model_id, task, MAX(created_at) AS m FROM benchmarks "
            "GROUP BY model_id, task) l ON l.model_id=b.model_id AND l.task=b.task AND l.m=b.created_at"):
        out.setdefault(r["model_id"], {})[r["task"]] = Bench(
            r["task"], r["accuracy"], r["precision"], r["recall"], r["f1"],
            r["json_valid_after_repair"] if r["json_valid_after_repair"] is not None else r["json_valid_first"],
            r["tok_s_gen"], r["peak_footprint_gb"])
    return out


def quality(role: str, b: Bench) -> float:
    if role == "fact_checker":
        return b.f1 if b.f1 is not None else (b.accuracy or 0.0)
    if role == "title_filter":
        return b.f1 if b.f1 is not None else (b.accuracy or 0.0)
    return b.accuracy or 0.0


def meets_floor(role: str, benches: dict[str, Bench]) -> tuple[bool, str | None]:
    if role == "fact_checker":
        b = benches.get("factcheck")
        if not b:
            return False, "not benchmarked"
        if (b.recall or 0) < 0.90:
            return False, f"recall on unsupported {b.recall or 0:.2f} < 0.90"
        if (b.precision or 0) < 0.85:
            return False, f"precision on ok {b.precision or 0:.2f} < 0.85"
    if role == "classifier":
        b = benches.get("classify_email")
        if not b:
            return False, "not benchmarked"
        if (b.recall or 0) < 0.95:
            return False, f"interview+offer recall {b.recall or 0:.2f} < 0.95"
    return True, None


def role_score(role: str, benches: dict[str, Bench], ram_gb: float | None, pool_gb: float) -> float | None:
    tasks = [benches[t] for t in ROLE_TASKS[role] if t in benches]
    if not tasks:
        return None
    q = sum(quality(role, b) for b in tasks) / len(tasks)
    jv = sum((b.json_valid if b.json_valid is not None else 0.0) for b in tasks) / len(tasks)
    speeds = [b.tok_s for b in tasks if b.tok_s]
    speed = min(1.0, (sum(speeds) / len(speeds)) / TARGET_TOK_S[role]) if speeds else 0.0
    ram = ram_gb or max((b.ram_gb or 0) for b in tasks) or 0.0
    fit = max(0.0, 1.0 - ram / pool_gb) if pool_gb else 0.0
    return round(0.60 * q + 0.15 * jv + 0.15 * speed + 0.10 * fit, 4)


def _usable_models(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {r["id"]: dict(r) for r in conn.execute(
        "SELECT * FROM models WHERE complete=1 AND runtime_supported=1 AND modality='chat' AND status!='broken'")}


def current(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in conn.execute("SELECT * FROM role_assignments ORDER BY role, rank"):
        out.setdefault(r["role"], []).append(dict(r))
    return out


def ranked(conn: sqlite3.Connection, role: str) -> list[str]:
    return [r["model_id"] for r in conn.execute(
        "SELECT model_id FROM role_assignments WHERE role=? ORDER BY rank", (role,))]


def assign(conn: sqlite3.Connection, pool_gb: float = 30.0) -> dict[str, list[dict[str, Any]]]:
    """Recompute auto rankings from the latest benchmarks, keep overrides, fact-checker first. Own transaction."""
    benches = latest_benchmarks(conn)
    models = _usable_models(conn)
    overrides = {r["role"]: r["model_id"] for r in conn.execute(
        "SELECT role, model_id FROM role_assignments WHERE source='override' AND rank=0")}
    plan: dict[str, list[tuple[str, float, str, str | None]]] = {}
    for role in ROLE_ORDER:
        scored = []
        for mid, m in models.items():
            b = benches.get(mid, {})
            s = role_score(role, b, m.get("measured_ram_gb") or m.get("est_ram_gb"), pool_gb)
            if s is None:
                continue
            ok, why = meets_floor(role, b)
            scored.append((mid, s, ok, why))
        passing = [x for x in scored if x[2]]
        below = [x for x in scored if not x[2]]
        if role == "writer" and plan.get("fact_checker"):
            checker = plan["fact_checker"][0][0]
            cfam = model_family(models.get(checker, {}).get("name", checker))
            passing = [x for x in passing if x[0] != checker]
            # prefer a different family from the checker: a small penalty keeps same-family models as fallbacks
            passing.sort(key=lambda x: -(x[1] - (0.05 if model_family(models[x[0]]["name"]) == cfam else 0)))
        else:
            passing.sort(key=lambda x: -x[1])
        below.sort(key=lambda x: -x[1])
        rows = [(mid, s, "auto", None) for mid, s, _, _ in passing]
        if not passing and below:
            # nobody meets the floor: keep them ranked as a pre-screen (the fact gate then needs Claude sign-off;
            # inbox locks still come from the deterministic rules)
            suffix = "; needs_claude_signoff" if role == "fact_checker" else ""
            rows = [(mid, s, "auto", f"below floor: {why}{suffix}") for mid, s, _, why in below]
        if role in overrides and overrides[role] in models:
            ov = overrides[role]
            rows = [(ov, next((s for m, s, _, _ in scored if m == ov), 0.0), "override", None)] + \
                   [r for r in rows if r[0] != ov]
        plan[role] = rows
    with tx(conn):
        conn.execute("DELETE FROM role_assignments")
        for role, rows in plan.items():
            for rank, (mid, score, source, reason) in enumerate(rows):
                conn.execute("INSERT INTO role_assignments(role, model_id, rank, score, source, reason, created_at) "
                             "VALUES (?,?,?,?,?,?,?)", (role, mid, rank, score, source, reason, now_iso()))
        validate_assignment(conn)
        repo.emit(conn, "roles.updated", "Role assignments updated", data={"roles": roles_json(conn)})
    return current(conn)


def validate_assignment(conn: sqlite3.Connection) -> None:
    w, c = ranked(conn, "writer"), ranked(conn, "fact_checker")
    if w and c and w[0] == c[0]:
        raise IndependenceError(f"writer and fact-checker are both {w[0]}; they must differ")


def set_override(conn: sqlite3.Connection, role: str, model_id: str) -> None:
    """Pin a model to the top of a role. Rejects writer == fact-checker. Own transaction."""
    if role not in ROLE_TASKS:
        raise ValueError(f"unknown role {role}")
    if not conn.execute("SELECT 1 FROM models WHERE id=?", (model_id,)).fetchone():
        raise ValueError(f"unknown model {model_id}")
    other = {"writer": "fact_checker", "fact_checker": "writer"}.get(role)
    if other and (ranked(conn, other)[:1] == [model_id]):
        raise IndependenceError(f"{model_id} is the {ROLE_LABEL[other].lower()}; writer and fact-checker must differ")
    rows = [r for r in ranked(conn, role) if r != model_id]
    with tx(conn):
        conn.execute("DELETE FROM role_assignments WHERE role=?", (role,))
        conn.execute("INSERT INTO role_assignments(role, model_id, rank, score, source, reason, created_at) "
                     "VALUES (?,?,0,NULL,'override',NULL,?)", (role, model_id, now_iso()))
        for i, mid in enumerate(rows, start=1):
            conn.execute("INSERT INTO role_assignments(role, model_id, rank, score, source, reason, created_at) "
                         "VALUES (?,?,?,NULL,'auto',NULL,?)", (role, mid, i, now_iso()))
        validate_assignment(conn)
        repo.emit(conn, "roles.updated", f"{ROLE_LABEL[role]} pinned to {model_id}", data={"roles": roles_json(conn)})


def reset_override(conn: sqlite3.Connection, role: str, pool_gb: float = 30.0) -> None:
    with tx(conn):
        conn.execute("UPDATE role_assignments SET source='auto' WHERE role=?", (role,))
    assign(conn, pool_gb)


def checker_allowed(checker_model: str, lineage_models: Iterable[str]) -> bool:
    """The checker must differ from every model that authored any version of the document (incl. Claude)."""
    return checker_model not in {m for m in lineage_models if m}


def needs_claude_signoff(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT reason FROM role_assignments WHERE role='fact_checker' AND rank=0").fetchone()
    return row is None or bool(row["reason"] and "needs_claude_signoff" in row["reason"])


def roles_json(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = current(conn)
    out = []
    for role in ROLE_ORDER:
        rows = cur.get(role, [])
        out.append({"role": role, "label": ROLE_LABEL[role],
                    "ranked": [{"model_id": r["model_id"], "score": r["score"], "source": r["source"],
                                "reason": r["reason"]} for r in rows],
                    "needs_claude_signoff": role == "fact_checker" and (not rows or bool(
                        rows[0]["reason"] and "needs_claude_signoff" in rows[0]["reason"]))})
    return out
