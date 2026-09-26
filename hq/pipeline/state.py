"""Pipeline state machine (CONTRACT §7/§8). Pure: no I/O, no clock, no settings lookups.

`next_tasks(stage, capability, result)` maps the opportunity's current stage and a finished capability's result
summary to the new stage and the follow-on tasks. The worker applies it in the same transaction as task success.

Stage flow: found → (verify) verified | filtered → (draft) drafted → (fact-check + sign-off) checked →
(résumé, apply) applied → (inbox) replied → interview | rejected | offer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STAGE_ORDER = ["found", "verified", "drafted", "checked", "applied", "replied", "interview", "offer"]
TERMINAL = {"filtered", "rejected", "offer", "frozen", "skipped"}
PRE_APPLY = {"found", "verified", "drafted", "checked"}
MAX_DRAFT_VERSIONS = 3

# Later stages drain first so work in flight finishes before new discovery piles up.
PRIORITY = {
    "discover": 30, "parse.job": 40, "verify": 50, "score.fit": 52, "draft": 60, "factcheck": 65,
    "check.quality": 66, "build.resume": 70, "apply": 80, "followup": 75, "inbox": 85, "strategy": 20,
}


def priority_for(capability: str) -> int:
    if capability in PRIORITY:
        return PRIORITY[capability]
    return PRIORITY.get(capability.split(".", 1)[0], 50)


@dataclass(frozen=True)
class TaskSpec:
    capability: str
    payload: dict[str, Any] = field(default_factory=dict)
    delay_s: float = 0.0
    priority: int | None = None

    @property
    def effective_priority(self) -> int:
        return self.priority if self.priority is not None else priority_for(self.capability)


def _redraft(stage: str, result: dict[str, Any]) -> tuple[str, list[TaskSpec]]:
    """Failed check → targeted rewrite (all layers re-run). After 3 loops: one Claude polish when the real pipeline
    allows it (`polish_allowed`), then a review item in Needs Prerit (raised by the checking agent)."""
    version = int(result.get("version") or 1)
    loop = int(result.get("loop") or version)
    if loop >= MAX_DRAFT_VERSIONS:
        if result.get("polish_allowed") and not result.get("polished"):
            return "drafted", [TaskSpec("polish.final", {"version": version, "loop": loop, "reason": "fix",
                                                          "feedback": result.get("feedback")})]
        return stage, []  # no more automatic loops
    return "drafted", [TaskSpec("draft.cover_letter", {"version": version + 1, "loop": loop + 1,
                                                       "feedback": result.get("feedback")})]


def _carry(result: dict[str, Any]) -> dict[str, Any]:
    return {k: result[k] for k in ("version", "loop", "polished") if k in result}


def next_tasks(stage: str, capability: str, result: dict[str, Any]) -> tuple[str, list[TaskSpec]]:
    ok = bool(result.get("ok", True))
    if stage in TERMINAL:
        return stage, []

    if capability.startswith("discover."):
        return ("found", [TaskSpec("parse.job")]) if result.get("created") else (stage, [])

    if capability == "parse.job":
        if stage == "found" and not ok:
            return "filtered", []
        return stage, [TaskSpec("verify.link")] if stage == "found" else []

    verify_chain = {"verify.link": "verify.eligibility", "verify.eligibility": "verify.scam",
                    "verify.scam": "verify.pay", "verify.pay": "score.fit"}
    if result.get("deadline_step"):
        verify_chain["verify.link"] = "verify.deadline"
    if capability in verify_chain or capability == "verify.deadline":
        if stage != "found":
            return stage, []
        if not ok:
            return "filtered", []
        nxt = verify_chain.get(capability, "verify.eligibility")
        return stage, [TaskSpec(nxt)]

    if capability == "score.fit":
        if stage not in ("found", "verified"):
            return stage, []
        if not ok:
            return "filtered", []
        return "verified", [TaskSpec("draft.cover_letter", {"version": 1, "loop": 1},
                                     delay_s=float(result.get("draft_delay_s") or 0))] if result.get("advance") else []

    if capability == "draft.cover_letter":
        if stage not in ("verified", "drafted"):
            return stage, []
        if not ok:
            return stage, []
        return "drafted", [TaskSpec("factcheck.deterministic", {"version": result.get("version", 1), **_carry(result)})]

    if capability == "polish.final":
        if stage != "drafted" or not ok:
            return stage, []
        return stage, [TaskSpec("factcheck.deterministic", {**_carry(result), "polished": True})]

    check_chain = {"factcheck.deterministic": "factcheck.sentence", "factcheck.sentence": "check.quality",
                   "check.quality": "factcheck.signoff"}
    if capability in check_chain:
        if stage != "drafted":
            return stage, []
        if not ok:
            return _redraft(stage, result)
        if capability == "check.quality" and result.get("polish"):
            return stage, [TaskSpec("polish.final", {**_carry(result), "reason": "high fit"})]
        return stage, [TaskSpec(check_chain[capability], {"version": result.get("version", 1), **_carry(result)})]

    if capability == "factcheck.signoff":
        if stage != "drafted":
            return stage, []
        if not ok:
            return _redraft(stage, result)
        return "checked", [TaskSpec("build.resume")]

    if capability == "build.resume":
        if stage != "checked" or not ok or result.get("approval_required"):
            return stage, []
        if result.get("apply_channel") == "email":
            return stage, [TaskSpec("apply.email_send")]
        if result.get("apply_channel") == "mock_ats":
            return stage, [TaskSpec("apply.ats_submit")]
        return stage, [TaskSpec("apply.manual_pack")]

    if capability in ("apply.email_send", "apply.ats_submit"):
        if stage != "checked":
            return stage, []
        if not ok:
            return stage, [TaskSpec("apply.manual_pack")] if result.get("fallback_pack") else []
        return "applied", [TaskSpec("followup.schedule")]

    if capability == "apply.manual_pack":
        return stage, []  # stays `checked` until Prerit marks the pack submitted

    if capability == "inbox.poll":
        if stage == "applied" and result.get("reply"):
            return "replied", [TaskSpec("inbox.classify", {"message_id": result.get("message_id")})]
        return stage, []

    if capability == "inbox.classify":
        if stage not in ("applied", "replied"):
            return stage, []
        outcome = result.get("classification")
        return {"interview": "interview", "rejection": "rejected", "offer": "offer"}.get(outcome, "replied"), []

    return stage, []
