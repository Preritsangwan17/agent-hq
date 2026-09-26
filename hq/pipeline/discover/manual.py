"""Paste-a-link (CONTRACT_C §3): Prerit pastes a URL and, for manual-lane sites, the posting text. Manual-lane
URLs are NEVER fetched; the pasted text is the posting and the application becomes a Needs Prerit pack."""
from __future__ import annotations

import hashlib

from hq.pipeline.discover.postings import RawPosting
from hq.util import netguard


def manual_posting(url: str, text: str | None, *, company: str | None = None, title: str | None = None) -> RawPosting:
    lane = netguard.is_manual_lane(url)
    ext = hashlib.sha1(url.strip().encode()).hexdigest()[:16]
    return RawPosting("manual:paste", "manual", ext, (company or netguard.host_of(url) or "Unknown").strip(),
                      (title or "Pasted posting").strip(), url.strip(), text=(text or "").strip(),
                      automation="manual_lane" if lane else "discover_only",
                      extra={"manual_lane": lane, "needs_fetch": not lane and not (text or "").strip()})
