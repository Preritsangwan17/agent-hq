"""Prompt (prompts/*.md) and JSON schema (schemas/*.json) files shared by agents and the benchmark.

`load_prompt("writer")` reads prompts/writer.md; a path with a slash ("prompts/custom.md") is relative to the repo.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from hq import settings as paths


def _resolve(name: str, folder: str, suffix: str) -> Path:
    p = Path(name)
    if p.is_absolute():
        return p
    if "/" in name:
        return paths.ROOT / name
    return paths.ROOT / folder / (name if name.endswith(suffix) else f"{name}{suffix}")


@lru_cache(maxsize=64)
def _read(path: str, mtime: float) -> str:
    return Path(path).read_text()


def load_prompt(name: str) -> str:
    p = _resolve(name, "prompts", ".md")
    return _read(str(p), p.stat().st_mtime)


def load_schema(name: str) -> dict[str, Any]:
    p = _resolve(name, "schemas", ".json")
    return json.loads(_read(str(p), p.stat().st_mtime))
