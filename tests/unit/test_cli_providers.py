"""Subscription CLI providers: the Claude CLI and ChatGPT's Codex CLI (fake executables), their usage-window limits,
the provider order (subscriptions before paid Grok), HQ's per-window cap and the usage page's provider rows."""
from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from hq.db.conn import tx
from hq.db.seed import get_settings, set_settings
from hq.llm import cloud
from hq.llm.claude_cli import ClaudeCliRunner
from hq.llm.codex_cli import CodexCliRunner
from hq.llm.errors import CloudBadOutput, CloudRateLimited, CloudResult, CloudUnavailable
from hq.llm.router import Router
from hq.worker import budget
from tests.conftest import MUTATE

SCHEMA = {"type": "object", "required": ["verdict"], "properties": {"verdict": {"enum": ["yes", "no"]}}}

CLAUDE = r'''#!{python}
import json, os, sys
state = os.path.dirname(os.path.abspath(__file__))
mode = open(os.path.join(state, "mode")).read().strip()
open(os.path.join(state, "argv.json"), "w").write(json.dumps(sys.argv[1:]))
if sys.argv[1:3] == ["auth", "status"]:
    print(json.dumps({{"loggedIn": mode != "logged_out"}}))
    sys.exit(0)
open(os.path.join(state, "stdin.txt"), "w").write(sys.stdin.read())
base = {{"type": "result", "total_cost_usd": 0.0421, "usage": {{"input_tokens": 900, "output_tokens": 40}}}}
if mode == "ok":
    print(json.dumps({{**base, "subtype": "success", "is_error": False, "structured_output": {{"verdict": "yes"}}}}))
elif mode == "bad_output":
    print(json.dumps({{**base, "subtype": "success", "is_error": False, "structured_output": {{"verdict": "maybe"}}}}))
elif mode == "limit":
    print(json.dumps({{**base, "subtype": "success", "is_error": True,
                      "result": "Claude usage limit reached. Your limit will reset in 3 hours."}}))
'''

CODEX = r'''#!{python}
import json, os, sys
state = os.path.dirname(os.path.abspath(__file__))
mode = open(os.path.join(state, "mode")).read().strip()
args = sys.argv[1:]
open(os.path.join(state, "argv.json"), "w").write(json.dumps(args))
if args[:2] == ["login", "status"]:
    print("Not logged in" if mode == "logged_out" else "Logged in using ChatGPT")
    sys.exit(1 if mode == "logged_out" else 0)
open(os.path.join(state, "stdin.txt"), "w").write(sys.stdin.read())
if mode == "limit":
    print(json.dumps({{"type": "error", "message": "You've hit your usage limit. Try again in 2 hours."}}))
    sys.exit(1)
if mode == "no_schema_flag" and "--output-schema" in args:
    sys.stderr.write("error: unexpected argument '--output-schema' found")
    sys.exit(2)
out = args[args.index("--output-last-message") + 1]
answer = json.dumps({{"verdict": "no"}}) if mode != "bad" else "sorry, no JSON"
print(json.dumps({{"type": "thread.started", "thread_id": "t1"}}))
print(json.dumps({{"id": "0", "msg": {{"type": "token_count", "info": {{"last_token_usage": {{"input_tokens": 700,
      "output_tokens": 30}}}}, "rate_limits": {{"primary": {{"used_percent": 42.0, "window_minutes": 300,
      "resets_in_seconds": 3600}}, "secondary": {{"used_percent": 10.0, "window_minutes": 10080}}}}}}}}))
print(json.dumps({{"type": "item.completed", "item": {{"id": "i1", "type": "agent_message", "text": answer}}}}))
print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 700, "output_tokens": 30}}}}))
open(out, "w").write(answer)
'''


def _shim(tmp_path: Path, name: str, body: str) -> Path:
    d = tmp_path / f"shim_{name}"
    d.mkdir()
    exe = d / name
    exe.write_text(body.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    (d / "mode").write_text("ok")
    return d


@pytest.fixture
def claude_shim(tmp_path, monkeypatch, hq_env) -> Path:
    d = _shim(tmp_path, "claude", CLAUDE)
    monkeypatch.setenv("HQ_CLAUDE_BIN", str(d / "claude"))
    return d


@pytest.fixture
def codex_shim(tmp_path, monkeypatch, hq_env) -> Path:
    d = _shim(tmp_path, "codex", CODEX)
    monkeypatch.setenv("HQ_CODEX_BIN", str(d / "codex"))
    return d


# ── Claude CLI ───────────────────────────────────────────────────────────────────────────────────────
async def test_claude_cli_runs_isolated_and_costs_nothing_from_the_grok_budget(db, claude_shim, monkeypatch):
    monkeypatch.setenv("HQ_SESSION_SECRET", "s" * 64)
    r = ClaudeCliRunner(db)
    assert await r.available() is True
    res = await r.run("Check this. Secret: " + "s" * 64, schema=SCHEMA, system_prompt="You check.", model="claude:sonnet")
    assert res.output == {"verdict": "yes"} and res.cost_usd == 0.0 and res.cost_source == "subscription"
    assert res.raw["notional_usd"] == pytest.approx(0.0421) and res.model == "claude:sonnet"
    argv = json.loads((claude_shim / "argv.json").read_text())
    assert argv[argv.index("--tools") + 1] == "" and "--no-session-persistence" in argv
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert not any("dangerously" in a for a in argv)
    assert "s" * 64 not in (claude_shim / "stdin.txt").read_text()


async def test_claude_cli_usage_limit_pauses_the_provider_until_reset(db, claude_shim):
    (claude_shim / "mode").write_text("limit")
    r = ClaudeCliRunner(db)
    assert await r.available()
    with pytest.raises(CloudRateLimited):
        await r.run("x", schema=SCHEMA, system_prompt="s")
    st = r.state(get_settings(db))["limits"]
    assert st["limited_until"] and "usage limit" in st["limit_message"] and st["source"].startswith("reported")
    assert await r.available() is False and "resets" in r.reason
    (claude_shim / "mode").write_text("bad_output")
    r2 = ClaudeCliRunner(db)
    with pytest.raises(CloudBadOutput):
        await r2.run("x", schema=SCHEMA, system_prompt="s")


async def test_claude_cli_logged_out_asks_only_when_switched_on(db, claude_shim):
    (claude_shim / "mode").write_text("logged_out")
    quiet = ClaudeCliRunner(db)
    assert not await quiet.available()
    assert not db.execute("SELECT 1 FROM needs_prerit WHERE title LIKE 'Log in to the Claude CLI'").fetchone()
    loud = ClaudeCliRunner(db)
    loud.nag = True
    assert not await loud.available()
    assert db.execute("SELECT 1 FROM needs_prerit WHERE title LIKE 'Log in to the Claude CLI'").fetchone()


# ── Codex CLI ────────────────────────────────────────────────────────────────────────────────────────
async def test_codex_cli_answers_with_schema_and_reports_its_usage_windows(db, codex_shim):
    r = CodexCliRunner(db)
    assert await r.available() is True
    res = await r.run("Decide.", schema=SCHEMA, system_prompt="You decide.", model="codex:default")
    assert res.output == {"verdict": "no"} and res.cost_usd == 0.0 and res.input_tokens == 700
    argv = json.loads((codex_shim / "argv.json").read_text())
    assert argv[:2] == ["exec", "--json"] and argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--output-schema" in argv and "-m" not in argv and argv[-1] == "-"
    assert "You decide." in (codex_shim / "stdin.txt").read_text()
    windows = {w["name"]: w for w in r.state(get_settings(db))["limits"]["windows"]}
    assert windows["5-hour window"]["used_percent"] == 42.0 and windows["5-hour window"]["left_percent"] == 58.0
    assert windows["5-hour window"]["resets_at"] and windows["weekly window"]["used_percent"] == 10.0


async def test_codex_cli_limit_login_and_old_versions(db, codex_shim):
    (codex_shim / "mode").write_text("limit")
    r = CodexCliRunner(db)
    with pytest.raises(CloudRateLimited):
        await r.run("x", schema=SCHEMA, system_prompt="s")
    assert r.limits.blocked() and not await r.available()
    (codex_shim / "mode").write_text("no_schema_flag")
    old = CodexCliRunner(db)
    res = await old.run("x", schema=SCHEMA, system_prompt="s")
    assert res.output == {"verdict": "no"} and old.schema_flag is False
    (codex_shim / "mode").write_text("logged_out")
    assert not await CodexCliRunner(db).available()


# ── provider order, fallback, window cap ─────────────────────────────────────────────────────────────
class Fake:
    def __init__(self, name: str, *, fail: Exception | None = None):
        self.name, self.fail, self.calls, self.reason, self.nag = name, fail, [], None, False
        self.limits = None

    async def available(self, force: bool = False) -> bool:
        return True

    async def run(self, prompt, *, schema, system_prompt, model=None, **kw) -> CloudResult:
        self.calls.append(model)
        if self.fail:
            raise self.fail
        paid = self.name == "xai"
        return CloudResult({"verdict": "yes"}, 0.01 if paid else 0.0, 100, 10, None, 5.0, model, "success",
                           cost_source="reported" if paid else "subscription", raw={"notional_usd": 0.02})

    def state(self, settings):
        return {"available": True, "reason": None, "installed": True}


def _runner(db, **fails):
    fakes = {p: Fake(p, fail=fails.get(p)) for p in ("xai", "claude", "codex")}
    return cloud.CloudRunner(db, xai=fakes["xai"], claude=fakes["claude"], codex=fakes["codex"]), fakes


async def test_router_uses_subscriptions_first_and_falls_through_on_limits(db):
    with tx(db):
        set_settings(db, {"claude_cli_enabled": True, "codex_cli_enabled": True})
    runner, fakes = _runner(db, claude=CloudRateLimited("usage limit reached"))
    res = await Router(db, None, runner).route("summarizer", [{"role": "user", "content": "u"}], SCHEMA)
    assert res.model_id == "codex:default" and fakes["claude"].calls == ["claude:sonnet"] and not fakes["xai"].calls
    rows = db.execute("SELECT provider, cost_usd_est, subtype FROM cloud_usage WHERE subtype!='released'").fetchall()
    assert [(r["provider"], r["subtype"]) for r in rows] == [("codex", "success")] and rows[0]["cost_usd_est"] == 0
    assert budget.usage_today(db)["calls"] == 0                  # subscriptions never touch the Grok $ limit


async def test_hq_window_cap_hands_over_to_the_next_provider(db):
    with tx(db):
        set_settings(db, {"claude_cli_enabled": True, "claude_window_calls": 1})
    runner, fakes = _runner(db)
    msgs = [{"role": "user", "content": "u"}]
    first = await Router(db, None, runner).route("summarizer", msgs, SCHEMA)
    second = await Router(db, None, runner).route("summarizer", msgs, SCHEMA)
    assert first.model_id == "claude:sonnet" and second.model_id == "xai:grok-4-fast"
    assert budget.usage_today(db)["calls"] == 1


def test_usage_page_shows_each_provider_with_exact_and_reported_figures(authed, db):
    with tx(db):
        set_settings(db, {"codex_cli_enabled": True, "cloud_state": {"providers": {"codex": {
            "available": True, "installed": True, "limits": {
                "source": "reported by the Codex CLI", "windows": [{"name": "5-hour window", "used_percent": 42.0,
                                                                    "left_percent": 58.0}],
                "windows_at": "2026-09-26T10:00:00Z"}}}}})
    r = budget.reserve(db, "escalation.writer", provider="codex")
    budget.commit(db, r, cost_usd=0.0, model="codex:default", cost_source="subscription", notional_usd=0.02)
    u = authed.get("/api/usage").json()
    rows = {p["provider"]: p for p in u["providers"]}
    assert list(rows) == ["claude", "codex", "xai"]
    codex = rows["codex"]
    assert codex["in_use"] and codex["hq_window"] == {**codex["hq_window"], "cap": 30, "used": 1, "left": 29}
    assert codex["hq_window"]["is_estimate"] is False and codex["reported"]["windows"][0]["left_percent"] == 58.0
    assert not rows["claude"]["in_use"] and u["today"]["calls"] == 0          # Grok figures stay Grok-only
    assert authed.patch("/api/settings", json={"claude_cli_enabled": True}, headers=MUTATE).status_code == 200
    assert authed.patch("/api/settings", json={"codex_model": "gpt-5-codex"}, headers=MUTATE).status_code == 200
