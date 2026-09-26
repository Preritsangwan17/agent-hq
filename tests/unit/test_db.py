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
