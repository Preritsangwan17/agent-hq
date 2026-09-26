"""Deterministic fact gate: the gold pairs (CONTRACT_B §2 targets) plus hand-written probes beyond the gold set."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hq.pipeline.gates.fact_deterministic import (
    CheckContext,
    check_document,
    check_sentence,
    clauses,
    split_sentences,
)

GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "factcheck_pairs.jsonl"


def _gold() -> list[dict]:
    return [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]


def test_gold_recall_and_zero_false_blocks():
    rows = _gold()
    bad = [r for r in rows if r["label"] != "ok"]
    ok = [r for r in rows if r["label"] == "ok"]
    caught = [r for r in bad if check_sentence(r["text"], context=CheckContext(previous=r["context"]))]
    false_blocks = [(r["text"], check_sentence(r["text"], context=CheckContext(previous=r["context"])))
                    for r in ok]
    false_blocks = [(t, v) for t, v in false_blocks if v]
    assert len(caught) / len(bad) >= 0.80, f"recall {len(caught)}/{len(bad)}"
    assert not false_blocks, false_blocks


@pytest.mark.parametrize("sentence, rule", [
    ("I deployed my recommender on AWS.", "BANNED_CLAIM"),
    ("I trained a churn model with 95% accuracy.", "BANNED_CLAIM"),
    ("I have 3 years of Python experience.", "NUM_NOT_IN_FACTS"),
    ("I used PyTorch to build a CNN for image tagging.", "TECH_NOT_WHITELISTED"),
    ("Read more at https://evil.example.com/prerit.", "URL_NOT_IN_FACTS"),
    ("I kept users with 200+ ratings.", "FACT_WORDING"),
    ("I am an expert in scikit-learn.", "UNVERIFIABLE_SELF_CLAIM"),
    ("I built several end-to-end ML pipelines.", "PLURAL_OVERGEN"),
    ("I can work 25 hours per week during term.", "PROFILE_UNCONFIRMED"),
    ("My CGPA is 8.9.", "PROFILE_UNCONFIRMED"),
    ("Bengaluru is close to my home, so relocation is easy.", "ANGLE_LEAK"),
])
def test_probes_are_blocked(sentence, rule):
    rules = {v.rule for v in check_sentence(sentence)}
    assert rule in rules, rules


@pytest.mark.parametrize("sentence", [
    "I haven't deployed anything to production yet.",
    "I'm keen to learn PyTorch and would be glad to pick up SQL on the job.",
    "My GitHub is https://github.com/Preritsangwan17.",
    "I kept users with more than 200 ratings and books with at least 50 ratings.",
    "I have not used Docker, Kubernetes or any cloud platform in a project.",
    "The model returns the 5 most similar books.",
    "The churn data covered over 7,000 customers.",
])
def test_honest_sentences_pass(sentence):
    assert check_sentence(sentence) == []


def test_confirmed_fields_and_job_quotes_unlock_claims():
    s = "I can work 20 hours per week during term."
    assert check_sentence(s)
    assert check_sentence(s, context=CheckContext(confirmed_fields={"hours_cap_term": "20"})) == []
    q = "You will work with SQL and dbt daily."
    s2 = "The role works with SQL every day, which I would like to learn."
    assert check_sentence(s2, context=CheckContext(job_quotes={"J1": q})) == []
    assert any(v.rule == "TECH_NOT_WHITELISTED" for v in check_sentence("The team uses SQL daily."))


def test_citations_required_for_writer_output():
    doc = [
        {"text": "I built an item-based collaborative-filtering book recommender.", "kind": "claim", "fact_ids": []},
        {"text": "It uses the Book-Crossing dataset.", "kind": "claim", "fact_ids": ["F-BOOK-DATA"]},
        {"text": "It uses 1.15 million ratings.", "kind": "claim", "fact_ids": ["F-NOPE"]},
    ]
    report = check_document(doc, require_citations=True)
    rules = [[v["rule"] for v in s["violations"]] for s in report.sentences]
    assert "CITATION_MISSING" in rules[0]
    assert rules[1] == []
    assert "UNKNOWN_FACT_ID" in rules[2]
    assert report.passed is False


def test_wrong_project_uses_previous_sentence():
    prev = "In my churn project I trained a Random Forest classifier on the IBM Telco dataset."
    v = check_sentence("I also built a YAML-driven pipeline with custom logging.", context=CheckContext(previous=prev))
    assert any(x.rule == "WRONG_PROJECT" for x in v)
    ok = check_sentence("My book recommender has a YAML-driven pipeline with custom logging.",
                        context=CheckContext(previous=prev))
    assert ok == []


def test_clause_split_and_sentence_split():
    assert clauses("While I have not used SQL, I am keen to learn it.") == ["While I have not used SQL",
                                                                            "I am keen to learn it."]
    assert split_sentences("Dear Team,\n\nI built a recommender. It works.\n\nThanks.") == [
        "Dear Team,", "I built a recommender.", "It works.", "Thanks."]
