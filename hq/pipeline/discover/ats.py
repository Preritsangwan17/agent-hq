"""Greenhouse, Lever and Ashby public job-board APIs → RawPosting (read-only GETs through the polite fetcher)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hq.pipeline.discover.fetch import Fetcher
from hq.pipeline.discover.postings import RawPosting
from hq.pipeline.discover.text import html_to_text

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
}


def _iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)[:19] + "Z" if len(str(value)) >= 19 else str(value)


def _company(slug: str) -> str:
    return slug.replace("-production", "").replace("-", " ").title()


def parse_greenhouse(data: dict[str, Any], source_id: str, slug: str) -> list[RawPosting]:
    out = []
    for j in data.get("jobs") or []:
        loc = (j.get("location") or {}).get("name")
        pay = None
        for m in j.get("metadata") or []:
            if isinstance(m, dict) and "salary" in str(m.get("name", "")).lower() and m.get("value"):
                pay = str(m["value"])
        out.append(RawPosting(source_id, "greenhouse", str(j.get("id")), j.get("company_name") or _company(slug),
                              j.get("title", ""), j.get("absolute_url", ""), html_to_text(j.get("content")), loc,
                              j.get("absolute_url"), _iso(j.get("first_published") or j.get("updated_at")), pay,
                              department=((j.get("departments") or [{}])[0] or {}).get("name")))
    return out


def parse_lever(data: list[dict[str, Any]], source_id: str, slug: str) -> list[RawPosting]:
    out = []
    for j in data or []:
        cats = j.get("categories") or {}
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description"))]
        for lst in j.get("lists") or []:
            parts.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content'))}")
        parts.append(j.get("additionalPlain") or html_to_text(j.get("additional")))
        sr = j.get("salaryRange") or {}
        pay = None
        if sr.get("min") or sr.get("max"):
            per = {"per-year-salary": "year", "per-month-salary": "month", "per-hour-wage": "hour"}.get(
                sr.get("interval", ""), sr.get("interval", ""))
            pay = f"{sr.get('currency', '')} {sr.get('min', '')} - {sr.get('max', '')}/{per}".strip()
        out.append(RawPosting(source_id, "lever", str(j.get("id")), _company(slug), j.get("text", ""),
                              j.get("hostedUrl", ""), "\n\n".join(p for p in parts if p), cats.get("location"),
                              j.get("applyUrl"), _iso(j.get("createdAt")), pay, cats.get("commitment"),
                              remote=(j.get("workplaceType") == "remote") or None, department=cats.get("team")))
    return out


def parse_ashby(data: dict[str, Any], source_id: str, slug: str) -> list[RawPosting]:
    out = []
    for j in data.get("jobs") or []:
        if j.get("isListed") is False:
            continue
        comp = j.get("compensation") or {}
        pay = comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary")
        out.append(RawPosting(source_id, "ashby", str(j.get("id")), _company(slug), j.get("title", ""),
                              j.get("jobUrl", ""), j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                              j.get("location"), j.get("applyUrl"), _iso(j.get("publishedAt")), pay,
                              j.get("employmentType"), remote=j.get("isRemote"), department=j.get("department")))
    return out


PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}


MOCK_BASE = "http://127.0.0.1:8799"


def endpoint_for(source: dict[str, Any]) -> str:
    """The board URL; a `base` override is honoured only for the local mock ATS (loopback)."""
    kind, cfg = source["kind"], source["config"]
    base = cfg.get("base")
    if base and base.rstrip("/") == MOCK_BASE and kind == "greenhouse":
        return f"{MOCK_BASE}/boards-api/v1/boards/{cfg['slug']}/jobs?content=true"
    return ENDPOINTS[kind].format(slug=cfg["slug"])


async def read_board(fetcher: Fetcher, source: dict[str, Any]) -> list[RawPosting]:
    kind, slug = source["kind"], source["config"]["slug"]
    res = await fetcher.get(endpoint_for(source), kind="api", source_id=source["id"])
    if res.status == 404:
        raise LookupError(f"{kind} board '{slug}' not found (404)")
    if res.status != 200:
        raise LookupError(f"{kind} board '{slug}' answered HTTP {res.status}")
    return PARSERS[kind](res.json(), source["id"], slug)
