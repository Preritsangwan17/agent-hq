"""Dedupe (CONTRACT_C §3): the same role seen twice becomes one opportunity with several sources.
Exact: canonical key, or the (source, external id) pair, or the normalised URL. Fuzzy: company ≥ 92 and title ≥ 90
(rapidfuzz), a compatible location (same country, or either side remote/unknown), posted within 60 days."""
from __future__ import annotations

import re
import sqlite3
from datetime import timedelta
from urllib.parse import urlparse, urlunparse

from rapidfuzz import fuzz

from hq.pipeline.discover.location import parse_location
from hq.pipeline.discover.postings import RawPosting
from hq.util.timeutil import parse_iso, to_iso, utcnow

COMPANY_MIN, TITLE_MIN = 92, 90
SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|pvt|private|gmbh|ag|sa|bv|plc|corp|corporation|co|technologies|labs?)\b\.?",
                    re.I)


def norm_company(name: str) -> str:
    return " ".join(SUFFIX.sub(" ", re.sub(r"[^\w& ]", " ", name.lower())).split())


def norm_url(url: str | None) -> str | None:
    if not url:
        return None
    u = urlparse(url.strip())
    path = re.sub(r"/+$", "", u.path)
    return urlunparse(("https", (u.hostname or "").lower().removeprefix("www."), path, "", "", ""))


def find_duplicate(conn: sqlite3.Connection, p: RawPosting) -> str | None:
    row = conn.execute("SELECT id FROM opportunities WHERE canonical_key=?", (p.canonical_key,)).fetchone()
    if row:
        return row["id"]
    row = conn.execute("SELECT opportunity_id FROM opportunity_sources WHERE source_id=? AND external_id=?",
                       (p.source_id, p.external_id)).fetchone()
    if row:
        return row["opportunity_id"]
    nu = norm_url(p.url)
    since = to_iso(utcnow() - timedelta(days=60))
    place = parse_location(p.location_raw, remote_flag=p.remote)
    nc = norm_company(p.company)
    for r in conn.execute("SELECT id, company_name, title, url, country_iso2, work_mode, posted_at, first_seen_at "
                          "FROM opportunities WHERE is_simulated=0 AND first_seen_at >= ?", (since,)):
        if nu and norm_url(r["url"]) == nu:
            return r["id"]
        if fuzz.ratio(nc, norm_company(r["company_name"])) < COMPANY_MIN:
            continue
        if fuzz.token_sort_ratio(p.title.lower(), r["title"].lower()) < TITLE_MIN:
            continue
        a, b = place.country_iso2, r["country_iso2"]
        if a and b and a != b and "remote" not in (place.work_mode, r["work_mode"]):
            continue
        posted = parse_iso(p.posted_at) if p.posted_at else None
        other = parse_iso(r["posted_at"] or r["first_seen_at"])
        if posted and other and abs((posted - other).days) > 60:
            continue
        return r["id"]
    return None
