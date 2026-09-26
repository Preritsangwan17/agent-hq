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
    version = int(result.get("version") or 1)
    if version >= MAX_DRAFT_VERSIONS:
        return stage, []  # the worker raises a review item; no more automatic loops
    return "drafted", [TaskSpec("draft.cover_letter", {"version": version + 1, "feedback": result.get("feedback")})]


def next_tasks(stage: str, capability: str, result: dict[str, Any]) -> tuple[str, list[TaskSpec]]:
    ok = bool(result.get("ok", True))
    if stage in TERMINAL:
        return stage, []

    if capability.startswith("discover."):
        return ("found", [TaskSpec("parse.job")]) if result.get("created") else (stage, [])

    if capability == "parse.job":
        return stage, [TaskSpec("verify.link")] if stage == "found" else []

    verify_chain = {"verify.link": "verify.eligibility", "verify.eligibility": "verify.scam",
                    "verify.scam": "verify.pay", "verify.pay": "score.fit"}
    if capability in verify_chain or capability == "verify.deadline":
        if stage != "found":
            return stage, []
        if not ok:
            return "filtered", []
        nxt = verify_chain.get(capability, "verify.eligibility")
        return stage, [TaskSpec(nxt)]

    if capability == "score.fit":
        if stage != "found":
            return stage, []
        if not ok:
            return "filtered", []
        return "verified", [TaskSpec("draft.cover_letter", {"version": 1})] if result.get("advance") else []

    if capability == "draft.cover_letter":
        if stage not in ("verified", "drafted"):
            return stage, []
        return "drafted", [TaskSpec("factcheck.deterministic", {"version": result.get("version", 1)})]

    check_chain = {"factcheck.deterministic": "factcheck.sentence", "factcheck.sentence": "check.quality",
                   "check.quality": "factcheck.signoff"}
    if capability in check_chain:
        if stage != "drafted":
            return stage, []
        if not ok:
            return _redraft(stage, result)
        return stage, [TaskSpec(check_chain[capability], {"version": result.get("version", 1)})]

    if capability == "factcheck.signoff":
        if stage != "drafted":
            return stage, []
        if not ok:
            return _redraft(stage, result)
        return "checked", [TaskSpec("build.resume")]

    if capability == "build.resume":
        if stage != "checked" or result.get("approval_required"):
            return stage, []
        if result.get("apply_channel") == "email":
            return stage, [TaskSpec("apply.email_send")]
        return stage, [TaskSpec("apply.manual_pack")]

    if capability == "apply.email_send":
        if stage != "checked" or not ok:
            return stage, []
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
