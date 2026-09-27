"""Automated submission must have fresh evidence that the posting is open."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from hq.pipeline.agents import applicant
from hq.pipeline.verify.link import LinkResult
from hq.util.timeutil import now_iso, to_iso, utcnow


def _ctx(db, fetcher=object()):
    return SimpleNamespace(conn=db, settings={}, services=SimpleNamespace(fetcher=fetcher),
                           progress=lambda *_: None)


def _opp():
    return {"id": "opp-1", "canonical_key": "greenhouse:acme:1", "company_name": "Acme", "title": "ML Intern",
            "url": "https://boards.greenhouse.io/acme/jobs/1", "link_status": "live",
            "last_verified_at": now_iso()}


async def test_recent_unknown_link_blocks_automatic_submission(db):
    opp = _opp()
    opp["link_status"] = "unknown"
    result = await applicant.recheck(_ctx(db), opp)
    assert result is not None and result.output["ok"] is False
    assert "not verified open" in result.output["stage_reason"]


@pytest.mark.parametrize("status", ["unknown", "dead", "not_automatable"])
async def test_stale_link_needs_fresh_live_result(db, monkeypatch, status):
    opp = _opp()
    opp["last_verified_at"] = to_iso(utcnow() - timedelta(days=2))

    async def check(*args, **kwargs):
        return LinkResult(status, "test result")

    monkeypatch.setattr(applicant, "check_link", check)
    result = await applicant.recheck(_ctx(db), opp)
    assert result is not None and result.output["ok"] is False
    assert "test result" in result.output["stage_reason"]


async def test_fresh_live_result_allows_submission(db, monkeypatch):
    opp = _opp()
    opp["last_verified_at"] = to_iso(utcnow() - timedelta(days=2))

    async def check(*args, **kwargs):
        return LinkResult("live", "still on board")

    monkeypatch.setattr(applicant, "check_link", check)
    assert await applicant.recheck(_ctx(db), opp) is None
    assert await applicant.recheck(_ctx(db, fetcher=None), opp) is not None
