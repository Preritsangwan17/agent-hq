"""Availability gate (PLAN §3): the role's dates and hours must fit Prerit's confirmed availability windows and
term-time hours cap. Unknown (no confirmed windows, or no dates in the posting) → needs_info."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass
class Availability:
    status: str          # fits | conflict | needs_info
    reason: str


def check_availability(*, windows_json: str | None, hours_cap: str | None, start: date | None,
                       duration_months: float | None, hours_per_week: float | None,
                       work_mode: str | None) -> Availability:
    if not windows_json:
        return Availability("needs_info", "availability windows not confirmed in Settings › Profile")
    try:
        windows = json.loads(windows_json)
    except ValueError:
        return Availability("needs_info", "availability windows unreadable")
    if not windows:
        return Availability("needs_info", "no availability windows saved")
    cap = float(hours_cap) if hours_cap else None
    if start is None:
        if hours_per_week and cap and hours_per_week > cap and work_mode != "onsite":
            return Availability("needs_info", f"{hours_per_week:g} h/week is above the term cap of {cap:g} h; dates unknown")
        return Availability("needs_info", "the posting gives no start date")
    end = start + timedelta(days=int(30.4 * (duration_months or 3)))
    for w in windows:
        wf, wt = date.fromisoformat(w["from"]), date.fromisoformat(w["to"])
        mode_ok = w.get("mode", "any") in ("any", work_mode or "any") or work_mode in (None, "unknown", "hybrid")
        if wf <= start and end <= wt and mode_ok:
            if hours_per_week and hours_per_week > float(w.get("hours_per_week") or 40):
                continue
            return Availability("fits", f"fits {w['from']}–{w['to']} ({w.get('hours_per_week')} h/week)")
    if hours_per_week and cap and hours_per_week <= cap and work_mode == "remote":
        return Availability("fits", f"part-time {hours_per_week:g} h/week is within the term cap of {cap:g} h")
    return Availability("conflict", f"{start.isoformat()} for ~{duration_months or 3:g} months doesn't fit any saved window")


def as_dict(a: Availability) -> dict[str, Any]:
    return {"status": a.status, "reason": a.reason}
