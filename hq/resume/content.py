"""Approved résumé content and the allowed-vocabulary check used on the rendered PDF."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from hq import settings as paths


@lru_cache(maxsize=2)
def _load(path: str, mtime: float) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text()) or {}


def content() -> dict[str, Any]:
    p = paths.CONFIG_DIR / "resume.yaml"
    return _load(str(p), p.stat().st_mtime)


def focus_for(role_type: str | None) -> str:
    return {"ml": "ml", "research": "research", "data": "data", "software": "software"}.get(role_type or "", "default")


def project_order(role_type: str | None, title: str = "") -> list[str]:
    if role_type == "data" and re.search(r"churn|classif|business|analyst", title, re.I):
        return ["churn", "book"]
    return ["book", "churn"]


@dataclass
class ResumeSpec:
    summary: str
    order: list[str]
    summary_fact_ids: list[str]


def approved_strings(summary: str) -> list[str]:
    c = content()
    out = [c["name"], c["contact"]["email"], "linkedin.com/in/prerit-sangwan-1b7572304", "github.com/Preritsangwan17",
           *c["contact"].get("extras", []), summary, "Education", "Projects", "Skills", "Summary",
           c["education"]["school"], c["education"]["degree"], c["education"]["status"]]
    for p in c["projects"].values():
        out += [p["title"], p["date"], p["tech"], p["url"], *[b["text"] for b in p["bullets"]]]
    for s in c["skills"]:
        out += [s["label"] + ":", s["value"]]
    return out


WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*|\d[\d,.]*")


def vocabulary(strings: list[str]) -> set[str]:
    vocab: set[str] = set()
    for s in strings:
        vocab.update(w.lower().strip(".,'’-") for w in WORD.findall(s))
    return vocab


def unapproved_words(pdf_text: str, summary: str) -> list[str]:
    vocab = vocabulary(approved_strings(summary)) | {"·", "in", "progress", "mdash", "https", "www", "com"}
    bad = sorted({w.lower().strip(".,'’-") for w in WORD.findall(pdf_text)} - vocab)
    return [w for w in bad if w and not re.fullmatch(r"[-–—·|]+", w)]
