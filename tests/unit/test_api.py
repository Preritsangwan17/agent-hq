"""REST shapes (CONTRACT §5), stage override semantics, control/settings/needs/agents routes, SSE generator."""
from __future__ import annotations

import asyncio

from conftest import MUTATE, write_agent

from hq.agents.registry import Registry
from hq.api.stream import event_stream
from hq.db import repo
from hq.db.conn import tx
from hq.sim.pool import ROLES_BY_KEY, compute_pay

AGENT_KEYS = {"id", "name", "avatar", "color", "role", "adapter", "model", "capabilities", "cost_tier", "concurrency",
              "schedule", "enabled", "paused", "status", "builtin", "side_effects", "tasks_today", "errors_today",
              "tokens_today", "restarts", "last_error", "live", "description", "probation_runs_left"}
LIVE_KEYS = {"agent_id", "now_line", "progress", "current_task_id", "opportunity_id", "model_id", "tok_s",
             "heartbeat_at", "updated_at"}
EVENT_KEYS = {"id", "ts", "type", "level", "agent_id", "opportunity_id", "task_id", "message", "data"}
PAY_KEYS = {"raw", "status", "min", "max", "currency", "period", "monthly_inr_min", "monthly_inr_mid",
            "monthly_inr_max", "hourly_inr_min", "hourly_inr_max", "fx_rate", "fx_date", "living_cost_monthly_inr",
            "living_cost_basis", "living_cost_confidence", "ratio", "benefits"}
OPP_KEYS = {"id", "company_name", "title", "kind", "role_type", "city", "country_iso2", "lat", "lon", "work_mode",
            "stage", "stage_reason", "is_simulated", "fit_score", "eligibility_status", "scam_status", "deadline_at",
            "deadline_confidence", "pay", "url", "apply_channel", "source_label", "active_agent_id", "needs_prerit",
            "updated_at", "first_seen_at"}
DETAIL_EXTRA = {"summary", "notes_unverified", "applications", "documents", "timeline", "gates",
                "eligibility_checks", "needs",
                # phase (c): the evidence behind every verdict
                "description_available", "location_raw", "apply_url", "automation", "posted_at", "fit_breakdown",
                "benefits", "eligibility_confidence", "parse", "requirements", "job_quotes", "scam_checks", "sources",
                "runs", "document_sentences"}
NEED_KEYS = {"id", "opportunity_id", "kind", "title", "instructions_md", "answers", "files", "direct_url", "priority",
             "due_at", "est_minutes", "status", "created_at"}
STATS_KEYS = {"found", "verified", "drafted", "applied", "replies", "interviews", "offers", "rejected", "filtered",
              "success_rate", "needs_open", "cloud_cost_today_usd", "cloud_budget_usd", "cloud_calls_today",
              "local_tokens_today", "pay", "by_stage", "sim"}
SNAPSHOT_KEYS = {"settings", "agents", "opportunities", "events", "stats", "needs", "server_time", "last_event_id",
                 "notifications_unacked"}


def seed_opp(conn, key: str = "quillfeather-nlp", stage: str = "found", **extra) -> str:
    role = ROLES_BY_KEY[key]
    pay = compute_pay(role)
    values = {"canonical_key": f"sim:{key}:{abs(hash((key, stage, str(extra)))) % 99999}",
              "company_name": role.company, "title": role.title, "kind": role.kind, "role_type": role.role_type,
              "city": "Bengaluru", "country_iso2": "IN", "lat": 12.97, "lon": 77.59, "work_mode": role.work_mode,
              "url": f"https://careers.{role.slug}.example/jobs/1", "apply_channel": role.channel,
              "apply_email": role.apply_email, "stage": stage, "source_label": "test (sim)",
              **{k: v for k, v in pay.items() if k != "hours_per_week"}, **extra}
    with tx(conn):
        return repo.insert_opportunity(conn, values, is_simulated=True)


def test_snapshot_shape(authed, team, db):
    Registry(team, db).scan()
    seed_opp(db)
    snap = authed.get("/api/snapshot").json()
    assert set(snap) == SNAPSHOT_KEYS
    assert [a["id"] for a in snap["agents"]] == ["scout", "verifier", "writer", "factchecker", "reviewer", "resume",
                                                 "applicant", "inbox", "followup", "strategist"]
    for agent in snap["agents"]:
        assert set(agent) == AGENT_KEYS
        assert set(agent["live"]) == LIVE_KEYS
        assert agent["status"] == "offline"  # no worker heartbeat yet
    applicant = next(a for a in snap["agents"] if a["id"] == "applicant")
    assert applicant["side_effects"] == ["apply.email_send", "apply.ats_submit"]
    assert set(snap["stats"]) == STATS_KEYS
    assert snap["settings"]["mode"] == "dry_run" and snap["settings"]["sim_speed"] == 1.0
    assert snap["last_event_id"] == max(e["id"] for e in snap["events"])
    assert all(set(e) == EVENT_KEYS for e in snap["events"])
    opp = snap["opportunities"][0]
    assert set(opp) == OPP_KEYS and set(opp["pay"]) == PAY_KEYS
    assert opp["is_simulated"] is True and opp["pay"]["monthly_inr_min"] == 35000
    assert opp["pay"]["ratio"] == 1.4 and opp["pay"]["benefits"] == {}


def test_opportunity_list_detail_and_filters(authed, db):
    a = seed_opp(db, "quillfeather-nlp")
    seed_opp(db, "hoshizora-vurp", stage="verified")
    items = authed.get("/api/opportunities").json()["items"]
    assert len(items) == 2
    assert [o["id"] for o in authed.get("/api/opportunities?stage=found").json()["items"]] == [a]
    assert len(authed.get("/api/opportunities?q=Hoshizora").json()["items"]) == 1
    assert authed.get("/api/opportunities?sim=0").json()["items"] == []
    funded = next(o for o in items if o["company_name"].startswith("Hoshizora"))
    assert funded["pay"]["benefits"]["housing"] and funded["pay"]["benefits"]["allowance_inr"] == 88500
    detail = authed.get(f"/api/opportunities/{a}").json()
    assert set(detail) == OPP_KEYS | DETAIL_EXTRA
    assert authed.get("/api/opportunities/nope").status_code == 404


def test_hourly_unknown_hours_is_variable(authed, db):
    oid = seed_opp(db, "juniper-llm-eval")
    pay = authed.get(f"/api/opportunities/{oid}").json()["pay"]
    assert pay["status"] == "variable" and pay["monthly_inr_min"] is None and pay["ratio"] is None
    assert pay["hourly_inr_min"] == 2200 and pay["hourly_inr_max"] == 3080


def test_stage_override_is_audited_and_creates_no_tasks(authed, db):
    from hq.worker import queue

    oid = seed_opp(db)
    with tx(db):
        queued = queue.enqueue(db, "verify.link", opportunity_id=oid)
    tasks_before = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    r = authed.patch(f"/api/opportunities/{oid}/stage", json={"stage": "applied", "reason": "sent it myself"},
                     headers=MUTATE)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == OPP_KEYS and body["stage"] == "applied" and body["stage_reason"] == "sent it myself"
    assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == tasks_before  # nothing new
    assert db.execute("SELECT status FROM tasks WHERE id=?", (queued,)).fetchone()[0] == "cancelled"
    row = db.execute("SELECT stage_override FROM opportunities WHERE id=?", (oid,)).fetchone()
    assert row[0] == 1
    audit = db.execute("SELECT actor, action, before_json, after_json FROM audit_log WHERE target=?", (oid,)).fetchone()
    assert audit["actor"] == "prerit" and audit["action"] == "opp.stage_override" and '"found"' in audit["before_json"]
    ev = db.execute("SELECT data_json FROM events WHERE type='opp.stage' AND opportunity_id=?", (oid,)).fetchone()
    assert '"override":true' in ev[0]
    assert db.execute("SELECT COUNT(*) FROM mock_mailbox").fetchone()[0] == 0
    assert authed.patch(f"/api/opportunities/{oid}/stage", json={"stage": "bogus"}, headers=MUTATE).status_code == 400


def test_stats_counts_and_pay(authed, db):
    seed_opp(db, "quillfeather-nlp", stage="applied")
    seed_opp(db, "nimbus-ml-intern", stage="interview")
    seed_opp(db, "saffron-bi", stage="filtered")
    s = authed.get("/api/stats").json()
    assert set(s) == STATS_KEYS
    assert (s["found"], s["applied"], s["interviews"], s["filtered"]) == (3, 2, 1, 1)
    assert s["success_rate"] == 0.5
    assert s["pay"]["median_applied_inr"] == 37500 and s["pay"]["pipeline_max_inr"] == 40000
    assert s["by_stage"] == {"applied": 1, "interview": 1, "filtered": 1}


def test_control_pause_resume_freeze(authed, db):
    assert authed.post("/api/control/pause-all", headers=MUTATE).json() == {"paused": True}  # body optional
    assert authed.post("/api/control/pause-all", json={"reason": "lunch"}, headers=MUTATE).json() == {"paused": True}
    assert authed.get("/api/settings").json()["settings"]["global_pause"] is True
    assert authed.post("/api/control/resume-all", json={"confirm": "yes"}, headers=MUTATE).status_code == 400
    assert authed.post("/api/control/resume-all", json={"confirm": "RESUME"}, headers=MUTATE).json() == {"paused": False}
    assert authed.post("/api/control/freeze-outbound", json={"on": True}, headers=MUTATE).json() == {
        "freeze_outbound": True}
    kinds = [r[0] for r in db.execute("SELECT kind FROM commands ORDER BY ts, rowid")]
    assert kinds == ["pause_all", "pause_all", "resume_all", "freeze_outbound"]
    types = [r[0] for r in db.execute("SELECT type FROM events WHERE type LIKE 'control.%' ORDER BY id")]
    assert types == ["control.pause", "control.pause", "control.pause", "control.freeze"]


def test_settings_patch_whitelist(authed):
    r = authed.patch("/api/settings", json={"sim_speed": 2.5, "autonomy": "approve_first"}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["settings"]["sim_speed"] == 2.5
    assert authed.patch("/api/settings", json={"mode": "live"}, headers=MUTATE).status_code == 400
    assert authed.patch("/api/settings", json={"global_pause": True}, headers=MUTATE).status_code == 400
    assert authed.patch("/api/settings", json={"sim_speed": 9}, headers=MUTATE).status_code == 400
    assert authed.patch("/api/settings", json={"quiet_hours": {"enabled": True, "start": "25:00"}},
                        headers=MUTATE).status_code == 400
    ok = authed.patch("/api/settings", json={"quiet_hours": {"enabled": True}}, headers=MUTATE).json()
    assert ok["settings"]["quiet_hours"] == {"enabled": True, "start": "23:00", "end": "07:00"}


def test_needs_submit_form_done_marks_applied(authed, db):
    oid = seed_opp(db, "nimbus-ml-intern", stage="checked")
    with tx(db):
        app_id = "APP1"
        db.execute("INSERT INTO applications(id, opportunity_id, channel, status, mode, created_at, updated_at) "
                   "VALUES (?,?,?,?,?,?,?)", (app_id, oid, "ats_form", "needs_prerit", "dry_run", "t", "t"))
        nid = repo.insert_need(db, {"opportunity_id": oid, "application_id": app_id, "kind": "submit_form",
                                    "title": "Submit it", "answers_json": [{"label": "Name", "value": "P"}]})
    items = authed.get("/api/needs").json()["items"]
    assert len(items) == 1 and set(items[0]) >= NEED_KEYS and items[0]["answers"][0]["label"] == "Name"
    assert authed.get("/api/opportunities").json()["items"][0]["needs_prerit"] is True
    r = authed.patch(f"/api/needs/{nid}", json={"status": "done"}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert db.execute("SELECT stage FROM opportunities WHERE id=?", (oid,)).fetchone()[0] == "applied"
    assert db.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()[0] == "submitted"
    assert authed.get("/api/needs").json()["items"] == []
    snooze = authed.patch(f"/api/needs/{nid}", json={"status": "snoozed", "snooze_hours": 2}, headers=MUTATE).json()
    assert snooze["status"] == "snoozed" and snooze["snoozed_until"]


def test_agents_meta_create_patch_delete(authed, team, db, hq_env):
    Registry(team, db).scan()
    meta = authed.get("/api/agents/meta").json()
    assert "apply.email_send" in meta["reserved_side_effects"] and "sim" in meta["adapters"]
    assert any(c["id"] == "discover.ats" and c["schedulable"] for c in meta["capabilities"])
    new = {"id": "summarizer", "name": "Summarizer", "adapter": "sim", "capabilities": ["summarize"],
           "color": "#34D399", "avatar": "📝"}
    r = authed.post("/api/agents", json=new, headers=MUTATE)
    assert r.status_code == 201, r.text
    assert set(r.json()) == AGENT_KEYS and r.json()["builtin"] is False
    assert (hq_env.agents / "summarizer.yaml").exists()
    assert authed.post("/api/agents", json=new, headers=MUTATE).status_code == 409
    bad = {**new, "id": "sender", "capabilities": ["apply.email_send"]}
    assert authed.post("/api/agents", json=bad, headers=MUTATE).status_code == 400
    assert authed.post("/api/agents", json={**new, "id": "x1", "builtin": True}, headers=MUTATE).status_code == 400

    r = authed.patch("/api/agents/summarizer", json={"paused": True, "concurrency": 3}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["paused"] is True and r.json()["concurrency"] == 3
    assert "concurrency: 3" in (hq_env.agents / "summarizer.yaml").read_text()
    assert authed.patch("/api/agents/summarizer", json={"color": "blue"}, headers=MUTATE).status_code == 400
    assert authed.patch("/api/agents/summarizer", json={"hack": 1}, headers=MUTATE).status_code == 422

    assert authed.delete("/api/agents/scout", headers=MUTATE).status_code == 400  # built-in
    r = authed.patch("/api/agents/scout", json={"enabled": False}, headers=MUTATE)
    assert r.json()["enabled"] is False and r.json()["status"] == "disabled"
    assert authed.delete("/api/agents/summarizer", headers=MUTATE).json() == {"ok": True}
    assert (hq_env.agents / "summarizer.yaml.disabled").exists()


def test_script_agents_are_loopback_only(app, db):
    from fastapi.testclient import TestClient

    from hq.api import auth

    auth.set_passcode("lan-pass-99")
    with TestClient(app, base_url="http://localhost", client=("192.168.1.9", 5000)) as lan:
        assert lan.post("/api/auth/login", json={"passcode": "lan-pass-99"}, headers=MUTATE).status_code == 200
        r = lan.post("/api/agents", json={"id": "scripty", "name": "Scripty", "adapter": "script",
                                          "capabilities": ["summarize"]}, headers=MUTATE)
        assert r.status_code == 403


def test_sim_reset_purges_only_simulated(authed, db):
    sim = seed_opp(db)
    with tx(db):
        legacy = repo.insert_opportunity(db, {"canonical_key": "legacy:1", "company_name": "Real Co", "title": "Intern",
                                              "stage": "frozen"}, is_simulated=False)
        repo.insert_need(db, {"opportunity_id": sim, "kind": "decision", "title": "x"})
    r = authed.post("/api/sim/reset", headers=MUTATE)
    assert r.json() == {"ok": True, "purged": 1}
    ids = [row[0] for row in db.execute("SELECT id FROM opportunities")]
    assert ids == [legacy]
    assert db.execute("SELECT COUNT(*) FROM needs_prerit").fetchone()[0] == 0


def test_events_endpoint_filters(authed, db):
    with tx(db):
        for i in range(5):
            repo.emit(db, "log", f"line {i}", agent_id="scout" if i % 2 else "writer", level="info")
        repo.emit(db, "task.dead", "dead one", level="error")
    evs = authed.get("/api/events?limit=3").json()["events"]
    assert [e["message"] for e in evs][-1] == "dead one" and len(evs) == 3
    assert [e["id"] for e in evs] == sorted(e["id"] for e in evs)  # newest last
    assert len(authed.get("/api/events?agent=scout").json()["events"]) == 2
    assert authed.get("/api/events?level=error").json()["events"][0]["type"] == "task.dead"
    assert len(authed.get("/api/events?type=task.*").json()["events"]) == 1
    first = authed.get("/api/events?limit=500").json()["events"][0]["id"]
    after = authed.get(f"/api/events?after={first}&limit=2").json()["events"]
    assert [e["id"] for e in after] == [first + 1, first + 2]


def test_spa_placeholder_and_api_404(authed):
    r = authed.get("/pipeline")
    assert r.status_code == 200 and "npm run build" in r.text
    assert authed.get("/api/does-not-exist").status_code == 404


def test_spa_serves_dist_with_fallback(authed, hq_env):
    dist = hq_env.root / "web-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    assert authed.get("/o/123").text == "<html>app</html>"
    r = authed.get("/assets/app.js")
    assert r.text == "console.log(1)" and "immutable" in r.headers["cache-control"]
    assert authed.get("/../../etc/passwd").text == "<html>app</html>"


# ── SSE generator ────────────────────────────────────────────────────────────────────────────────────
async def _take(gen, n, timeout=3.0):
    out = []

    async def run():
        async for item in gen:
            out.append(item)
            if len(out) >= n:
                return

    await asyncio.wait_for(run(), timeout)
    return out


async def never_disconnected():
    return False


async def test_sse_replays_after_id_and_forwards_agent_live(db, hq_env):
    write_agent(hq_env.agents, "helper")
    Registry(hq_env.agents, db).scan()
    with tx(db):
        first = repo.emit(db, "log", "one")
        repo.emit(db, "log", "two")
    gen = event_stream(db, first - 1, never_disconnected, poll_s=0.02)
    items = await _take(gen, 2)
    assert [i["event"] for i in items] == ["log", "log"]
    assert items[0]["id"] == str(first) and '"message":"one"' in items[0]["data"]
    repo.set_live(db, "helper", now_line="Parsing Greenhouse board…", progress=0.5)
    live = await _take(gen, 1)
    assert live[0]["event"] == "agent.live" and "Parsing Greenhouse" in live[0]["data"] and "id" not in live[0]
    await gen.aclose()


async def test_sse_resync_when_gap_too_large(db):
    with tx(db):
        for i in range(520):
            repo.emit(db, "log", f"e{i}", level="debug")
    gen = event_stream(db, 1, never_disconnected, poll_s=0.02)
    first = await _take(gen, 1)
    assert first[0]["event"] == "resync"
    await gen.aclose()
    gen = event_stream(db, 10_000_000, never_disconnected, poll_s=0.02)
    assert (await _take(gen, 1))[0]["event"] == "resync"
    await gen.aclose()
