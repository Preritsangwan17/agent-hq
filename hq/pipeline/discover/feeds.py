"""Remote job feeds (CONTRACT_E §3): Remotive, Arbeitnow (visa sponsorship), Himalayas, Jobicy, We Work Remotely.

Public read APIs / RSS used as documented, GET only through the polite fetcher, with attribution (source label) and
a link back to the original posting. Roles whose location restriction excludes India are skipped at discovery."""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from hq.pipeline.discover.fetch import Fetcher
from hq.pipeline.discover.postings import RawPosting
from hq.pipeline.discover.text import html_to_text

FEEDS: dict[str, dict[str, str]] = {
    "remotive": {"label": "Remotive", "url": "https://remotive.com/api/remote-jobs?search=intern"},
    "arbeitnow": {"label": "Arbeitnow", "url": "https://www.arbeitnow.com/api/job-board-api?visa_sponsorship=true"},
    "himalayas": {"label": "Himalayas", "url": "https://himalayas.app/jobs/api?limit=100"},
    "jobicy": {"label": "Jobicy", "url": "https://jobicy.com/api/v2/remote-jobs?count=50&tag=intern"},
    "wwr": {"label": "We Work Remotely", "url": "https://weworkremotely.com/categories/remote-programming-jobs.rss"},
}
OK_REGIONS = re.compile(r"india|worldwide|anywhere|global|asia|apac|remote$|^$", re.I)


def location_ok(restriction: str | list | None) -> bool:
    """True when India can apply (no restriction, worldwide, Asia/APAC or India listed)."""
    if not restriction:
        return True
    items = restriction if isinstance(restriction, list) else re.split(r"[,;/|]| or ", str(restriction))
    items = [str(i).strip() for i in items if str(i).strip()]
    return not items or any(OK_REGIONS.search(i) for i in items)


def _ext(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _iso(v: Any) -> str | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(v)[:19] + "Z" if len(str(v)) >= 19 and "T" in str(v) else str(v)


def _posting(src: str, feed: str, ext: str, company: str, title: str, url: str, text: str, loc: str | None,
             posted: Any = None, pay: str | None = None, etype: str | None = None) -> RawPosting:
    return RawPosting(src, "feed", ext, (company or "Unknown").strip()[:120], (title or "").strip()[:200], url,
                      text, loc or "Remote", url, _iso(posted), pay, etype, remote=True,
                      extra={"feed": feed, "attribution": FEEDS[feed]["label"]})


def parse_remotive(data: dict, src: str) -> tuple[list[RawPosting], int]:
    out, skipped = [], 0
    for j in data.get("jobs") or []:
        if not location_ok(j.get("candidate_required_location")):
            skipped += 1
            continue
        out.append(_posting(src, "remotive", str(j.get("id")), j.get("company_name"), j.get("title"), j.get("url", ""),
                            html_to_text(j.get("description")), j.get("candidate_required_location"),
                            j.get("publication_date"), j.get("salary") or None, j.get("job_type")))
    return out, skipped


def parse_arbeitnow(data: dict, src: str) -> tuple[list[RawPosting], int]:
    out = []
    for j in data.get("data") or []:
        if not j.get("visa_sponsorship", True):
            continue
        text = html_to_text(j.get("description")) + ("\n\nVisa sponsorship offered." if j.get("visa_sponsorship") else "")
        out.append(_posting(src, "arbeitnow", j.get("slug") or _ext(j.get("url")), j.get("company_name"),
                            j.get("title"), j.get("url", ""), text, j.get("location"), j.get("created_at"),
                            etype=", ".join(j.get("job_types") or []) or None))
    return out, 0


def parse_himalayas(data: dict, src: str) -> tuple[list[RawPosting], int]:
    out, skipped = [], 0
    for j in data.get("jobs") or []:
        if not location_ok(j.get("locationRestrictions")):
            skipped += 1
            continue
        pay = None
        if j.get("minSalary") or j.get("maxSalary"):
            pay = f"{j.get('currency') or 'USD'} {j.get('minSalary') or ''}-{j.get('maxSalary') or ''} per year"
        url = j.get("applicationLink") or j.get("guid") or ""
        out.append(_posting(src, "himalayas", _ext(j.get("guid") or url), j.get("companyName"), j.get("title"), url,
                            html_to_text(j.get("description") or j.get("excerpt")),
                            ", ".join(j.get("locationRestrictions") or []) or None, j.get("pubDate"), pay,
                            j.get("employmentType")))
    return out, skipped


def parse_jobicy(data: dict, src: str) -> tuple[list[RawPosting], int]:
    out, skipped = [], 0
    for j in data.get("jobs") or []:
        if not location_ok(j.get("jobGeo")):
            skipped += 1
            continue
        pay = None
        if j.get("annualSalaryMin"):
            pay = f"{j.get('salaryCurrency') or 'USD'} {j['annualSalaryMin']}-{j.get('annualSalaryMax') or ''} per year"
        out.append(_posting(src, "jobicy", str(j.get("id")), j.get("companyName"), j.get("jobTitle"), j.get("url", ""),
                            html_to_text(j.get("jobDescription") or j.get("jobExcerpt")), j.get("jobGeo"),
                            j.get("pubDate"), pay, ", ".join(j["jobType"]) if isinstance(j.get("jobType"), list)
                            else j.get("jobType")))
    return out, skipped


def parse_wwr(xml: str, src: str) -> tuple[list[RawPosting], int]:
    out, skipped = [], 0
    root = ET.fromstring(xml)
    for item in root.iter("item"):
        title_raw = (item.findtext("title") or "").strip()
        company, _, title = title_raw.partition(":")
        if not title:
            company, title = "", title_raw
        region = (item.findtext("region") or "").strip()
        if not location_ok(region):
            skipped += 1
            continue
        link = (item.findtext("link") or "").strip()
        out.append(_posting(src, "wwr", _ext(link), company, title, link, html_to_text(item.findtext("description")),
                            region or None, item.findtext("pubDate")))
    return out, skipped


PARSERS = {"remotive": parse_remotive, "arbeitnow": parse_arbeitnow, "himalayas": parse_himalayas,
           "jobicy": parse_jobicy}


async def read_feed(fetcher: Fetcher, source: dict[str, Any]) -> tuple[list[RawPosting], int]:
    feed = source["config"]["feed"]
    res = await fetcher.get(source["config"].get("url") or FEEDS[feed]["url"], kind="api", source_id=source["id"])
    if res.status != 200:
        raise LookupError(f"{FEEDS[feed]['label']} answered HTTP {res.status}")
    if feed == "wwr":
        return parse_wwr(res.text, source["id"])
    return PARSERS[feed](res.json(), source["id"])
