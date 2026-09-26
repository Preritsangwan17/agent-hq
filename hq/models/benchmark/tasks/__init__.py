"""Benchmark tasks. Each module exposes `TASK: BenchTask` built from real project data in tests/fixtures."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from hq.models.benchmark.scoring import Metrics


@dataclass
class Case:
    id: str
    messages: list[dict[str, str]]
    gold: Any
    meta: dict[str, Any]


@dataclass
class BenchTask:
    name: str
    schema_name: str
    max_tokens: int
    cases: Callable[[bool], list[Case]]
    score: Callable[[list[Case], list[Any]], Metrics]


def all_tasks() -> dict[str, BenchTask]:
    from hq.models.benchmark.tasks import classify_email, eligibility, factcheck, parse_job, title_filter, write_paragraph

    return {t.TASK.name: t.TASK for t in (parse_job, eligibility, title_filter, write_paragraph, factcheck,
                                           classify_email)}
