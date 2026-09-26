"""Link + deadline verification (PLAN §3). ATS postings are "live" while they are still on the board (one cached
board read covers every posting); other pages need a 200 and no "closed" markers. Manual-lane links are never
fetched (`not_automatable`). Deadlines are treated as one day earlier than stated; no deadline = rolling."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from hq.pipeline.discover.ats import ENDPOINTS, PARSERS
from hq.pipeline.discover.fetch import FetchBlocked, Fetcher
from hq.util import netguard
from hq.util.timeutil import parse_iso

CLOSED = re.compile(r"(no longer (accepting|available|open)|position (has been )?(filled|closed)|job (is )?closed|"
                    r"applications? (are |is )?(now )?closed|this (job|posting) has expired|page not found|404)", re.I)
BUFFER = timedelta(days=1)


@dataclass
class LinkResult:
    status: str        # live | dead | not_automatable | unknown
    reason: str


async def check_link(fetcher: Fetcher, *, canonical_key: str, url: str | None) -> LinkResult:
    kind, _, rest = canonical_key.partition(":")
    if kind in ENDPOINTS:
        slug, _, ext = rest.partition(":")
        res = await fetcher.get(ENDPOINTS[kind].format(slug=slug), kind="api", source_id=f"{kind}:{slug}")
        if res.status != 200:
            return LinkResult("unknown", f"board answered HTTP {res.status}")
        ids = {p.external_id for p in PARSERS[kind](res.json(), f"{kind}:{slug}", slug)}
        return LinkResult("live", "still on the board") if ext in ids else LinkResult("dead", "no longer on the board")
    if not url:
        return LinkResult("unknown", "no URL")
    if netguard.is_manual_lane(url):
        return LinkResult("not_automatable", "manual-lane site; HQ doesn't fetch it")
    try:
        res = await fetcher.get(url, kind="html")
    except FetchBlocked as exc:
        return LinkResult("not_automatable", str(exc))
    if res.status in (404, 410):
        return LinkResult("dead", f"HTTP {res.status}")
    if res.status != 200:
        return LinkResult("unknown", f"HTTP {res.status}")
    head = res.text[:20000]
    m = CLOSED.search(head)
    return LinkResult("dead", f"page says “{m.group(0)}”") if m else LinkResult("live", "page is up")


def deadline_state(deadline_at: str | None, now: datetime | None = None) -> tuple[str, str]:
    """(open|expired|rolling, reason) with a conservative one-day buffer."""
    if not deadline_at:
        return "rolling", "no deadline stated — re-verified every 3 days"
    dl = parse_iso(deadline_at)
    now = now or datetime.now(timezone.utc)
    if dl is None:
        return "rolling", "deadline unreadable"
    if dl - BUFFER <= now:
        return "expired", f"deadline {deadline_at[:10]} has passed (1-day safety margin)"
    return "open", f"{(dl - BUFFER - now).days} days left before the safe deadline"
