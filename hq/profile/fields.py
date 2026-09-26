"""Personal fields Prerit confirms in Settings › Profile & Facts (CONTRACT_C §2).

Unconfirmed values are never used in outbound text: `confirmed_value()` returns None unless
`confirmed_by_prerit=1`, and `share_policy='never'` fields are never returned for outbound use at all.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from hq.util.timeutil import now_iso


class FieldError(ValueError):
    pass


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    kind: str                  # text|number|choice|windows|date
    share_policy: str = "on_request"
    required_for_live: bool = False
    hint: str = ""
    choices: tuple[str, ...] = ()


FIELD_DEFS: tuple[FieldDef, ...] = (
    FieldDef("phone", "Phone number", "text", "forms", True, "With country code, e.g. +91 98xxxxxxx. Never sent to Grok or any cloud model."),
    FieldDef("cgpa", "CGPA (current)", "number", "forms", True, "Out of 10, as on your latest grade sheet."),
    FieldDef("marks_x", "Class X marks", "text", "on_request", False, "Percentage or CGPA, e.g. 92%."),
    FieldDef("marks_xii", "Class XII marks", "text", "on_request", False, "Percentage, e.g. 88%."),
    FieldDef("grad_year", "Expected graduation year", "number", "forms", True, "e.g. 2029."),
    FieldDef("semester", "Current semester", "number", "forms", True, "1–8."),
    FieldDef("home_city", "Home city", "text", "forms", True, "Where you live during term."),
    FieldDef("home_living_cost_inr", "Living cost at home (₹/month)", "number", "never", False,
             "Used for remote-role pay ratios; never shared."),
    FieldDef("availability_windows", "Availability windows", "windows", "forms", True,
             "Dates you can work, hours per week and mode (remote/onsite)."),
    FieldDef("hours_cap_term", "Max hours/week during term", "number", "forms", True, "e.g. 20."),
    FieldDef("passport", "Passport", "choice", "on_request", True, "Needed for roles abroad.", ("yes", "no")),
    FieldDef("dob", "Date of birth", "date", "never", False, "Only for forms that require it; never auto-filled."),
    FieldDef("address", "Postal address", "text", "never", False, "Never auto-filled."),
)

DEFS = {d.key: d for d in FIELD_DEFS}
SHARE_POLICIES = ("forms", "on_request", "never")


def _num(lo: float, hi: float, integer: bool = False) -> Callable[[Any], str]:
    def check(v: Any) -> str:
        try:
            n = float(str(v).strip())
        except ValueError:
            raise FieldError("expected a number") from None
        if not lo <= n <= hi:
            raise FieldError(f"must be between {lo:g} and {hi:g}")
        return str(int(n)) if integer else f"{n:g}"
    return check


def _windows(v: Any) -> str:
    items = json.loads(v) if isinstance(v, str) else v
    if not isinstance(items, list):
        raise FieldError("expected a list of windows")
    out = []
    for w in items:
        if not isinstance(w, dict):
            raise FieldError("each window needs from, to, hours_per_week and mode")
        f, t = str(w.get("from", "")), str(w.get("to", ""))
        if not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", f) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", t)) or t < f:
            raise FieldError("window dates must be YYYY-MM-DD with from ≤ to")
        hours = float(w.get("hours_per_week") or 0)
        if not 1 <= hours <= 60:
            raise FieldError("hours per week must be 1–60")
        mode = w.get("mode", "any")
        if mode not in ("remote", "onsite", "any"):
            raise FieldError("mode must be remote, onsite or any")
        out.append({"from": f, "to": t, "hours_per_week": hours, "mode": mode})
    return json.dumps(out)


VALIDATORS: dict[str, Callable[[Any], str]] = {
    "cgpa": _num(0, 10),
    "grad_year": _num(2025, 2035, integer=True),
    "semester": _num(1, 12, integer=True),
    "home_living_cost_inr": _num(1000, 1_000_000, integer=True),
    "hours_cap_term": _num(1, 60, integer=True),
    "availability_windows": _windows,
}


def validate_value(key: str, value: Any) -> str | None:
    d = DEFS.get(key)
    if d is None:
        raise FieldError(f"unknown profile field '{key}'")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if d.kind == "choice":
        v = str(value).strip().lower()
        if v not in d.choices:
            raise FieldError(f"must be one of {', '.join(d.choices)}")
        return v
    if d.kind == "date":
        v = str(value).strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise FieldError("expected YYYY-MM-DD")
        return v
    if key in VALIDATORS:
        return VALIDATORS[key](value)
    v = str(value).strip()
    if len(v) > 500:
        raise FieldError("too long")
    return v


def seed_fields(conn: sqlite3.Connection) -> int:
    added = 0
    for d in FIELD_DEFS:
        cur = conn.execute(
            "INSERT OR IGNORE INTO profile_fields(key, label, value, share_policy, confirmed_by_prerit, required_for_live) "
            "VALUES (?,?,NULL,?,0,?)", (d.key, d.label, d.share_policy, int(d.required_for_live)))
        added += cur.rowcount
    return added


def field_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    order = {d.key: i for i, d in enumerate(FIELD_DEFS)}
    rows = [dict(r) for r in conn.execute("SELECT * FROM profile_fields")]
    return sorted(rows, key=lambda r: order.get(r["key"], 999))


def field_json(row: dict[str, Any]) -> dict[str, Any]:
    d = DEFS.get(row["key"])
    value: Any = row["value"]
    if d and d.kind == "windows" and value:
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    return {"key": row["key"], "label": row["label"], "value": value, "share_policy": row["share_policy"],
            "confirmed": bool(row["confirmed_by_prerit"]), "required_for_live": bool(row["required_for_live"]),
            "updated_at": row["updated_at"], "kind": d.kind if d else "text", "hint": d.hint if d else "",
            "choices": list(d.choices) if d else []}


def update_field(conn: sqlite3.Connection, key: str, value: Any, share_policy: str | None = None) -> dict[str, Any]:
    """Validate and store a field Prerit edited; saving marks it confirmed. Caller owns the transaction."""
    cleaned = validate_value(key, value)
    if share_policy is not None and share_policy not in SHARE_POLICIES:
        raise FieldError(f"share_policy must be one of {', '.join(SHARE_POLICIES)}")
    row = conn.execute("SELECT * FROM profile_fields WHERE key=?", (key,)).fetchone()
    if row is None:
        seed_fields(conn)
    conn.execute(
        "UPDATE profile_fields SET value=?, share_policy=COALESCE(?, share_policy), confirmed_by_prerit=?, updated_at=? "
        "WHERE key=?", (cleaned, share_policy, int(cleaned is not None), now_iso(), key))
    return dict(conn.execute("SELECT * FROM profile_fields WHERE key=?", (key,)).fetchone())


def confirmed_value(conn: sqlite3.Connection, key: str, *, outbound: bool = True) -> str | None:
    """The value agents may use, or None. Outbound use also excludes share_policy 'never'."""
    row = conn.execute("SELECT value, share_policy, confirmed_by_prerit FROM profile_fields WHERE key=?", (key,)).fetchone()
    if row is None or not row["confirmed_by_prerit"] or row["value"] is None:
        return None
    if outbound and row["share_policy"] == "never":
        return None
    return row["value"]


def confirmed_fields(conn: sqlite3.Connection, *, outbound: bool = True) -> dict[str, str]:
    out = {}
    for r in conn.execute("SELECT key FROM profile_fields"):
        v = confirmed_value(conn, r["key"], outbound=outbound)
        if v is not None:
            out[r["key"]] = v
    return out
