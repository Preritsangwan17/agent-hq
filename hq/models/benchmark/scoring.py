"""Metric helpers for the benchmark tasks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz


@dataclass
class Metrics:
    n: int
    accuracy: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 4), round(r, 4), round(f, 4)


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("–", "-").replace("—", "-")).strip().lower()


def grounded(quote: str | None, text: str) -> bool:
    q = norm(quote)
    return bool(q) and q in norm(text)


def similar(a: str | None, b: str | None, threshold: int = 85) -> bool:
    if not a or not b:
        return not a and not b
    return fuzz.token_set_ratio(norm(a), norm(b)) >= threshold
