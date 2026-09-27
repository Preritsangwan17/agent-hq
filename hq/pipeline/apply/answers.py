"""Form answers from the answer bank (config/answer_bank.yaml, CONTRACT_C §2). Values come only from verified
facts or fields Prerit confirmed; anything else is left for him. Sensitive IDs are never answered. Gender uses the
confirmed profile choice; other EEO questions use "Prefer not to say" only when that option exists."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from hq import settings as paths
from hq.profile.fields import confirmed_value

DEFAULT_QUESTIONS = [
    {"label": "First name", "required": True}, {"label": "Last name", "required": True},
    {"label": "Email", "required": True}, {"label": "Phone", "required": True},
    {"label": "Resume/CV", "required": True, "type": "file"}, {"label": "Cover letter", "required": False, "type": "file"},
    {"label": "LinkedIn profile", "required": False}, {"label": "Website / GitHub", "required": False},
    {"label": "Are you legally authorized to work in the country of this role?", "required": True},
    {"label": "Will you now or in the future require visa sponsorship?", "required": True},
    {"label": "When can you start?", "required": False},
]


@dataclass
class Answer:
    label: str
    value: str
    status: str            # filled | needs_prerit | never | file
    required: bool
    copy: bool = True
    note: str | None = None
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@lru_cache(maxsize=2)
def _bank(path: str, mtime: float) -> list[dict[str, Any]]:
    return (yaml.safe_load(Path(path).read_text()) or {}).get("answers", [])


def bank() -> list[dict[str, Any]]:
    p = paths.CONFIG_DIR / "answer_bank.yaml"
    return _bank(str(p), p.stat().st_mtime)


def seed_answer_bank(conn: sqlite3.Connection) -> int:
    import json

    n = 0
    for a in bank():
        cur = conn.execute(
            "INSERT INTO answer_bank(id, question_pattern, answer_template, fact_ids_json, field_keys_json, policy) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET question_pattern=excluded.question_pattern, "
            "answer_template=excluded.answer_template, fact_ids_json=excluded.fact_ids_json, "
            "field_keys_json=excluded.field_keys_json, policy=excluded.policy",
            (a["id"], a["pattern"], a.get("template"), json.dumps(a.get("facts", [])), json.dumps(a.get("fields", [])),
             a.get("policy", "needs_prerit")))
        n += cur.rowcount
    return n


def resolve(conn: sqlite3.Connection, label: str, *, required: bool = False, options: list[str] | None = None,
            qtype: str | None = None) -> Answer:
    if qtype == "file" or re.search(r"\b(resume|cv|cover letter)\b", label, re.I) and qtype in (None, "file"):
        return Answer(label, "attached from this pack", "file", required, copy=False)
    low = label.lower()
    if re.fullmatch(r"\s*first name\s*\*?\s*", low):
        return Answer(label, "Prerit", "filled", required, source="F-NAME")
    if re.fullmatch(r"\s*last name\s*\*?\s*", low):
        return Answer(label, "Sangwan", "filled", required, source="F-NAME")
    for a in bank():
        if not re.search(a["pattern"], low):
            continue
        policy = a.get("policy", "needs_prerit")
        if policy == "never":
            return Answer(label, "", "never", required, copy=False, note="HQ never provides this; decide yourself")
        if policy == "auto_if_option":
            opts = [o for o in (options or []) if re.search(r"prefer not|decline|don'?t wish", o, re.I)]
            if opts:
                return Answer(label, opts[0], "filled", required, source=a["id"])
            if options is None:
                return Answer(label, "Prefer not to say", "filled", required, source=a["id"],
                              note="pick “Prefer not to say” (or the closest decline option)")
            return Answer(label, "", "needs_prerit", required, note="no 'prefer not to say' option")
        fields = a.get("fields") or []
        values = {f: confirmed_value(conn, f) for f in fields}
        if policy == "needs_prerit" or any(v is None for v in values.values()):
            missing = [f for f, v in values.items() if v is None]
            return Answer(label, "", "needs_prerit", required,
                          note=f"confirm {', '.join(missing)} in Settings › Profile" if missing else None)
        if policy == "confirmed_choice":
            value = values[fields[0]]
            if options is not None:
                match = next((o for o in options if o.strip().casefold() == value.casefold()), None)
                if match is None:
                    return Answer(label, "", "needs_prerit", required, note="confirmed answer is not an available option")
                value = match
            else:
                value = value.capitalize()
            return Answer(label, value, "filled", required, source=a["id"])
        template = a.get("template") or ""
        try:
            value = template.format(**values)
        except KeyError:
            return Answer(label, "", "needs_prerit", required)
        return Answer(label, value, "filled", required, source=a["id"])
    return Answer(label, "", "needs_prerit", required, note="no stored answer")


def answer_all(conn: sqlite3.Connection, questions: list[dict[str, Any]] | None) -> list[Answer]:
    return [resolve(conn, q["label"], required=bool(q.get("required")), options=q.get("options"),
                    qtype=q.get("type")) for q in (questions or DEFAULT_QUESTIONS)]
