"""Local first, Grok only when it earns its cost. Every "may this task use Grok?" question is answered here.

Switches (Settings › AI & budget):
  local_ai_enabled  — the local models on this Mac (free, private). Off = nothing runs locally.
  grok_enabled      — Grok through xAI's API (paid). Off = nothing is sent to xAI.
  Both on = local first, Grok as the policy allows; Local only; Grok only (everything goes to Grok); None = the
  AI steps wait while rules-only work (discovery, pay, scam and link checks) carries on.

`cloud_mode` decides how much Grok is used when both are on:
  saver    (API-saving, default) — Grok only when no local model can do the task, or for the final sign-off of an
           application when no second independent local checker exists. Never for optional polish.
  balanced — also Grok for the eligibility third opinion, a polish of important letters, and the strong Grok model
           signs off important applications.
  quality  — Grok signs off every application with the strong model and polishes every high-fit letter.
"Important" = the opportunity's match score ≥ `important_score_threshold` (default 75).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hq.llm import cloud

MODES = ("saver", "balanced", "quality")
ENGINES = ("both", "local", "grok", "none")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    model: str | None = None    # "xai:<model>" when allowed
    reason: str = ""


def mode(s: dict[str, Any]) -> str:
    m = s.get("cloud_mode", "saver")
    return m if m in MODES else "saver"


def local_on(s: dict[str, Any]) -> bool:
    return bool(s.get("local_ai_enabled", True))


def grok_on(s: dict[str, Any]) -> bool:
    return bool(s.get("grok_enabled", True))


def engines(s: dict[str, Any]) -> str:
    lo, gr = local_on(s), grok_on(s)
    return "both" if lo and gr else "local" if lo else "grok" if gr else "none"


def engines_patch(value: str) -> dict[str, bool]:
    if value not in ENGINES:
        raise ValueError(f"engines must be one of {', '.join(ENGINES)}")
    return {"local_ai_enabled": value in ("both", "local"), "grok_enabled": value in ("both", "grok")}


def important(opp: dict[str, Any] | None, s: dict[str, Any]) -> bool:
    if not opp:
        return False
    return float(opp.get("fit_score") or 0) >= float(s.get("important_score_threshold", 75))


def _no(reason: str) -> Decision:
    return Decision(False, None, reason)


def escalate(s: dict[str, Any], kind: str, *, opp: dict[str, Any] | None = None,
             local_tried: bool = True) -> Decision:
    """After the local ladder: may Grok take over? `kind`:
      "needed"      — the task can't finish without a model (no local model managed it): writer, email classifier
      "second_look" — the local models answered but weren't confident (eligibility third opinion)
      "bulk"        — high-volume, low-stakes work (title filter, job parsing): only when local AI is off
    """
    if not grok_on(s):
        return _no("Grok is switched off")
    if not local_on(s):
        return Decision(True, cloud.fast_model(s), "local AI is switched off")
    m = mode(s)
    if kind == "bulk":
        return _no("bulk work stays local")
    if kind == "second_look":
        if m == "saver" and local_tried:
            return _no("API-saving mode: an unclear case becomes a one-click decision instead")
        return Decision(True, cloud.fast_model(s), f"{m} mode: Grok gives the third opinion")
    return Decision(True, cloud.fast_model(s), "no local model could do this task")


def polish(s: dict[str, Any], opp: dict[str, Any] | None, reason: str) -> Decision:
    """`reason`: "high fit" (optional quality lift) or "fix" (the local writer failed the gates 3 times)."""
    if not grok_on(s):
        return _no("Grok is switched off")
    m = mode(s)
    if reason == "high fit":
        if m == "saver":
            return _no("API-saving mode: no optional polish")
        if m == "balanced" and not important(opp, s):
            return _no("balanced mode: polish only important applications")
        return Decision(True, cloud.fast_model(s), f"{m} mode: polish a high-fit letter")
    if m == "saver" and local_on(s) and not important(opp, s):
        return _no("API-saving mode: a letter that isn't a top match goes to you for review instead")
    return Decision(True, cloud.fast_model(s), "the local writer couldn't pass the gates")


def signoff(s: dict[str, Any], opp: dict[str, Any] | None, *, local_checker_available: bool) -> Decision:
    """Final independent check before anything is sent. Decision.model None + allowed → a local model signs off."""
    m = mode(s)
    local_ok = local_on(s) and local_checker_available
    if not grok_on(s):
        return Decision(local_ok, None, "a second independent local model signs off" if local_ok
                        else "Grok is switched off and no second independent local checker is available")
    if m == "quality":
        return Decision(True, cloud.strong_model(s), "quality mode: the strong Grok model signs off")
    if m == "balanced" and important(opp, s):
        return Decision(True, cloud.strong_model(s), "important application: the strong Grok model signs off")
    if local_ok:
        return Decision(True, None, "a second independent local model signs off (free)")
    return Decision(True, cloud.fast_model(s), "no second independent local checker: Grok signs off")


def describe(s: dict[str, Any]) -> dict[str, Any]:
    """For the UI: what the current switches and mode mean in plain words."""
    return {"engines": engines(s), "local_ai_enabled": local_on(s), "grok_enabled": grok_on(s), "mode": mode(s),
            "fast_model": cloud.fast_model(s), "strong_model": cloud.strong_model(s),
            "important_score_threshold": float(s.get("important_score_threshold", 75))}
