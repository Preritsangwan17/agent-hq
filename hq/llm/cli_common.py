"""Shared pieces for the subscription CLIs (Claude CLI, ChatGPT's Codex CLI): a clean sandbox directory, and
reading usage-window limits out of whatever the CLI prints.

Neither CLI promises a stable "how much of my plan is left" API in headless mode, so HQ keeps two kinds of numbers
and labels them: `reported` — limit information the CLI itself printed (a usage-percentage snapshot, or a "limit
reached, resets at …" message), and HQ's own count of the calls it made in the rolling 5-hour and 7-day windows.
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Any

from hq import settings as paths
from hq.util.timeutil import now_iso, to_iso, utcnow

LIMIT_MARKERS = ("usage limit", "rate limit", "rate_limit", "429", "too many requests", "limit reached",
                 "hit your limit", "hit your usage", "quota", "try again in", "resets at", "reset at")


def sandbox_dir(name: str) -> Path:
    d = paths.DATA / f"{name}_sandbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def looks_rate_limited(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in LIMIT_MARKERS)


def parse_reset(text: str) -> str | None:
    """"try again in 2 hours" / "resets in 45 minutes" → ISO time; a clock time ("resets 5pm") stays in the raw
    message only (its time zone is ambiguous)."""
    m = re.search(r"(?:try again|resets?|available again)\s+in\s+(?:about\s+)?(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m|"
                  r"days?|d)\b", text or "", re.I)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    delta = timedelta(days=n) if unit.startswith("d") else timedelta(hours=n) if unit.startswith("h") \
        else timedelta(minutes=n)
    return to_iso(utcnow() + delta)


def find_rate_limits(obj: Any, path: str = "") -> list[dict[str, Any]]:
    """Every dict in a CLI's JSON that looks like a usage window ({used_percent, window_minutes, resets_…})."""
    out: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        pct = obj.get("used_percent", obj.get("usedPercent", obj.get("utilization")))
        if isinstance(pct, (int, float)):
            resets = obj.get("resets_in_seconds", obj.get("resetsInSeconds"))
            resets_at = obj.get("resets_at") or obj.get("resetsAt")
            if isinstance(resets, (int, float)) and not resets_at:
                resets_at = to_iso(utcnow() + timedelta(seconds=float(resets)))
            minutes = obj.get("window_minutes", obj.get("windowMinutes"))
            name = path.rsplit(".", 1)[-1] or "window"
            if isinstance(minutes, (int, float)):
                name = "5-hour window" if 250 <= minutes <= 350 else "weekly window" if minutes >= 7 * 1440 - 60 \
                    else f"{int(minutes)}-minute window"
            used = float(pct) * (100.0 if float(pct) <= 1.0 and "utilization" in obj else 1.0)
            out.append({"name": name, "used_percent": round(used, 1), "left_percent": round(max(0.0, 100 - used), 1),
                        "window_minutes": minutes, "resets_at": resets_at})
        for k, v in obj.items():
            out.extend(find_rate_limits(v, f"{path}.{k}" if path else str(k)))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(find_rate_limits(v, path))
    return out


class LimitTracker:
    """What a CLI has told HQ about its usage windows."""

    def __init__(self, source: str):
        self.source = source
        self.windows: list[dict[str, Any]] = []
        self.windows_at: str | None = None
        self.limited_until: str | None = None
        self.limit_message: str | None = None
        self.limit_at: str | None = None

    def saw_json(self, obj: Any) -> None:
        found = find_rate_limits(obj)
        if found:
            self.windows, self.windows_at = found, now_iso()

    def saw_limit(self, text: str) -> None:
        self.limit_message = (text or "").strip()[:300]
        self.limit_at = now_iso()
        self.limited_until = parse_reset(text) or to_iso(utcnow() + timedelta(hours=1))

    def blocked(self) -> bool:
        return bool(self.limited_until and self.limited_until > now_iso())

    def state(self) -> dict[str, Any]:
        return {"source": self.source, "windows": self.windows, "windows_at": self.windows_at,
                "limited_until": self.limited_until if self.blocked() else None,
                "limit_message": self.limit_message, "limit_at": self.limit_at}
