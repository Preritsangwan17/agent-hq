"""Fixture loading shared by the tasks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hq import settings as paths


def fixtures_dir() -> Path:
    return paths.ROOT / "tests" / "fixtures"


def jsonl(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (fixtures_dir() / name).read_text().splitlines() if line.strip()]


def job_text(rel: str) -> str:
    return (fixtures_dir() / rel).read_text()


def job_header(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines()[:5]:
        if ":" in line and line.split(":", 1)[0] in ("TITLE", "COMPANY", "LOCATION"):
            k, v = line.split(":", 1)
            out[k.lower()] = v.strip()
    return out
