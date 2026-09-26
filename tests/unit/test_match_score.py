"""The transparent match score: career-plan priorities (regions, roles, companies), the twelve factors and the
apply / consider / skip decision."""
from __future__ import annotations

import json

import pytest

from hq.pipeline.verify.score import FACTOR_LABELS, match_score

GOOD_TEXT = ("We welcome undergraduate students currently pursuing a B.Tech. You will use Python, pandas and "
             "scikit-learn to build recommendation models and evaluation pipelines. Visa sponsorship is available. "
             "You'll have a mentor.")


def opp(**kw):
    base = {"title": "Machine Learning Intern", "company_name": "Hugging Face", "kind": "internship",
            "country_iso2": "DE", "work_mode": "onsite", "pay_status": "listed", "pay_ratio": 1.6,
            "pay_monthly_inr_min": 110000, "canonical_key": "greenhouse:x:1", "benefits": {}}
    return {**base, **kw}


def score(o, text=GOOD_TEXT, status="eligible", conf=0.9):
    return match_score(o, text=text, eligibility_confidence=conf, eligibility_status=status)


def test_every_factor_is_explained_and_weights_sum_to_100():
    total, b = score(opp())
    assert [f["key"] for f in b["factors"]] == list(FACTOR_LABELS)
    assert sum(f["weight"] for f in b["factors"]) == pytest.approx(100)
    assert all(f["why"] and 0 <= f["score"] <= 100 for f in b["factors"])
    assert total == b["total"] and b["verdict"] == "apply" and b["track"] == "core" and total >= 85
    assert "python" in b["skills_matched"]


def test_region_priorities_europe_russia_canada_australia_then_india_then_rest():
    loc = {c: {f["key"]: f for f in score(opp(country_iso2=c))[1]["factors"]}["location"]["score"]
           for c in ("DE", "CA", "RU", "AU", "IN", "US")}
    assert loc["DE"] >= loc["IN"] and loc["CA"] >= loc["IN"] and loc["RU"] > loc["IN"] and loc["AU"] > loc["IN"]
    assert loc["IN"] > loc["US"]
    within = {c: {f["key"]: f for f in score(opp(country_iso2=c))[1]["factors"]}["location"]["score"]
              for c in ("DE", "IT")}
    assert within["DE"] > within["IT"]                                  # ranked within Europe


def test_global_search_keeps_unusually_relevant_roles_elsewhere():
    _, b = score(opp(country_iso2="US"))
    assert b["exception"] and b["verdict"] == "apply"
    _, weak = score(opp(country_iso2="US", title="Marketing Analyst Intern", company_name="Acme"), text="Excel.")
    assert weak["exception"] is None and weak["verdict"] != "apply"


def test_stepping_stones_are_recognised_but_rank_below_core_roles():
    core, _ = score(opp())
    step, b = score(opp(title="Data Engineering Intern"))
    assert b["track"] == "stepping_stone" and b["stepping_stone_why"] and step < core


def test_requirements_the_profile_cannot_meet_pull_the_score_down():
    total, _ = score(opp())
    senior_text = "Requires a Master's degree and 3+ years of experience. We do not offer visa sponsorship."
    low, b = score(opp(kind="job", title="Machine Learning Engineer"), text=senior_text, conf=0.5)
    f = {x["key"]: x for x in b["factors"]}
    assert f["experience"]["score"] <= 10 and f["visa"]["score"] <= 10 and f["role_type"]["score"] <= 40
    assert f["education"]["score"] <= 40 and low < total - 25 and b["concerns"]


def test_india_needs_no_visa_and_remote_roles_are_welcome():
    f = {x["key"]: x for x in score(opp(country_iso2="IN", company_name="Flipkart"))[1]["factors"]}
    assert f["visa"]["score"] == 100 and f["company"]["score"] == 80
    r = {x["key"]: x for x in score(opp(country_iso2=None, work_mode="remote",
                                        location_raw="Remote - Europe"))[1]["factors"]}
    assert r["location"]["score"] >= 85 and r["visa"]["score"] >= 90


def test_known_mill_and_unknown_pay_are_marked():
    f = {x["key"]: x for x in score(opp(known_mill=True, pay_status="unknown", pay_ratio=None))[1]["factors"]}
    assert f["company"]["score"] == 0 and f["compensation"]["score"] == 50


def test_apply_anyway_pushes_a_parked_match_through(authed, db):
    from hq.db.conn import tx
    from tests.conftest import MUTATE
    from tests.unit.test_api import seed_opp

    oid = seed_opp(db, stage="verified")
    with tx(db):
        db.execute("UPDATE opportunities SET fit_score=52 WHERE id=?", (oid,))
    r = authed.post(f"/api/opportunities/{oid}/apply-anyway", headers=MUTATE)
    assert r.status_code == 200 and r.json()["queued"] is True
    task = db.execute("SELECT payload_json FROM tasks WHERE capability='score.fit' AND opportunity_id=?", (oid,)).fetchone()
    assert json.loads(task[0]) == {"force": True}
    other = seed_opp(db, "nimbus-ml-intern", stage="applied")
    assert authed.post(f"/api/opportunities/{other}/apply-anyway", headers=MUTATE).status_code == 409
