"""Programme and lab pages (CONTRACT_C §3): the TEEP table (one row per lab programme; AI/ML/data topics kept)
and a generic watcher for single programme pages (SRFP, Summer@EPFL, UTRIP, MLH) that re-parses only when the
page text changes."""
from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from hq.pipeline.discover.postings import RawPosting
from hq.pipeline.discover.text import html_to_text

TOPIC = re.compile(r"\b(machine learning|deep learning|artificial intelligence|\bai\b|a\.i\.|data|recommend\w*|"
                   r"computer vision|image processing|nlp|natural language|neural|intelligent|information retrieval|"
                   r"big data|software|computing|algorithm|robot\w*|learning|llm|language model)\b", re.I)
PERIOD = re.compile(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})\s*[-~–]\s*(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})")


def teep_deadline(period: str) -> str | None:
    m = PERIOD.search(period or "")
    if not m:
        return None
    y, mo, d = int(m.group(4)), int(m.group(5)), int(m.group(6))
    return f"{y:04d}-{mo:02d}-{d:02d}T15:59:00Z"   # 23:59 Taipei


def parse_teep(html: str, source_id: str, base_url: str, meta: dict[str, Any]) -> list[RawPosting]:
    tree = HTMLParser(html)
    out = []
    for tr in tree.css("tr"):
        cells = tr.css("td")
        if len(cells) < 5:
            continue
        program = cells[1].text(strip=True)
        school, location, period = cells[2].text(strip=True), cells[3].text(strip=True), cells[4].text(strip=True)
        if not TOPIC.search(program):
            continue
        link = tr.css_first("a[href*='/program/']")
        href = urljoin(base_url, link.attributes.get("href", "")) if link else base_url
        pid = re.search(r"/program/(\d+)", href)
        out.append(RawPosting(
            source_id, "program_page", pid.group(1) if pid else hashlib.sha1(program.encode()).hexdigest()[:12],
            school, f"TEEP research internship: {program[:150]}", href,
            text=f"TEEP (Taiwan Experience Education Program) lab programme at {school}, {location}, Taiwan.\n"
                 f"Topic: {program}\nPeriod of application: {period}",
            location_raw=f"{location}, Taiwan", pay_raw=meta.get("pay_raw"), employment_type="research internship",
            extra={"deadline_at": teep_deadline(period), "kind": meta.get("kind", "research_internship"),
                   "period": period}))
    return out


def parse_generic(html: str, source_id: str, url: str, meta: dict[str, Any], program_id: str) -> list[RawPosting]:
    text = html_to_text(html)[:40000]
    if len(text) < 200:
        return []
    city = meta.get("city")
    loc = ", ".join(x for x in (city, meta.get("country_iso2")) if x) or None
    return [RawPosting(source_id, "program_page", program_id, meta.get("company") or program_id,
                       meta.get("title") or program_id, url, text=text, location_raw=loc,
                       pay_raw=meta.get("pay_raw"), employment_type=meta.get("kind"),
                       remote=meta.get("work_mode") == "remote",
                       extra={"kind": meta.get("kind"), "page_sha": hashlib.sha256(text.encode()).hexdigest()})]


def parse_program_page(html: str, source: dict[str, Any]) -> list[RawPosting]:
    cfg = source["config"]
    meta = cfg.get("program") or {}
    if cfg.get("parser") == "teep":
        return parse_teep(html, source["id"], cfg["url"], meta)
    return parse_generic(html, source["id"], cfg["url"], meta, source["id"].split(":", 1)[-1])
