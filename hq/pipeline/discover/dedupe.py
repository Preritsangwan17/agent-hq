"""Dedupe (CONTRACT_C §3): the same role seen twice becomes one opportunity with several sources.
Exact: canonical key, or the (source, external id) pair, or the normalised URL. Fuzzy: company ≥ 92 and title ≥ 90
(rapidfuzz), compatible location and requisition identity, posted within 60 days."""
from __future__ import annotations

import re
import sqlite3
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from rapidfuzz import fuzz

from hq.pipeline.discover.location import parse_location
from hq.pipeline.discover.postings import RawPosting
from hq.util.timeutil import parse_iso, to_iso, utcnow

COMPANY_MIN, TITLE_MIN = 92, 90
SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|pvt|private|gmbh|ag|sa|bv|plc|corp|corporation|co|technologies|labs?)\b\.?",
                    re.I)
TRACKING = {"gclid", "fbclid", "msclkid"}
OFFICIAL_ATS = {"greenhouse", "lever", "ashby"}


def norm_company(name: str) -> str:
    return " ".join(SUFFIX.sub(" ", re.sub(r"[^\w& ]", " ", name.lower())).split())


def norm_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        u = urlparse(url.strip())
        if u.scheme.lower() not in ("http", "https") or not u.hostname:
            return None
        port = u.port
    except ValueError:
        return None
    path = re.sub(r"/+$", "", u.path)
    # Query strings and SPA fragments can contain the requisition ID. Discard only known tracking keys.
    query = urlencode(sorted((k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
                           if not k.lower().startswith("utm_") and k.lower() not in TRACKING))
    host = u.hostname.lower().removeprefix("www.")
    host += f":{port}" if port else ""
    return urlunparse(("https", host, path, "", query, u.fragment))


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
    for r in conn.execute("SELECT id, canonical_key, company_name, title, url, city, country_iso2, work_mode, "
                          "posted_at, first_seen_at "
                          "FROM opportunities WHERE is_simulated=0 AND first_seen_at >= ?", (since,)):
        other_url = norm_url(r["url"])
        if nu and nu == other_url:
            return r["id"]
        # Distinct requisitions on one URL path must not be merged by the fallback title match.
        if nu and other_url and urlparse(nu)._replace(query="", fragment="") == urlparse(other_url)._replace(query="", fragment=""):
            continue
        old_kind = r["canonical_key"].split(":", 1)[0]
        if p.source_kind in OFFICIAL_ATS and old_kind in OFFICIAL_ATS:
            # Two official ATS records with distinct IDs can represent separate openings.
            continue
        old_company = norm_company(r["company_name"])
        if nc in ("", "unknown") or old_company in ("", "unknown"):
            continue
        if fuzz.ratio(nc, old_company) < COMPANY_MIN:
            continue
        if fuzz.token_sort_ratio(p.title.lower(), r["title"].lower()) < TITLE_MIN:
            continue
        a, b = place.country_iso2, r["country_iso2"]
        if a and b and a != b and "remote" not in (place.work_mode, r["work_mode"]):
            continue
        if (place.city and r["city"] and place.city.casefold() != r["city"].casefold()
                and "remote" not in (place.work_mode, r["work_mode"])):
            continue
        posted = parse_iso(p.posted_at) if p.posted_at else None
        other = parse_iso(r["posted_at"] or r["first_seen_at"])
        if posted and other and abs((posted - other).days) > 60:
            continue
        return r["id"]
    return None
