"""Agent YAML schema (CONTRACT §6): pydantic AgentConfig, capability vocabulary and side-effect rules."""
from __future__ import annotations

import re
from typing import Any, Literal

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ADAPTERS = ["sim", "script", "openai_compatible", "cloud", "http", "browser"]

# Outbound side effects. Only the built-in owners below may declare them; the loader enforces it and the
# dispatcher double-checks, so a hand-edited DB row cannot route them elsewhere either.
RESERVED_SIDE_EFFECTS = ["apply.email_send", "apply.ats_submit", "reply.send", "followup.send"]
SIDE_EFFECT_OWNERS = {"applicant", "inbox", "followup"}

# Capabilities that are parked system-wide when an agent owning a reserved capability is paused or disabled.
SIDE_EFFECT_FAMILY_PREFIXES = ("apply.",)
SIDE_EFFECT_FAMILY_EXACT = {"reply.send", "followup.send"}

# (id, label, group, description). Starred ones in the contract are used by the phase-(a) sim.
CAPABILITIES: list[tuple[str, str, str, str]] = [
    ("discover.ats", "Discover: ATS boards", "discover", "Poll Greenhouse/Lever/Ashby public job boards."),
    ("discover.feed", "Discover: remote feeds", "discover", "Read remote job feeds with attribution."),
    ("discover.program_page", "Discover: program pages", "discover", "Watch lab and research-program pages."),
    ("discover.email_alerts", "Discover: alert emails", "discover", "Parse Prerit's own job-alert emails."),
    ("parse.job", "Parse job", "parse", "Extract requirements, deadline, pay and apply channel."),
    ("classify.title", "Classify title", "parse", "Keep intern/part-time/contract/junior titles."),
    ("verify.link", "Verify link", "verify", "Check the posting is still live."),
    ("verify.deadline", "Verify deadline", "verify", "Conservative deadline check."),
    ("verify.eligibility", "Verify eligibility", "verify", "Rule engine + quoted LLM extraction."),
    ("verify.eligibility_hard", "Hard eligibility", "verify", "Escalated eligibility review."),
    ("verify.pay", "Verify pay", "verify", "Normalise pay to ₹/month and compare to living cost."),
    ("verify.scam", "Scam check", "verify", "Fees, mills, free-mail recruiters, lookalike domains."),
    ("score.fit", "Match score", "verify", "Transparent 0–100 match score against the career plan."),
    ("draft.cover_letter", "Draft cover letter", "draft", "Fact-cited cover letter."),
    ("draft.cold_email", "Draft cold email", "draft", "Short fact-cited email."),
    ("draft.research_statement", "Draft research statement", "draft", "Research-program statement."),
    ("draft.form_answers", "Draft form answers", "draft", "Answers mapped to facts or confirmed fields."),
    ("draft.followup", "Draft follow-up", "draft", "One polite follow-up."),
    ("polish.final", "Final polish", "draft", "Cloud polish, only when the local-first policy allows it."),
    ("factcheck.deterministic", "Fact rules", "check", "Deterministic fact-gate rules."),
    ("factcheck.sentence", "Sentence fact-check", "check", "Independent per-sentence verifier."),
    ("factcheck.signoff", "Sign-off", "check", "Independent final sign-off: a second local model, or a cloud model."),
    ("check.quality", "Quality gate", "check", "Specificity, clichés, length, salutation."),
    ("build.resume", "Build résumé", "build", "Approved bullets only, one page."),
    ("apply.email_send", "Send application email", "apply", "Outbound email (reserved side effect)."),
    ("apply.ats_submit", "Submit ATS form", "apply", "Browser submit (reserved; mock ATS only in v1)."),
    ("apply.manual_pack", "Pre-filled pack", "apply", "Build a Needs-Prerit pack for manual submission."),
    ("inbox.poll", "Poll inbox", "inbox", "Poll for replies."),
    ("inbox.classify", "Classify reply", "inbox", "Interview/rejection/offer/... with notify-only locks."),
    ("reply.draft", "Draft reply", "inbox", "Draft an info-request reply."),
    ("reply.send", "Send reply", "inbox", "Outbound reply (reserved side effect)."),
    ("followup.schedule", "Schedule follow-up", "followup", "Schedule one follow-up 10 days out."),
    ("followup.send", "Send follow-up", "followup", "Outbound follow-up (reserved side effect)."),
    ("strategy.daily_review", "Daily review", "strategy", "Daily pipeline review and proposals."),
    ("debug.failed_run", "Debug failed run", "strategy", "Diagnose repeated failures."),
    ("summarize", "Summarize", "other", "Generic summarisation."),
]
CAPABILITY_IDS = [c[0] for c in CAPABILITIES]

# Capabilities the scheduler may create tasks for on interval/cron agents (others need an opportunity).
SCHEDULABLE = ["discover.ats", "discover.program_page", "discover.feed", "discover.email_alerts",
               "inbox.poll", "followup.send", "strategy.daily_review"]

# Display order of the starting team (CONTRACT §6); user-created agents follow in creation order.
TEAM_ORDER = ["scout", "verifier", "writer", "factchecker", "reviewer", "resume", "applicant", "inbox", "followup",
              "strategist"]

PALETTE = ["#22D3EE", "#2DD4BF", "#A78BFA", "#F59E0B", "#FB7185", "#60A5FA", "#F472B6", "#A3E635",
           "#FB923C", "#E879F9", "#34D399", "#818CF8", "#FACC15", "#38BDF8", "#F87171", "#C084FC"]

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
MODEL_RE = re.compile(r"^(auto|(mlx|ollama|lmstudio|llamacpp|xai|claude|codex|sim|openai):.+)$")


def is_side_effect_family(capability: str) -> bool:
    return capability.startswith(SIDE_EFFECT_FAMILY_PREFIXES) or capability in SIDE_EFFECT_FAMILY_EXACT


def capability_meta() -> list[dict[str, Any]]:
    return [
        {"id": cid, "label": label, "group": group, "description": desc,
         "reserved": cid in RESERVED_SIDE_EFFECTS, "side_effect": is_side_effect_family(cid),
         "schedulable": cid in SCHEDULABLE}
        for cid, label, group, desc in CAPABILITIES
    ]


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["on_demand", "interval", "cron"] = "on_demand"
    minutes: float | None = Field(default=None, gt=0, le=7 * 24 * 60)
    cron: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "Schedule":
        if self.mode == "interval" and not self.minutes:
            raise ValueError("interval schedule needs minutes > 0")
        if self.mode == "cron" and not (self.cron and croniter.is_valid(self.cron)):
            raise ValueError("cron schedule needs a valid 5-field cron expression")
        return self

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"mode": self.mode}
        if self.minutes is not None:
            out["minutes"] = self.minutes
        if self.cron is not None:
            out["cron"] = self.cron
        return out


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=40)
    avatar: str = Field(default="🤖", min_length=1, max_length=40)
    color: str = Field(default="#94A3B8", pattern=r"^#[0-9A-Fa-f]{6}$")
    role: str = Field(default="custom", min_length=1, max_length=40)
    description: str = Field(default="", max_length=500)
    adapter: Literal["sim", "script", "openai_compatible", "cloud", "http", "browser"]
    adapter_config: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    capabilities: list[str] = Field(min_length=1)
    cost_tier: Literal["local", "cloud", "external"] = "local"
    concurrency: int = Field(default=1, ge=1, le=8)
    schedule: Schedule = Field(default_factory=Schedule)
    enabled: bool = True
    builtin: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("id must match ^[a-z][a-z0-9_-]{1,31}$")
        return v

    @field_validator("model")
    @classmethod
    def _model(cls, v: str | None) -> str | None:
        if v is not None and not MODEL_RE.match(v):
            raise ValueError("model must be null, 'auto' or '<runtime>:<name>' (e.g. mlx:<repo>)")
        return v

    @field_validator("capabilities")
    @classmethod
    def _caps(cls, v: list[str]) -> list[str]:
        unknown = [c for c in v if c not in CAPABILITY_IDS]
        if unknown:
            raise ValueError(f"unknown capabilities: {', '.join(unknown)}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate capabilities")
        return v

    @model_validator(mode="after")
    def _side_effects(self) -> "AgentConfig":
        reserved = [c for c in self.capabilities if c in RESERVED_SIDE_EFFECTS]
        if reserved and not (self.builtin and self.id in SIDE_EFFECT_OWNERS):
            raise ValueError(
                f"reserved side-effect capabilities ({', '.join(reserved)}) are only allowed on the built-in "
                f"agents {', '.join(sorted(SIDE_EFFECT_OWNERS))}"
            )
        if self.schedule.mode != "on_demand" and not any(c in SCHEDULABLE for c in self.capabilities):
            raise ValueError("a scheduled agent needs at least one schedulable capability "
                             f"({', '.join(SCHEDULABLE)})")
        return self

    @property
    def side_effects(self) -> list[str]:
        return [c for c in self.capabilities if c in RESERVED_SIDE_EFFECTS]

    @property
    def schedulable_capabilities(self) -> list[str]:
        return [c for c in self.capabilities if c in SCHEDULABLE]

    def to_yaml_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        data["schedule"] = self.schedule.as_json()
        return data
