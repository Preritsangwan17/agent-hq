"""Import the pre-HQ shortlist (the old `applications/` folder) as frozen, historical opportunities.

    python -m hq.importer.legacy --src legacy/applications [--db data/hq.db] [--offline]

Idempotent: opportunities upsert on canonical_key "legacy:<id>", and applications, documents and needs are
matched on stable keys, so a second run changes nothing. Nothing here sends anything: every application is
`historical_frozen` until Prerit says which ones he actually sent (one `confirm_legacy` need asks exactly that).
letters.py is read with `ast` (constants and f-strings over those constants only); it is never executed.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hq import settings
from hq.db.conn import connect, dumps, tx
from hq.db.migrate import migrate
from hq.pipeline.verify import pay as pay_mod
from hq.pipeline.verify.fx import FxRates
from hq.pipeline.verify.living_cost import LivingCosts, city_coords
from hq.util.ids import new_id
from hq.util.timeutil import now_iso, to_iso

SOURCE_LABEL = "legacy shortlist 2026-09-26"
AUTHOR = "legacy_import"
DRAFT_MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-DWQ"
FROZEN_REASON = "legacy shortlist item; whether it was sent is unknown (answer the Needs Prerit item)"
SKIPPED_REASON = "dropped; no final letter"
CONFIRM_TITLE = "Which of these 11 legacy applications did you actually send?"
FACT_TITLE = 'Confirm fact rewording: "users with 200+ ratings" -> "users with more than 200 ratings"'
TEEP_ID = "07-nccu-teep"
SKIPPED_IDS = {"07-codingninjas"}

# Document kind and on-disk file name for each letter (build.py wrote LETTERS[key] to these files).
LETTER_FILES = {"04-outlier": ("profile_summary", "profile_summary.txt"),
                TEEP_ID: ("cold_email", "email.txt"),
                "09-srfp": ("research_statement", "research_statement.txt")}
DEFAULT_LETTER = ("cover_letter", "cover_letter.txt")
RESUME_FILES = (("resume_pdf", "Prerit_Sangwan_Resume.pdf"), ("compact_pdf", "Prerit_Sangwan_Resume_compact.pdf"))

TEEP_ITEM = {
    "id": TEEP_ID,
    "company": "National Chung Cheng University (CCU)",
    "role": "TEEP research internship, MARS Lab (recommender systems)",
    "location": "Chiayi, Taiwan (CCU campus; Taiwan Experience Education Program)",
    "pay": "NT$15,000/month (TEEP minimum)",
    "apply": None,
    "about": ("Cold-email enquiry to Prof. Chiu's MARS lab (recommender systems and retrieval) about a TEEP "
              "(Taiwan Experience Education Program) internship. The lab listing was seen on the TEEP portal."),
    "angle": None,
}
TEEP_NOTES = (
    "RE-VERIFY before any reuse. (1) University: cychiu@ccu.edu.tw is National Chung Cheng University (CCU, Chiayi); "
    "the old folder name said NCCU (Chengchi), which is wrong. The email text itself names no university. "
    "(2) The lab/professor listing was never saved; the closest saved TEEP row is #36 'AI, information retrieval, "
    "data mining', CCU, application period 2026/04/01-2026/12/31 (teep.studyintaiwan.org/program/1689). "
    "(3) NT$15,000/month is the TEEP programme minimum, not a figure confirmed by the lab."
)


@dataclass(frozen=True)
class ItemMeta:
    kind: str
    role_type: str
    city: str | None
    country_iso2: str
    work_mode: str
    apply_channel: str
    deadline: str | None = None           # local calendar date
    deadline_tz: str = "Asia/Kolkata"
    deadline_confidence: str | None = None
    hours_per_week: float | None = None
    duration_months: float | None = None
    apply_email: str | None = None


# Curated facts about each legacy item that jobs.json does not hold in structured form.
META: dict[str, ItemMeta] = {
    "01-readyly": ItemMeta("internship", "software", None, "IN", "remote", "portal",
                           hours_per_week=20, duration_months=6),
    "02-logphase": ItemMeta("internship", "ml", None, "IN", "remote", "portal", deadline="2026-10-21",
                            deadline_confidence="low", duration_months=6),
    "03-reducate": ItemMeta("internship", "data", None, "IN", "remote", "portal", duration_months=6),
    "04-outlier": ItemMeta("freelance", "software", None, "IN", "remote", "portal", deadline_confidence="rolling"),
    "05-stripe": ItemMeta("internship", "software", "Bengaluru", "IN", "onsite", "ats_form"),
    "06-pharmaand": ItemMeta("internship", "ml", "Hyderabad", "IN", "onsite", "portal", duration_months=6),
    "07-codingninjas": ItemMeta("internship", "ml", "Gurugram", "IN", "unknown", "portal"),
    TEEP_ID: ItemMeta("research_internship", "research", "Chiayi", "TW", "onsite", "email", deadline="2026-12-31",
                      deadline_tz="Asia/Taipei", deadline_confidence="low", apply_email="cychiu@ccu.edu.tw"),
    "08-mlh": ItemMeta("fellowship", "software", None, "IN", "remote", "portal",
                       duration_months=round(12 * 7 / 30.4375, 2)),
    "09-srfp": ItemMeta("fellowship", "research", None, "IN", "onsite", "portal", deadline="2026-11-30",
                        deadline_confidence="medium"),
    "10-epfl": ItemMeta("research_internship", "research", "Lausanne", "CH", "onsite", "portal",
                        deadline="2026-11-29", deadline_tz="Europe/Zurich", deadline_confidence="medium"),
}
FALLBACK_META = ItemMeta("internship", "other", None, "IN", "unknown", "manual")


@dataclass
class ItemResult:
    legacy_id: str
    company: str
    stage: str
    action: str
    opp: dict[str, Any]


@dataclass
class ImportReport:
    src: str
    items: list[ItemResult] = field(default_factory=list)
    documents: dict[str, int] = field(default_factory=lambda: {"created": 0, "updated": 0, "unchanged": 0})
    needs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"created": 0, "updated": 0, "unchanged": 0}
        for item in self.items:
            out[item.action] += 1
        return out


# ── reading the old folder ────────────────────────────────────────────
def _literal_str(node: ast.AST, names: dict[str, str]) -> str:
    """Evaluate a string expression built only from literals, known names and f-strings over known names."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_str(node.left, names) + _literal_str(node.right, names)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif (isinstance(value, ast.FormattedValue) and value.conversion == -1 and value.format_spec is None):
                parts.append(_literal_str(value.value, names))
            else:
                raise ValueError(f"unsupported f-string part at line {getattr(value, 'lineno', '?')}")
        return "".join(parts)
    raise ValueError(f"unsupported expression {type(node).__name__} at line {getattr(node, 'lineno', '?')}")


def load_letters(path: Path) -> dict[str, str]:
    """LETTERS from letters.py, evaluated statically. Raises ValueError on anything but plain string building."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: dict[str, str] = {}
    letters: dict[str, str] | None = None
    for stmt in tree.body:
        if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)):
            continue
        target = stmt.targets[0].id
        if target == "LETTERS":
            if not isinstance(stmt.value, ast.Dict):
                raise ValueError("LETTERS is not a dict literal")
            letters = {}
            for key, value in zip(stmt.value.keys, stmt.value.values, strict=True):
                if key is None:
                    raise ValueError("LETTERS uses ** unpacking")
                letters[_literal_str(key, names)] = _literal_str(value, names)
        else:
            try:
                names[target] = _literal_str(stmt.value, names)
            except ValueError:
                pass  # non-string constants are irrelevant to the letters
    if letters is None:
        raise ValueError(f"no LETTERS dict in {path}")
    return letters


def load_items(src: Path) -> list[dict[str, Any]]:
    """jobs.json entries plus the TEEP item that only exists in letters.py and its folder."""
    jobs = json.loads((src / "jobs.json").read_text(encoding="utf-8"))
    items = [dict(job) for job in jobs]
    if not any(job.get("id") == TEEP_ID for job in items):
        items.append(dict(TEEP_ITEM))
    return sorted(items, key=lambda job: job["id"])


def default_src() -> Path:
    for candidate in (settings.ROOT / "legacy" / "applications", settings.ROOT / "applications"):
        if (candidate / "jobs.json").exists():
            return candidate
    return settings.ROOT / "legacy" / "applications"


# ── helpers ───────────────────────────────────────────────────────────
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _deadline_utc(day: str | None, tz: str) -> str | None:
    if not day:
        return None
    return to_iso(datetime.combine(date.fromisoformat(day), time(23, 59, 59), tzinfo=ZoneInfo(tz)))


def _norm_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _db_dir(conn: sqlite3.Connection) -> Path:
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main" and row[2]:
            return Path(row[2]).parent
    return settings.DATA


def _copy_artifact(source: Path, dest_dir: Path) -> tuple[Path, str]:
    """Copy into data/artifacts/legacy/<id>/ (the old folder is a temporary workspace). Returns (path, sha256)."""
    data = source.read_bytes()
    digest = _sha256_bytes(data)
    dest = dest_dir / source.name
    if not dest.exists() or _sha256_bytes(dest.read_bytes()) != digest:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    return dest, digest


def _changed(row: sqlite3.Row, values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if row[k] != v}


def _update(conn: sqlite3.Connection, table: str, row_id: str, values: dict[str, Any]) -> None:
    sets = ", ".join(f"{k}=?" for k in values)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*values.values(), row_id))


def _insert(conn: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    cols = ", ".join(values)
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(values))})", tuple(values.values()))


# ── the import ────────────────────────────────────────────────────────
def build_opportunity(job: dict[str, Any], fx: Any, living: Any) -> dict[str, Any]:
    """All opportunity columns except id, canonical_key and timestamps."""
    legacy_id = job["id"]
    meta = META.get(legacy_id, FALLBACK_META)
    parsed = pay_mod.parse_pay(job.get("pay"), hours_per_week=meta.hours_per_week,
                               duration_months=meta.duration_months)
    pay = pay_mod.normalize(parsed, fx, living, city=meta.city, country_iso2=meta.country_iso2,
                            work_mode=meta.work_mode, benefits={})
    coords = city_coords(meta.city, meta.country_iso2) if meta.city else None
    skipped = legacy_id in SKIPPED_IDS
    reason = SKIPPED_REASON if skipped else FROZEN_REASON
    if legacy_id == TEEP_ID:
        reason += "; CCU, lab and stipend must be re-verified before any reuse"
    return {
        "is_simulated": 0,
        "company_name": job["company"],
        "title": job["role"],
        "kind": meta.kind,
        "role_type": meta.role_type,
        "summary": job.get("about"),
        "location_raw": job.get("location"),
        "city": meta.city,
        "country_iso2": meta.country_iso2,
        "lat": coords[0] if coords else None,
        "lon": coords[1] if coords else None,
        "work_mode": meta.work_mode,
        "url": job.get("apply"),
        "apply_url": job.get("apply"),
        "apply_channel": meta.apply_channel,
        "apply_email": meta.apply_email,
        "deadline_at": _deadline_utc(meta.deadline, meta.deadline_tz),
        "deadline_confidence": meta.deadline_confidence,
        "duration_months": meta.duration_months,
        "hours_per_week": meta.hours_per_week,
        **pay,
        "stage": "skipped" if skipped else "frozen",
        "stage_reason": reason,
        "source_label": SOURCE_LABEL,
        "notes_unverified": TEEP_NOTES if legacy_id == TEEP_ID else job.get("angle"),
    }


def _upsert_company(conn: sqlite3.Connection, name: str) -> str:
    norm = _norm_name(name)
    row = conn.execute("SELECT id FROM companies WHERE norm_name=?", (norm,)).fetchone()
    if row:
        return row["id"]
    company_id = new_id()
    _insert(conn, "companies", {"id": company_id, "name": name, "norm_name": norm})
    return company_id


def _upsert_opportunity(conn: sqlite3.Connection, key: str, values: dict[str, Any], now: str) -> tuple[str, str]:
    row = conn.execute("SELECT * FROM opportunities WHERE canonical_key=?", (key,)).fetchone()
    if row is None:
        opp_id = new_id()
        _insert(conn, "opportunities", {"id": opp_id, "canonical_key": key, **values,
                                        "first_seen_at": now, "updated_at": now})
        return opp_id, "created"
    if row["stage_override"]:
        values = {k: v for k, v in values.items() if k not in ("stage", "stage_reason")}
    changed = _changed(row, values)
    if not changed:
        return row["id"], "unchanged"
    _update(conn, "opportunities", row["id"], {**changed, "updated_at": now})
    return row["id"], "updated"


def _upsert_document(conn: sqlite3.Connection, report: ImportReport, opp_id: str, app_id: str,
                     values: dict[str, Any], now: str) -> str:
    row = conn.execute("SELECT * FROM documents WHERE opportunity_id=? AND kind=? AND author_agent=?",
                       (opp_id, values["kind"], AUTHOR)).fetchone()
    values = {**values, "application_id": app_id, "opportunity_id": opp_id, "author_agent": AUTHOR,
              "status": "historical"}
    if row is None:
        doc_id = new_id()
        _insert(conn, "documents", {"id": doc_id, **values, "created_at": now})
        report.documents["created"] += 1
        return doc_id
    changed = _changed(row, values)
    if changed:
        _update(conn, "documents", row["id"], changed)
    report.documents["updated" if changed else "unchanged"] += 1
    return row["id"]


def _upsert_application(conn: sqlite3.Connection, opp_id: str, channel: str, status: str, now: str) -> str:
    row = conn.execute("SELECT * FROM applications WHERE opportunity_id=? ORDER BY created_at, id LIMIT 1",
                       (opp_id,)).fetchone()
    if row is None:
        app_id = new_id()
        _insert(conn, "applications", {"id": app_id, "opportunity_id": opp_id, "channel": channel,
                                       "status": status, "created_at": now, "updated_at": now})
        return app_id
    values: dict[str, Any] = {"channel": channel}
    if row["status"] in ("historical_frozen", "skipped"):  # never undo what Prerit later confirmed
        values["status"] = status
    changed = _changed(row, values)
    if changed:
        _update(conn, "applications", row["id"], {**changed, "updated_at": now})
    return row["id"]


def _upsert_need(conn: sqlite3.Connection, kind: str, title: str, values: dict[str, Any], now: str) -> tuple[str, str]:
    row = conn.execute("SELECT * FROM needs_prerit WHERE kind=? AND title=? ORDER BY created_at LIMIT 1",
                       (kind, title)).fetchone()
    if row is None:
        need_id = new_id()
        _insert(conn, "needs_prerit", {"id": need_id, "kind": kind, "title": title, **values, "status": "open",
                                       "created_at": now})
        return need_id, "created"
    changed = _changed(row, values)  # status is Prerit's; content may be refreshed
    if changed:
        _update(conn, "needs_prerit", row["id"], changed)
    return row["id"], "updated" if changed else "unchanged"


def _confirm_need(results: list[ItemResult]) -> dict[str, Any]:
    lines = [
        "Agent HQ has **not** sent any of these and will not touch them until you answer. They are imported as "
        "`historical_frozen` (Coding Ninjas as `skipped`). For each one, say whether you sent it yourself and "
        "roughly when. Unsent items can later be re-drafted through the gates; the old letters stay read-only.",
        "",
        "| # | Company | Role | Channel | Stage |",
        "|---|---|---|---|---|",
    ]
    answers = []
    for n, item in enumerate(results, 1):
        opp = item.opp
        channel = opp["apply_email"] or opp["url"] or "-"
        lines.append(f"| {n} | {opp['company_name']} | {opp['title']} | {opp['apply_channel']}: {channel} | "
                     f"{opp['stage']} |")
        answers.append({"label": f"{n}. {opp['company_name']}", "value": f"{opp['title']} ({opp['stage']})"})
    return {"instructions_md": "\n".join(lines), "answers_json": dumps(answers), "files_json": "[]",
            "priority": 80, "est_minutes": 3}


def _fact_need(letters: dict[str, str]) -> dict[str, Any]:
    affected = sorted(k for k, text in letters.items() if "200+" in text or "at least 200" in text)
    lines = [
        "The Book Recommendation System keeps users with `value_counts() > 200`, i.e. **more than 200** ratings. "
        '"200+" and "at least 200" both mean 200 or more, which overstates the filter by one rating.',
        "",
        'Proposed fact: "kept users with more than 200 ratings". Once you confirm, new drafts and the '
        "regenerated résumé use it; the historical letters below are left untouched as history.",
        "",
        "Historical letters that use the old wording: " + (", ".join(f"`{k}`" for k in affected) or "none") + ".",
        "The old résumé bullet (build.py) says \"users with 200+ ratings\" too.",
    ]
    answers = [{"label": "New wording", "value": "kept users with more than 200 ratings", "copy": True}]
    return {"instructions_md": "\n".join(lines), "answers_json": dumps(answers), "files_json": "[]",
            "priority": 60, "est_minutes": 1}


def import_legacy(conn: sqlite3.Connection, src: Path, *, fx: Any = None, living: Any = None,
                  artifacts_dir: Path | None = None) -> ImportReport:
    """Upsert every legacy item. Network (FX) work happens before the single write transaction."""
    src = Path(src)
    report = ImportReport(src=str(src))
    db_dir = _db_dir(conn)
    fx = fx or FxRates(cache_path=db_dir / "fx" / "rates.json")
    living = living or LivingCosts(fx=fx)
    artifacts_dir = Path(artifacts_dir) if artifacts_dir else db_dir / "artifacts" / "legacy"

    try:
        letters = load_letters(src / "letters.py")
    except (OSError, ValueError, SyntaxError) as exc:
        letters = {}
        report.warnings.append(f"letters.py not read: {exc}")
    jobs = load_items(src)
    planned = [(job, build_opportunity(job, fx, living)) for job in jobs]
    now = now_iso()

    with tx(conn):
        for job, values in planned:
            legacy_id = job["id"]
            values = {**values, "company_id": _upsert_company(conn, values["company_name"])}
            opp_id, action = _upsert_opportunity(conn, f"legacy:{legacy_id}", values, now)
            conn.execute("INSERT OR IGNORE INTO opportunity_sources (opportunity_id, source_id, external_id, "
                         "source_url, first_seen, last_seen, raw_path) VALUES (?, 'legacy', ?, ?, ?, ?, ?)",
                         (opp_id, legacy_id, job.get("apply"), now, now, str(src / "jobs.json")))
            skipped = legacy_id in SKIPPED_IDS
            app_id = _upsert_application(conn, opp_id, values["apply_channel"],
                                         "skipped" if skipped else "historical_frozen", now)
            letter_doc_id = resume_doc_id = None
            folder = src / legacy_id
            if legacy_id in letters and not skipped:
                kind, file_name = LETTER_FILES.get(legacy_id, DEFAULT_LETTER)
                text = letters[legacy_id]
                content_path = None
                on_disk = folder / file_name
                if on_disk.exists():
                    if on_disk.read_text(encoding="utf-8") != text:
                        report.warnings.append(f"{legacy_id}: {file_name} differs from letters.py (letters.py used)")
                    content_path = str(_copy_artifact(on_disk, artifacts_dir / legacy_id)[0])
                letter_doc_id = _upsert_document(conn, report, opp_id, app_id, {
                    "kind": kind, "version": 1, "content_text": text, "content_path": content_path,
                    "sha256": _sha256_bytes(text.encode()), "author_model": None,
                    "lineage_models_json": dumps([DRAFT_MODEL]),
                }, now)
            elif not skipped:
                report.warnings.append(f"{legacy_id}: no letter in letters.py")
            for kind, file_name in RESUME_FILES:
                pdf = folder / file_name
                if skipped or not pdf.exists():
                    continue
                path, digest = _copy_artifact(pdf, artifacts_dir / legacy_id)
                doc_id = _upsert_document(conn, report, opp_id, app_id, {
                    "kind": kind, "version": 1, "content_text": None, "content_path": str(path), "sha256": digest,
                    "author_model": None, "lineage_models_json": "[]",
                }, now)
                resume_doc_id = resume_doc_id or doc_id
            app_row = conn.execute("SELECT letter_doc_id, resume_doc_id FROM applications WHERE id=?",
                                   (app_id,)).fetchone()
            if (app_row["letter_doc_id"], app_row["resume_doc_id"]) != (letter_doc_id, resume_doc_id):
                _update(conn, "applications", app_id, {"letter_doc_id": letter_doc_id,
                                                       "resume_doc_id": resume_doc_id, "updated_at": now})
            opp_row = dict(conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,)).fetchone())
            report.items.append(ItemResult(legacy_id, values["company_name"], opp_row["stage"], action, opp_row))

        need_id, need_action = _upsert_need(conn, "confirm_legacy", CONFIRM_TITLE, _confirm_need(report.items), now)
        report.needs["confirm_legacy"] = f"{need_id} ({need_action})"
        if letters:
            need_id, need_action = _upsert_need(conn, "decision", FACT_TITLE, _fact_need(letters), now)
            report.needs["decision"] = f"{need_id} ({need_action})"

        counts = report.counts()
        message = (f"Legacy import: {len(report.items)} items ({counts['created']} new, {counts['updated']} updated, "
                   f"{counts['unchanged']} unchanged); nothing sent")
        conn.execute("INSERT INTO events (ts, type, level, message, data_json) VALUES (?, 'log', 'info', ?, ?)",
                     (now, message, dumps({"source": "legacy_import", **counts, "documents": report.documents})))
        _insert(conn, "audit_log", {"id": new_id(), "ts": now, "actor": "importer", "action": "legacy_import",
                                    "target": str(src), "after_json": dumps({**counts, "warnings": report.warnings})})
    return report


# ── CLI ───────────────────────────────────────────────────────────────
def _inr(value: float | None) -> str:
    return "-" if value is None else f"₹{value:,.0f}"


def pay_label(opp: dict[str, Any]) -> str:
    status = opp["pay_status"]
    lo, hi = opp["pay_monthly_inr_min"], opp["pay_monthly_inr_max"]
    if lo is not None or hi is not None:
        if lo is None:
            return f"up to {_inr(hi)}"
        if hi is None:
            return f"{_inr(lo)}+"
        return _inr(lo) if lo == hi else f"{_inr(lo)}-{hi:,.0f}"
    if opp["pay_hourly_inr_min"] is not None:
        lo_h, hi_h = opp["pay_hourly_inr_min"], opp["pay_hourly_inr_max"]
        span = _inr(lo_h) if lo_h == hi_h else f"{_inr(lo_h)}-{hi_h:,.0f}"
        return f"{span}/h (hours unknown)"
    return {"unknown": "unknown", "unpaid": "unpaid", "fee_required": "FEE REQUIRED"}.get(status, status)


def format_table(report: ImportReport) -> str:
    rows = [("id", "company", "stage", "₹/month", "ratio", "living cost")]
    for item in report.items:
        opp = item.opp
        ratio = "-" if opp["pay_ratio"] is None else f"{opp['pay_ratio']:.2f}x"
        living = _inr(opp["living_cost_monthly_inr"])
        rows.append((item.legacy_id, item.company[:38], item.stage, pay_label(opp), ratio, living))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)) for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the legacy applications folder as frozen items.")
    parser.add_argument("--src", type=Path, default=None,
                        help="old applications folder (default: legacy/applications)")
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB (default: HQ_DB_PATH or data/hq.db)")
    parser.add_argument("--offline", action="store_true", help="use config/fx_seed.json only (sets HQ_OFFLINE=1)")
    args = parser.parse_args(argv)
    if args.offline:
        os.environ["HQ_OFFLINE"] = "1"
    src = args.src or default_src()
    if not (src / "jobs.json").exists():
        print(f"error: {src}/jobs.json not found (pass --src)", file=sys.stderr)
        return 2
    db_path = args.db or settings.DB_PATH
    conn = connect(db_path)
    try:
        migrate(conn)
        report = import_legacy(conn, src)
    finally:
        conn.close()
    counts = report.counts()
    print(f"Imported {len(report.items)} legacy items from {src} into {db_path}")
    print(f"  opportunities: {counts['created']} new, {counts['updated']} updated, {counts['unchanged']} unchanged")
    print(f"  documents: {report.documents}")
    print(f"  needs: {report.needs}")
    for warning in report.warnings:
        print(f"  warning: {warning}")
    print()
    print(format_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
