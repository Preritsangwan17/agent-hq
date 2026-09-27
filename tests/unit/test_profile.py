"""Profile facts/fields seeding and the Settings routes (profile, security, audit, passcode change)."""
from __future__ import annotations

import json

from hq.profile import fields as pfields
from hq.profile.facts import load_facts
from tests.conftest import MUTATE, PASSCODE


def test_facts_yaml_parses_with_evidence_links():
    sheet = load_facts()
    ids = sheet.by_id()
    assert "F-BOOK-FILTER" in ids and "F-SKILLS" in ids
    assert "more than 200" in ids["F-BOOK-FILTER"].text
    assert ids["F-BOOK-KNN"].evidence_url.startswith("https://github.com/Preritsangwan17/End-to-End-Book")
    assert "/tree/2a5c9e39" in ids["F-BOOK-KNN"].evidence_url
    assert ids["F-NAME"].evidence_url is None


def test_seed_is_idempotent_and_keeps_prerit_status(db):
    n = db.execute("SELECT COUNT(*) FROM profile_facts").fetchone()[0]
    assert n == len(load_facts().facts)
    db.execute("UPDATE profile_facts SET status='retired' WHERE id='F-BOOK-COSINE'")
    from hq.db.seed import seed_all

    seed_all(db)
    assert db.execute("SELECT status FROM profile_facts WHERE id='F-BOOK-COSINE'").fetchone()[0] == "retired"
    assert db.execute("SELECT COUNT(*) FROM profile_fields").fetchone()[0] == len(pfields.FIELD_DEFS)
    assert pfields.confirmed_value(db, "gender") == "male"
    pfields.update_field(db, "gender", "prefer not to say")
    seed_all(db)
    assert pfields.confirmed_value(db, "gender") == "prefer not to say"


def test_unconfirmed_and_never_fields_are_not_used_outbound(db):
    db.execute("UPDATE profile_fields SET value='+91 99999 99999' WHERE key='phone'")
    assert pfields.confirmed_value(db, "phone") is None
    pfields.update_field(db, "phone", "+91 99999 99999")
    assert pfields.confirmed_value(db, "phone") == "+91 99999 99999"
    pfields.update_field(db, "address", "Somewhere 1")
    assert pfields.confirmed_value(db, "address") is None
    assert pfields.confirmed_value(db, "address", outbound=False) == "Somewhere 1"


def test_field_validation():
    assert pfields.validate_value("cgpa", "8.7") == "8.7"
    assert pfields.validate_value("semester", 3) == "3"
    assert pfields.validate_value("passport", "Yes") == "yes"
    for key, bad in [("cgpa", "11"), ("semester", "x"), ("passport", "maybe"), ("dob", "01/02/2006")]:
        try:
            pfields.validate_value(key, bad)
        except pfields.FieldError:
            continue
        raise AssertionError(f"{key}={bad!r} should be rejected")
    windows = pfields.validate_value("availability_windows", [{"from": "2027-05-15", "to": "2027-07-31",
                                                               "hours_per_week": 40, "mode": "any"}])
    assert json.loads(windows)[0]["hours_per_week"] == 40


def test_profile_routes(authed):
    r = authed.get("/api/profile")
    assert r.status_code == 200
    body = r.json()
    assert "phone" in body["required_missing"]
    assert any(f["id"] == "F-BOOK-FILTER" for f in body["facts"])

    r = authed.patch("/api/profile/fields/cgpa", json={"value": "12"}, headers=MUTATE)
    assert r.status_code == 400 and "CGPA" in r.json()["error"]
    r = authed.patch("/api/profile/fields/cgpa", json={"value": "8.4"}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["confirmed"] is True
    assert "cgpa" not in authed.get("/api/profile").json()["required_missing"]

    audit = authed.get("/api/audit", params={"action": "profile"}).json()["items"]
    assert audit and audit[0]["target"] == "cgpa"
    # personal values never land in the audit log
    assert "8.4" not in json.dumps([(a["before"], a["after"], a["target"]) for a in audit])

    r = authed.patch("/api/profile/facts/F-BOOK-COSINE", json={"status": "retired"}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["status"] == "retired"
    assert authed.patch("/api/profile/fields/nope", json={"value": "x"}, headers=MUTATE).status_code == 404


def test_security_and_passcode_change(authed):
    sec = authed.get("/api/security").json()
    assert sec["lan"] is False and sec["loopback"] is True
    assert "HQ_PASSCODE_HASH" in sec["secrets_present"]
    assert all("=" not in k for k in sec["secrets_present"])

    r = authed.post("/api/auth/change-passcode", json={"current": "wrong", "new": "another-one-9"}, headers=MUTATE)
    assert r.status_code == 401
    r = authed.post("/api/auth/change-passcode", json={"current": PASSCODE, "new": "another-one-9"}, headers=MUTATE)
    assert r.status_code == 200
    authed.post("/api/auth/logout", headers=MUTATE)
    assert authed.post("/api/auth/login", json={"passcode": "another-one-9"}, headers=MUTATE).status_code == 200
