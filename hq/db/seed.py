"""Default settings (CONTRACT §3), seeding, and typed get/set helpers for the `settings` table.

`python -m hq.db.seed` migrates and seeds the configured database.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from hq import settings as paths
from hq.db.conn import connect, dumps, tx
from hq.util.timeutil import now_iso

DEFAULT_SETTINGS: dict[str, Any] = {
    "global_pause": False,
    "freeze_outbound": False,
    "mode": "dry_run",
    "autonomy": "auto",
    "sim_enabled": True,
    "sim_speed": 1.0,
    "keep_awake": True,
    "eligibility_threshold": 0.8,
    "min_pay_ratio": 1.0,
    "funded_program_min_inr": 5000,
    "fit_draft_threshold": 60,
    "fit_polish_threshold": 75,
    "daily_draft_cap": 20,
    "claude_daily_budget_usd": 5.0,
    "claude_daily_call_cap": 40,
    "email_daily_cap": 10,
    "quiet_hours": {"enabled": False, "start": "23:00", "end": "07:00"},
    "unknown_pay_policy": "decision",
    # phase (b): models, Claude, budget
    "model_pool_budget_gb": 30,
    "usability_mode": True,
    "claude_model": "sonnet",
    "claude_signoff_model": "opus",
    "cloud_llm": "auto",
    "xai_model": "grok-4-fast",
    "xai_signoff_model": "grok-4",
    "claude_per_call_cap_usd": 0.5,
    "require_claude_signoff": True,
    "benchmark_on_new_model": True,
    # phase (d): Gmail, inbox, notifications, go-live
    "gmail_poll_minutes": 3,
    "auto_reply_enabled": False,     # effective only in LIVE and ≥ 14 days after going live (CONTRACT_D §2)
    "mac_notifications": True,
    "signoff_policy_ack": False,     # go-live without a cloud sign-off model, acknowledged by Prerit
}


class SettingError(ValueError):
    pass


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    raise SettingError("expected true/false")


def _num(lo: float, hi: float, integer: bool = False) -> Callable[[Any], float]:
    def check(v: Any) -> float:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise SettingError("expected a number")
        if not lo <= v <= hi:
            raise SettingError(f"must be between {lo} and {hi}")
        return int(v) if integer else float(v)
    return check


def _choice(*options: str) -> Callable[[Any], str]:
    def check(v: Any) -> str:
        if v not in options:
            raise SettingError(f"must be one of {', '.join(options)}")
        return v
    return check


def _model_name(v: Any) -> str:
    import re

    if not isinstance(v, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", v):
        raise SettingError("expected a model id like grok-4")
    return v


def _hhmm(v: Any) -> str:
    if not isinstance(v, str) or len(v) != 5 or v[2] != ":":
        raise SettingError("expected HH:MM")
    h, m = v.split(":")
    if not (h.isdigit() and m.isdigit() and 0 <= int(h) < 24 and 0 <= int(m) < 60):
        raise SettingError("expected HH:MM")
    return v


def _quiet_hours(v: Any) -> dict:
    if not isinstance(v, dict) or set(v) - {"enabled", "start", "end"}:
        raise SettingError("expected {enabled, start, end}")
    out = dict(DEFAULT_SETTINGS["quiet_hours"])
    if "enabled" in v:
        out["enabled"] = _bool(v["enabled"])
    for k in ("start", "end"):
        if k in v:
            out[k] = _hhmm(v[k])
    return out


# Keys PATCH /api/settings may change. global_pause / freeze_outbound go through /api/control/*, mode is
# read-only in phase (a), worker_heartbeat_at is written by the worker.
EDITABLE: dict[str, Callable[[Any], Any]] = {
    "autonomy": _choice("auto", "approve_first"),
    "sim_enabled": _bool,
    "sim_speed": _num(0.25, 4.0),
    "keep_awake": _bool,
    "eligibility_threshold": _num(0.0, 1.0),
    "min_pay_ratio": _num(0.0, 5.0),
    "funded_program_min_inr": _num(0, 1_000_000, integer=True),
    "fit_draft_threshold": _num(0, 100, integer=True),
    "fit_polish_threshold": _num(0, 100, integer=True),
    "daily_draft_cap": _num(0, 500, integer=True),
    "claude_daily_budget_usd": _num(0.0, 1000.0),
    "claude_daily_call_cap": _num(0, 10_000, integer=True),
    "email_daily_cap": _num(0, 100, integer=True),
    "quiet_hours": _quiet_hours,
    "unknown_pay_policy": _choice("decision", "accept", "reject"),
    "model_pool_budget_gb": _num(2, 40),
    "usability_mode": _bool,
    "claude_model": _choice("haiku", "sonnet", "opus"),
    "claude_signoff_model": _choice("haiku", "sonnet", "opus"),
    "cloud_llm": _choice("auto", "claude", "xai"),
    "gmail_poll_minutes": _num(1, 60, integer=True),
    "auto_reply_enabled": _bool,
    "mac_notifications": _bool,
    "signoff_policy_ack": _bool,
    "xai_model": _model_name,
    "xai_signoff_model": _model_name,
    "claude_per_call_cap_usd": _num(0.01, 5.0),
    "require_claude_signoff": _bool,
    "benchmark_on_new_model": _bool,
}


def validate_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Return the cleaned patch or raise SettingError naming the first bad key."""
    if not isinstance(patch, dict) or not patch:
        raise SettingError("body must be a non-empty object")
    cleaned = {}
    for key, value in patch.items():
        if key not in EDITABLE:
            raise SettingError(f"'{key}' is not an editable setting")
        try:
            cleaned[key] = EDITABLE[key](value)
        except SettingError as exc:
            raise SettingError(f"{key}: {exc}") from None
    return cleaned


def seed_settings(conn: sqlite3.Connection) -> list[str]:
    """Insert default values for missing keys; never overwrites existing values."""
    added = []
    now = now_iso()
    for key, value in DEFAULT_SETTINGS.items():
        cur = conn.execute(
            "INSERT OR IGNORE INTO settings(key, value_json, updated_at, updated_by) VALUES (?,?,?, 'seed')",
            (key, dumps(value), now),
        )
        if cur.rowcount:
            added.append(key)
    return added


def seed_all(conn: sqlite3.Connection) -> dict[str, int]:
    """Every idempotent seed step (settings, profile facts and fields, answer bank, sources). Caller owns the tx."""
    from hq.pipeline.apply.answers import seed_answer_bank
    from hq.pipeline.discover.sources import seed_sources
    from hq.profile.facts import seed_facts
    from hq.profile.fields import seed_fields

    return {"settings": len(seed_settings(conn)), "facts": seed_facts(conn), "fields": seed_fields(conn),
            "answers": seed_answer_bank(conn), "sources": seed_sources(conn)}


def get_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    for row in conn.execute("SELECT key, value_json FROM settings"):
        try:
            out[row["key"]] = json.loads(row["value_json"])
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    return json.loads(row["value_json"])


def set_settings(conn: sqlite3.Connection, values: dict[str, Any], by: str = "system") -> None:
    """Upsert several keys. Caller decides on the transaction."""
    now = now_iso()
    for key, value in values.items():
        conn.execute(
            "INSERT INTO settings(key, value_json, updated_at, updated_by) VALUES (?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at, "
            "updated_by=excluded.updated_by",
            (key, dumps(value), now, by),
        )


def main() -> None:
    from hq.db.migrate import migrate

    paths.ensure_dirs()
    conn = connect()
    applied = migrate(conn)
    with tx(conn):
        added = seed_all(conn)
    print(f"db={paths.DB_PATH} migrations_applied={applied} seeded={added}")


if __name__ == "__main__":
    main()
