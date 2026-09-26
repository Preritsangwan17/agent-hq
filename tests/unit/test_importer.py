"""Legacy importer end to end into a temp DB (offline FX from the committed seed). Skips if the old folder is absent."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hq import settings
from hq.db.conn import connect
from hq.db.migrate import migrate
from hq.importer.legacy import CONFIRM_TITLE, SOURCE_LABEL, TEEP_ID, import_legacy, load_items, load_letters, main
from hq.pipeline.verify.fx import FxRates

_CANDIDATES = [
    os.environ.get("HQ_LEGACY_SRC"),
    settings.ROOT / "legacy" / "applications",
    settings.ROOT / "applications",
    "/Users/preritsangwan/Library/Application Support/Claude/scratch-workspaces/53fd0e06-f0d3-4ac6-9bac-9b0546625df8/"
    "8d474ecb-3352-4f4e-8ce0-81d2e005fcc9/scratch-2026-09-26-25af46/applications",
]
SRC = next((Path(p) for p in _CANDIDATES if p and (Path(p) / "jobs.json").exists()), None)
needs_src = pytest.mark.skipif(SRC is None, reason="legacy applications folder not found (set HQ_LEGACY_SRC)")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("HQ_OFFLINE", "1")
    conn = connect(tmp_path / "hq.db")
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture
def fx(tmp_path):
    return FxRates(offline=True, cache_path=tmp_path / "fx" / "rates.json")


def opps(conn):
    return {r["canonical_key"].removeprefix("legacy:"): dict(r) for r in conn.execute("SELECT * FROM opportunities")}


def test_load_letters_is_static(tmp_path):
    good = tmp_path / "letters.py"
    good.write_text('A = "x"\nB = ("y" "z")\nLETTERS = {"k": f"""{A}-{B}!""", "j": A + "q"}\n')
    assert load_letters(good) == {"k": "x-yz!", "j": "xq"}
    bad = tmp_path / "bad.py"
    bad.write_text('import os\nLETTERS = {"k": f"{os.system(\'echo pwned\')}"}\n')
    with pytest.raises(ValueError):
        load_letters(bad)


@needs_src
def test_import_end_to_end(db, fx):
    report = import_legacy(db, SRC, fx=fx)
    assert report.counts() == {"created": 11, "updated": 0, "unchanged": 0}
    assert report.warnings == []
    rows = opps(db)
    assert len(rows) == 11
    assert all(r["is_simulated"] == 0 and r["source_label"] == SOURCE_LABEL for r in rows.values())
    assert {k for k, r in rows.items() if r["stage"] == "skipped"} == {"07-codingninjas"}
    assert rows["07-codingninjas"]["stage_reason"] == "dropped; no final letter"
    assert sum(r["stage"] == "frozen" for r in rows.values()) == 10

    usd, twd = fx.rate("USD")[0], fx.rate("TWD")[0]
    readyly = rows["01-readyly"]
    assert readyly["pay_monthly_inr_min"] == 25000 and readyly["work_mode"] == "remote"
    assert readyly["living_cost_monthly_inr"] == 12000 and readyly["pay_ratio"] == pytest.approx(25000 / 12000, 1e-3)
    logphase = rows["02-logphase"]
    assert (logphase["pay_monthly_inr_min"], logphase["pay_monthly_inr_max"]) == (25000, 40000)
    assert logphase["deadline_at"].startswith("2026-10-21") and logphase["deadline_confidence"] == "low"
    outlier = rows["04-outlier"]
    assert outlier["pay_status"] == "variable" and outlier["pay_monthly_inr_min"] is None
    assert outlier["pay_hourly_inr_min"] == pytest.approx(13.25 * usd, abs=0.01)
    assert outlier["pay_hourly_inr_max"] == pytest.approx(27.5 * usd, abs=0.01)
    teep = rows[TEEP_ID]
    assert teep["company_name"] == "National Chung Cheng University (CCU)"
    assert teep["apply_email"] == "cychiu@ccu.edu.tw" and teep["apply_channel"] == "email"
    assert (teep["pay_currency"], teep["city"], teep["country_iso2"]) == ("TWD", "Chiayi", "TW")
    assert teep["pay_monthly_inr_min"] == round(15000 * twd)
    assert "RE-VERIFY" in teep["notes_unverified"] and "re-verified" in teep["stage_reason"]
    assert rows["05-stripe"]["pay_status"] == "unknown" and rows["05-stripe"]["city"] == "Bengaluru"
    assert rows["10-epfl"]["country_iso2"] == "CH" and rows["10-epfl"]["lat"] is not None
    assert rows["09-srfp"]["living_cost_basis"] == "unseeded"

    jobs = {j["id"]: j for j in json.loads((SRC / "jobs.json").read_text())}
    for key, job in jobs.items():
        assert rows[key]["notes_unverified"] == job["angle"]


@needs_src
def test_applications_documents_and_needs(db, fx):
    import_legacy(db, SRC, fx=fx)
    statuses = dict(db.execute("SELECT o.canonical_key, a.status FROM applications a "
                               "JOIN opportunities o ON o.id = a.opportunity_id").fetchall())
    assert len(statuses) == 11
    assert statuses.pop("legacy:07-codingninjas") == "skipped"
    assert set(statuses.values()) == {"historical_frozen"}

    letters = load_letters(SRC / "letters.py")
    docs = db.execute("SELECT d.*, o.canonical_key FROM documents d JOIN opportunities o ON o.id = d.opportunity_id")
    by_kind: dict[str, list] = {}
    for doc in docs:
        by_kind.setdefault(doc["kind"], []).append(doc)
        assert doc["status"] == "historical"
        if doc["content_text"] is not None:
            assert doc["content_text"] == letters[doc["canonical_key"].removeprefix("legacy:")]
        else:
            assert Path(doc["content_path"]).exists() and doc["content_path"].endswith(".pdf")
    assert len(by_kind["resume_pdf"]) == 10 and len(by_kind["compact_pdf"]) == 1
    assert len(by_kind["cold_email"]) == 1 and len(by_kind["profile_summary"]) == 1
    assert len(by_kind["research_statement"]) == 1 and len(by_kind["cover_letter"]) == 7
    linked = db.execute("SELECT count(*) FROM applications WHERE letter_doc_id IS NOT NULL "
                        "AND resume_doc_id IS NOT NULL").fetchone()[0]
    assert linked == 10

    needs = {r["kind"]: dict(r) for r in db.execute("SELECT * FROM needs_prerit")}
    assert set(needs) == {"confirm_legacy", "decision"}
    assert needs["confirm_legacy"]["title"] == CONFIRM_TITLE
    assert len(json.loads(needs["confirm_legacy"]["answers_json"])) == 11
    assert "more than 200 ratings" in needs["decision"]["title"]
    assert "02-logphase" in needs["decision"]["instructions_md"]


@needs_src
def test_idempotent_and_respects_stage_override(db, fx):
    import_legacy(db, SRC, fx=fx)
    counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("opportunities", "applications", "documents", "needs_prerit", "companies",
                        "opportunity_sources")}
    db.execute("UPDATE opportunities SET stage='applied', stage_override=1 WHERE canonical_key='legacy:01-readyly'")
    db.execute("UPDATE needs_prerit SET status='done' WHERE kind='confirm_legacy'")
    report = import_legacy(db, SRC, fx=fx)
    assert report.counts() == {"created": 0, "updated": 0, "unchanged": 11}
    assert report.documents["created"] == 0 and report.documents["updated"] == 0
    assert counts == {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in counts}
    assert opps(db)["01-readyly"]["stage"] == "applied"
    assert db.execute("SELECT status FROM needs_prerit WHERE kind='confirm_legacy'").fetchone()[0] == "done"


@needs_src
def test_items_include_teep_once():
    items = load_items(SRC)
    assert len(items) == 11 and sum(i["id"] == TEEP_ID for i in items) == 1


@needs_src
def test_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HQ_OFFLINE", "1")
    assert main(["--src", str(SRC), "--db", str(tmp_path / "cli.db"), "--offline"]) == 0
    out = capsys.readouterr().out
    assert "11 new" in out and "Readyly" in out and "₹25,000" in out and "(hours unknown)" in out
    assert (tmp_path / "artifacts" / "legacy" / "01-readyly" / "Prerit_Sangwan_Resume.pdf").exists()


@needs_src
def test_bootstrap_imports_legacy_once(hq_env):
    from hq.db.seed import seed_all
    from hq.db.conn import tx
    from hq.util.bootstrap import import_legacy_once

    conn = connect(hq_env.db)
    migrate(conn)
    with tx(conn):
        seed_all(conn)
    try:
        assert import_legacy_once(conn, SRC) == 11
        frozen = conn.execute("SELECT COUNT(*) FROM applications WHERE status='historical_frozen'").fetchone()[0]
        assert frozen == 10
        # second start: already there, nothing re-imported or overwritten
        conn.execute("UPDATE opportunities SET stage_reason='edited by Prerit' WHERE canonical_key='legacy:01-readyly'")
        assert import_legacy_once(conn, SRC) == 0
        assert conn.execute("SELECT stage_reason FROM opportunities WHERE canonical_key='legacy:01-readyly'"
                            ).fetchone()[0] == "edited by Prerit"
    finally:
        conn.close()


def test_bootstrap_skips_missing_legacy_folder(hq_env, tmp_path):
    from hq.util.bootstrap import import_legacy_once

    conn = connect(hq_env.db)
    migrate(conn)
    try:
        assert import_legacy_once(conn, tmp_path / "nope") == 0
    finally:
        conn.close()
