"""Migrations, settings seed/validation and repo helpers."""
from __future__ import annotations

import pytest

from hq.db import repo
from hq.db.conn import connect, tx
from hq.db.migrate import migrate
from hq.db.seed import DEFAULT_SETTINGS, SettingError, get_settings, seed_settings, set_settings, validate_patch


def test_migrations_idempotent_and_pragmas(db):
    assert migrate(db) == []
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    cols = {r["name"] for r in db.execute("PRAGMA table_info(agent_runs)")}
    assert {"input_json", "output_json"} <= cols
    versions = [r[0] for r in db.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions[:2] == [1, 2]


def test_seed_defaults_do_not_overwrite(db):
    assert get_settings(db) == DEFAULT_SETTINGS
    with tx(db):
        set_settings(db, {"sim_speed": 2.0})
        assert seed_settings(db) == []
    assert get_settings(db)["sim_speed"] == 2.0


@pytest.mark.parametrize("patch", [
    {}, {"mode": "live"}, {"global_pause": True}, {"worker_heartbeat_at": "x"}, {"sim_speed": 0.1},
    {"sim_speed": "fast"}, {"autonomy": "yolo"}, {"sim_enabled": 1}, {"quiet_hours": {"start": "7am"}},
    {"fit_draft_threshold": 101},
])
def test_validate_patch_rejects(patch):
    with pytest.raises(SettingError):
        validate_patch(patch)


def test_validate_patch_cleans():
    assert validate_patch({"fit_draft_threshold": 65.0, "sim_speed": 4}) == {"fit_draft_threshold": 65,
                                                                             "sim_speed": 4.0}


def test_events_newest_last_and_after(db):
    with tx(db):
        ids = [repo.emit(db, "log", f"m{i}", data={"i": i}) for i in range(10)]
    latest = repo.list_events(db, limit=3)
    assert [e["id"] for e in latest] == ids[-3:]
    assert latest[-1]["data"] == {"i": 9}
    assert [e["id"] for e in repo.list_events(db, after=ids[2], limit=2)] == ids[3:5]
    assert repo.last_event_id(db) == ids[-1]


def test_insert_opportunity_rejects_unknown_columns(db):
    with pytest.raises(ValueError):
        repo.insert_opportunity(db, {"canonical_key": "x", "company_name": "A", "title": "B", "evil": 1},
                                is_simulated=True)


def test_set_live_bumps_seq(db):
    now = "2026-09-26T00:00:00.000Z"
    db.execute("INSERT INTO agent_live(agent_id, updated_at) VALUES ('a', ?)", (now,))
    repo.set_live(db, "a", now_line="hello", progress=0.5)
    repo.set_live(db, "a", now_line="again")
    row = repo.live_row(db, "a")
    assert row["seq"] == 2 and row["now_line"] == "again"


def test_separate_connections_see_committed_writes(db):
    other = connect()
    with tx(db):
        repo.emit(db, "log", "cross-process")
    assert repo.list_events(other, limit=1)[0]["message"] == "cross-process"
    other.close()


# ── schema drift repair ("no such table: claude_usage") ──────────────────────────────────────────────
def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_repair_restores_missing_table_column_and_index(db):
    from hq.db import serializers
    from hq.db.migrate import repair_schema

    db.execute("DROP TABLE claude_usage")
    db.execute("DROP INDEX idx_needs_kind")
    db.execute("ALTER TABLE needs_prerit DROP COLUMN payload_json")
    with pytest.raises(Exception, match="no such table: claude_usage"):
        serializers.snapshot(db)
    assert migrate(db) == []                      # every numbered migration is already recorded …
    assert "claude_usage" in _tables(db)          # … and the repair put the missing pieces back
    assert "payload_json" in _cols(db, "needs_prerit")
    assert db.execute("SELECT 1 FROM sqlite_master WHERE name='idx_needs_kind'").fetchone()
    assert serializers.snapshot(db)["stats"]["claude_calls_today"] == 0
    assert repair_schema(db) == []               # idempotent


def test_repair_heals_an_early_draft_database(tmp_path):
    """A database from before the schema was final: a few tables, fewer columns, but marked fully migrated."""
    from hq.db import serializers
    from hq.db.seed import seed_all
    from hq.db.migrate import _files, reference_schema

    conn = connect(tmp_path / "draft.db")
    conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for p in _files():
        conn.execute("INSERT INTO schema_migrations VALUES (?, 'draft')", (int(p.name[:4]),))
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE opportunities (id TEXT PRIMARY KEY, canonical_key TEXT NOT NULL, company_name TEXT, "
                 "title TEXT, stage TEXT NOT NULL DEFAULT 'found', first_seen_at TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO settings VALUES ('mode', '\"dry_run\"', '2026-01-01T00:00:00Z')")
    conn.execute("INSERT INTO opportunities VALUES ('o1', 'k1', 'Old Co', 'ML Intern', 'found', "
                 "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')")
    migrate(conn)
    ref = reference_schema()
    want = {r[0] for r in ref.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert want <= _tables(conn)
    for table in ("settings", "opportunities"):
        assert {r[1] for r in ref.execute(f"PRAGMA table_info({table})")} <= _cols(conn, table)
    row = conn.execute("SELECT is_simulated, job_quotes_json, updated_by FROM opportunities o, settings s "
                       "WHERE o.id='o1' AND s.key='mode'").fetchone()
    assert tuple(row) == (0, "[]", "system")   # added NOT NULL columns got their defaults on old rows
    with tx(conn):
        seed_all(conn)
    snap = serializers.snapshot(conn)
    assert [o["company_name"] for o in snap["opportunities"]] == ["Old Co"]
    conn.close()


def test_migration_already_partly_present_is_tolerated(db):
    """The reverse drift: 0005's columns exist but the version wasn't recorded (e.g. a crash in between)."""
    db.execute("DELETE FROM schema_migrations WHERE version=5")
    assert migrate(db) == [5]
    assert db.execute("SELECT 1 FROM schema_migrations WHERE version=5").fetchone()


def test_snapshot_api_works_on_a_drifted_database(hq_env, db):
    from fastapi.testclient import TestClient

    from hq.api.app import create_app
    from tests.conftest import MUTATE

    db.execute("DROP TABLE claude_usage")
    with TestClient(create_app(), base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        assert c.post("/api/auth/setup", json={"passcode": "correct-horse-42"}, headers=MUTATE).status_code == 200
        assert c.get("/api/snapshot").status_code == 200
        assert c.get("/api/analytics").status_code == 200
