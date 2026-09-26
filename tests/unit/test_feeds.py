"""Remote feeds (CONTRACT_E §3): parsing, the India location rule, and scout discovery through a mock transport."""
from __future__ import annotations

import httpx
from conftest import drive

from hq.adapters.base import Services
from hq.db.conn import tx
from hq.db.seed import set_settings
from hq.pipeline.discover import feeds
from hq.pipeline.discover.fetch import Fetcher
from hq.worker import queue
from hq.worker.orchestrator import Worker

REMOTIVE = {"jobs": [
    {"id": 1, "url": "https://remotive.com/remote-jobs/1", "title": "Machine Learning Intern", "company_name": "Acme AI",
     "candidate_required_location": "Worldwide", "publication_date": "2026-09-20T10:00:00", "salary": "",
     "description": "<p>Python and pandas.</p>", "job_type": "internship"},
    {"id": 2, "url": "https://remotive.com/remote-jobs/2", "title": "Data Science Intern", "company_name": "US Only Co",
     "candidate_required_location": "USA", "description": "x"},
    {"id": 3, "url": "https://remotive.com/remote-jobs/3", "title": "Senior Staff Engineer", "company_name": "Acme AI",
     "candidate_required_location": "Worldwide", "description": "x"}]}
WWR = """<rss><channel><item><title>Orbit: Junior Python Developer</title><region>Anywhere in the World</region>
<link>https://weworkremotely.com/remote-jobs/orbit-junior</link><pubDate>Mon, 21 Sep 2026</pubDate>
<description>&lt;p&gt;Build APIs&lt;/p&gt;</description></item>
<item><title>Euro: ML Intern</title><region>Europe Only</region><link>https://weworkremotely.com/x</link></item>
</channel></rss>"""


def test_location_rule():
    assert feeds.location_ok(None) and feeds.location_ok("Worldwide") and feeds.location_ok(["India", "USA"])
    assert feeds.location_ok("APAC") and not feeds.location_ok("USA") and not feeds.location_ok(["Europe", "Canada"])


def test_parsers():
    got, skipped = feeds.parse_remotive(REMOTIVE, "feed:remotive")
    assert [p.company for p in got] == ["Acme AI", "Acme AI"] and skipped == 1
    assert got[0].url == "https://remotive.com/remote-jobs/1" and got[0].canonical_key == "feed:remotive:1"
    got, skipped = feeds.parse_wwr(WWR, "feed:wwr")
    assert [(p.company, p.title) for p in got] == [("Orbit", "Junior Python Developer")] and skipped == 1
    got, _ = feeds.parse_arbeitnow({"data": [{"slug": "a", "company_name": "B", "title": "Werkstudent ML",
                                              "url": "https://arbeitnow.com/a", "visa_sponsorship": True,
                                              "description": "x", "created_at": 1790000000}]}, "feed:arbeitnow")
    assert got[0].posted_at.startswith("2026") and "Visa sponsorship" in got[0].text


async def test_scout_reads_feeds(db, team):
    def api(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if req.url.host == "remotive.com":
            return httpx.Response(200, json=REMOTIVE)
        return httpx.Response(404)

    async def nosleep(_):
        return None

    with tx(db):
        set_settings(db, {"sim_enabled": False})
        db.execute("UPDATE sources SET enabled=0 WHERE id != 'feed:remotive'")
    w = Worker(conn=db, agents_dir=team, loop_interval=0.01, watch=False, schedule=False,
               services=Services(fetcher=Fetcher(db, transport=httpx.MockTransport(api), sleep=nosleep)))
    w.startup()
    with tx(db):
        queue.enqueue(db, "discover.feed", type_="scheduled")
    assert await drive(w, lambda: db.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 1, timeout=10)
    await w.shutdown()
    o = db.execute("SELECT * FROM opportunities").fetchone()
    assert o["title"] == "Machine Learning Intern" and o["source_label"].startswith("Remotive")
    assert o["url"] == "https://remotive.com/remote-jobs/1" and o["work_mode"] == "remote"
