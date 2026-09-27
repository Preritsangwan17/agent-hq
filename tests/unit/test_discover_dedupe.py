"""Job identity regression tests: tracking links may match, requisitions may not."""
from hq.db import repo
from hq.pipeline.discover.dedupe import find_duplicate, norm_url
from hq.pipeline.discover.postings import RawPosting


def _posting(external_id: str, url: str, *, source_kind: str = "greenhouse", source_id: str = "greenhouse:acme",
             location: str = "Bengaluru, India") -> RawPosting:
    return RawPosting(source_id, source_kind, external_id, "Acme", "Machine Learning Intern", url,
                      location_raw=location)


def _save(db, p: RawPosting) -> str:
    return repo.insert_opportunity(db, {
        "canonical_key": p.canonical_key, "company_name": p.company, "title": p.title,
        "url": p.url, "city": "Bengaluru", "country_iso2": "IN", "work_mode": "onsite",
    }, is_simulated=False)


def test_url_identity_keeps_job_parameters_and_spa_fragment():
    assert norm_url("https://www.example.com/jobs?gh_jid=1&utm_source=board") == \
        norm_url("http://example.com/jobs/?utm_medium=email&gh_jid=1")
    assert norm_url("https://example.com/jobs?gh_jid=1") != norm_url("https://example.com/jobs?gh_jid=2")
    assert norm_url("https://example.com/#/jobs/1") != norm_url("https://example.com/#/jobs/2")
    assert norm_url("http://127.0.0.1:8799/jobs/1") != norm_url("http://127.0.0.1:8800/jobs/1")
    assert norm_url("https://example.com/jobs?ref=1") != norm_url("https://example.com/jobs?ref=2")
    assert norm_url("/jobs/1") is None
    assert norm_url("https://example.com:bad/jobs/1") is None


def test_different_requisitions_do_not_merge_by_title(db):
    first = _posting("1", "https://acme.example/jobs?gh_jid=1")
    oid = _save(db, first)
    assert find_duplicate(db, _posting("2", "https://acme.example/jobs?gh_jid=2")) is None
    assert find_duplicate(db, _posting("2", "https://acme.example/jobs?gh_jid=1&utm_source=mail")) == oid


def test_two_official_ids_and_distinct_onsite_cities_stay_separate(db):
    first = _posting("1", "https://boards.greenhouse.io/acme/jobs/1")
    _save(db, first)
    assert find_duplicate(db, _posting("2", "https://boards.greenhouse.io/acme/jobs/2")) is None
    feed = _posting("feed-2", "https://feed.example/other", source_kind="feed", source_id="feed:x",
                    location="Mumbai, India")
    assert find_duplicate(db, feed) is None


def test_unknown_company_does_not_trigger_fuzzy_merge(db):
    first = _posting("1", "https://feed.example/one", source_kind="feed", source_id="feed:a")
    first.company = "Unknown"
    _save(db, first)
    second = _posting("2", "https://another.example/two", source_kind="feed", source_id="feed:b")
    second.company = "Unknown"
    assert find_duplicate(db, second) is None
