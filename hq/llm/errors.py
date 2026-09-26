"""Error and result types shared by the cloud model runner (Grok via xAI's API) and everything that calls it.

A cloud answer is accepted only when it validates against the task's JSON schema. The error kinds decide what the
caller does next: `CloudUnavailable` → wait and raise one Needs item, `CloudRateLimited` → retry in an hour,
`CloudBudgetExceeded` → over the per-call cap, `CloudBadOutput` → the answer didn't validate (its cost still counts).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


class CloudError(Exception):
    kind = "error"
    cost_usd: float | None = None


class CloudUnavailable(CloudError):
    kind = "auth"


class CloudBudgetExceeded(CloudError):
    kind = "budget"


class CloudRateLimited(CloudError):
    kind = "rate_limit"


class CloudBadOutput(CloudError):
    kind = "structured_output"


@dataclass
class CloudResult:
    output: Any
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    duration_ms: float
    model: str
    subtype: str
    # "reported": xAI returned the exact cost of the call; "estimated": HQ computed it from config/cloud_prices.yaml
    cost_source: str = "estimated"
    raw: dict[str, Any] = field(default_factory=dict)


def minimal_env() -> dict[str, str]:
    """Environment for helper subprocesses: nothing secret, just enough to run."""
    return {k: os.environ[k] for k in ("PATH", "HOME", "USER", "LANG") if k in os.environ}
