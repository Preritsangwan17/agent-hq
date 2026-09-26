"""Agent YAML schema, registry sync, invalid-config handling and watchfiles hot reload."""
from __future__ import annotations

import asyncio
import time

import pytest
import yaml
from conftest import REPO_AGENTS, write_agent
from pydantic import ValidationError

from hq.agents.registry import AgentFileError, Registry, parse_agent_file
from hq.agents.schema import RESERVED_SIDE_EFFECTS, AgentConfig


def base(**kw):
    cfg = {"id": "helper", "name": "Helper", "adapter": "sim", "capabilities": ["summarize"]}
    cfg.update(kw)
    return cfg


def test_starting_team_is_valid_and_matches_contract():
    expected = {
        "scout": ("#22D3EE", ["discover.ats", "discover.program_page", "parse.job"]),
        "verifier": ("#2DD4BF", ["verify.link", "verify.deadline", "verify.eligibility", "verify.pay", "verify.scam",
                                 "score.fit"]),
        "writer": ("#A78BFA", ["draft.cover_letter"]),
        "factchecker": ("#F59E0B", ["factcheck.deterministic", "factcheck.sentence", "check.quality"]),
        "reviewer": ("#FB7185", ["factcheck.signoff"]),
        "resume": ("#60A5FA", ["build.resume"]),
        "applicant": ("#F472B6", ["apply.email_send", "apply.manual_pack"]),
        "inbox": ("#A3E635", ["inbox.poll", "inbox.classify"]),
        "followup": ("#FB923C", ["followup.schedule"]),
        "strategist": ("#E879F9", ["strategy.daily_review"]),
    }
    found = {}
    for path in REPO_AGENTS.glob("*.yaml"):
        cfg, _ = parse_agent_file(path)
        found[cfg.id] = (cfg.color, cfg.capabilities)
        assert cfg.builtin and cfg.adapter == "sim"
    assert found == expected


def test_reserved_side_effects_rejected_for_non_builtin():
    for cap in RESERVED_SIDE_EFFECTS:
        with pytest.raises(ValidationError, match="reserved side-effect"):
            AgentConfig.model_validate(base(capabilities=[cap]))
    with pytest.raises(ValidationError):  # builtin flag alone is not enough: must be one of the owners
        AgentConfig.model_validate(base(builtin=True, capabilities=["apply.email_send"]))
    ok = AgentConfig.model_validate(base(id="applicant", builtin=True, capabilities=["apply.email_send"]))
    assert ok.side_effects == ["apply.email_send"]


@pytest.mark.parametrize("bad", [
    {"id": "Bad Id"}, {"color": "red"}, {"capabilities": []}, {"capabilities": ["hack.planet"]},
    {"adapter": "telnet"}, {"schedule": {"mode": "cron", "cron": "not a cron"}},
    {"schedule": {"mode": "interval"}}, {"unknown_key": 1}, {"model": "gpt-magic"}, {"concurrency": 0},
    {"schedule": {"mode": "interval", "minutes": 5}},  # scheduled but nothing schedulable
])
def test_schema_rejects_bad_configs(bad):
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(base(**bad))


def test_file_name_must_match_id(hq_env):
    path = hq_env.agents / "other.yaml"
    path.write_text(yaml.safe_dump(base()))
    with pytest.raises(AgentFileError, match="must match"):
        parse_agent_file(path)


def test_scan_adds_updates_and_removes(hq_env, db):
    reg = Registry(hq_env.agents, db)
    write_agent(hq_env.agents, "helper")
    assert reg.scan() == [("helper", "added")]
    assert reg.scan() == []  # unchanged file → no event
    write_agent(hq_env.agents, "helper", name="Helper Two")
    assert reg.scan() == [("helper", "updated")]
    (hq_env.agents / "helper.yaml").rename(hq_env.agents / "helper.yaml.disabled")
    assert reg.scan(running={"helper": 1}) == []  # drains first
    assert "helper" in reg.draining
    assert reg.scan(running={}) == [("helper", "removed")]
    types = [r[0] for r in db.execute("SELECT type FROM events WHERE type LIKE 'agent.%' ORDER BY id")]
    assert types == ["agent.added", "agent.updated", "agent.removed"]
    assert db.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 0


def test_invalid_yaml_keeps_last_good_config(hq_env, db):
    reg = Registry(hq_env.agents, db)
    write_agent(hq_env.agents, "helper", name="Good")
    reg.scan()
    (hq_env.agents / "helper.yaml").write_text("id: helper\nname: [broken\n")
    assert reg.scan() == [("helper", "error")]
    assert reg.configs["helper"].name == "Good"
    assert reg.scan() == []  # same broken content → no repeated error event
    row = db.execute("SELECT config_json FROM agents WHERE id='helper'").fetchone()
    assert '"name":"Good"' in row[0]
    err = db.execute("SELECT level, message FROM events WHERE type='error'").fetchone()
    assert err["level"] == "error" and "keeping the last good config" in err["message"]
    # a restarted registry (worker restart) still keeps the last good config from the DB
    assert Registry(hq_env.agents, db).configs["helper"].name == "Good"


def test_reserved_cap_in_yaml_is_rejected_by_loader(hq_env, db):
    write_agent(hq_env.agents, "sneaky", capabilities=["apply.email_send"])
    changes = Registry(hq_env.agents, db).scan()
    assert changes == [("sneaky", "error")]
    assert db.execute("SELECT COUNT(*) FROM agents WHERE id='sneaky'").fetchone()[0] == 0


def test_yaml_enabled_edit_wins_but_db_pause_persists(hq_env, db):
    reg = Registry(hq_env.agents, db)
    write_agent(hq_env.agents, "helper")
    reg.scan()
    db.execute("UPDATE agents SET paused=1 WHERE id='helper'")
    write_agent(hq_env.agents, "helper", enabled=False)
    reg.scan()
    row = db.execute("SELECT enabled, paused FROM agents WHERE id='helper'").fetchone()
    assert (row["enabled"], row["paused"]) == (0, 1)


async def test_hot_reload_adds_agent_within_three_seconds(hq_env, db):
    reg = Registry(hq_env.agents, db)
    reg.scan()
    stop = asyncio.Event()
    fired = asyncio.Event()

    def on_change():
        if reg.scan():
            fired.set()

    watcher = asyncio.create_task(reg.watch(on_change, stop))
    await asyncio.sleep(0.5)  # let the watcher attach
    t0 = time.monotonic()
    write_agent(hq_env.agents, "newbie", name="Newbie")
    await asyncio.wait_for(fired.wait(), timeout=5)
    elapsed = time.monotonic() - t0
    stop.set()
    await asyncio.wait_for(watcher, timeout=5)
    assert elapsed < 3.0
    assert db.execute("SELECT type FROM events WHERE type='agent.added' AND agent_id='newbie'").fetchone()
