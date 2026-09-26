"""`ats_resolve` (CONTRACT_D §2): find a role seen in a job-alert email on the company's own Greenhouse / Lever /
Ashby board — a compliant channel HQ may read and prepare for, unlike the alert site itself. Known sources first,
then the obvious slug guesses; GET-only through the polite fetcher; a title match needs fuzz ≥ 90."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from rapidfuzz import fuzz

from hq.adapters.base import TransientError
from hq.pipeline.discover.ats import read_board
from hq.pipeline.discover.fetch import FetchBlocked
from hq.pipeline.discover.postings import RawPosting
from hq.pipeline.discover.sources import ATS_KINDS

MIN_TITLE_SCORE = 90
MAX_BOARDS = 6


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def candidates(conn: sqlite3.Connection, company: str, *, guess: bool = True) -> list[dict[str, Any]]:
    want = _norm(company)
    if len(want) < 3:
        return []
    out = []
    for r in conn.execute(f"SELECT * FROM sources WHERE kind IN ({','.join('?' * len(ATS_KINDS))})", ATS_KINDS):
        import json

        cfg = json.loads(r["config_json"] or "{}")
        slug = cfg.get("slug") or ""
        if _norm(slug.replace("-production", "")) == want or _norm(r["name"]).endswith(want):
            out.append({"id": r["id"], "kind": r["kind"], "config": cfg, "name": r["name"]})
    if guess:
        known = {(c["kind"], c["config"]["slug"]) for c in out}
        for kind in ATS_KINDS:
            for slug in dict.fromkeys([want, re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")]):
                if (kind, slug) not in known:
                    out.append({"id": f"{kind}:{slug}", "kind": kind, "config": {"slug": slug}, "name": slug,
                                "guessed": True})
    return out[:MAX_BOARDS]


async def resolve(fetcher: Any, conn: sqlite3.Connection, company: str, title: str) -> RawPosting | None:
    if fetcher is None:
        return None
    for src in candidates(conn, company):
        try:
            found = await read_board(fetcher, src)
        except (FetchBlocked, LookupError, TransientError, ValueError, KeyError):
            continue
        scored = [(fuzz.token_set_ratio(p.title.lower(), title.lower()), p) for p in found]
        scored = [x for x in scored if x[0] >= MIN_TITLE_SCORE]
        if scored:
            return max(scored, key=lambda x: x[0])[1]
    return None
