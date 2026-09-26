"""Claude runner (fake `claude` shim) and the router's escalation ladder (local → different local → Claude)."""
from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from hq.adapters.base import Deferred
from hq.db.conn import tx
from hq.llm import client as llm_client
from hq.llm.claude import (
    ClaudeBadOutput,
    ClaudeBudgetExceeded,
    ClaudeError,
    ClaudeRunner,
    ClaudeUnavailable,
    LOGIN_NEED_TITLE,
)
from hq.llm.router import EscalationExhausted, Router
from hq.models import roles
from hq.models.discovery.base import ModelInfo, upsert_models

SCHEMA = {"type": "object", "required": ["verdict"], "properties": {"verdict": {"enum": ["yes", "no"]},
                                                                  "confidence": {"type": "number"}}}

SHIM = r'''#!{python}
import json, os, sys
state = os.path.dirname(os.path.abspath(__file__))
mode = open(os.path.join(state, "mode")).read().strip()
open(os.path.join(state, "argv.json"), "w").write(json.dumps(sys.argv[1:]))
if sys.argv[1:3] == ["auth", "status"]:
    print(json.dumps({{"loggedIn": mode != "logged_out"}}))
    sys.exit(0)
prompt = sys.stdin.read()
open(os.path.join(state, "stdin.txt"), "w").write(prompt)
base = {{"type": "result", "total_cost_usd": 0.0421, "usage": {{"input_tokens": 900, "output_tokens": 40}}}}
if mode == "ok":
    print(json.dumps({{**base, "subtype": "success", "is_error": False, "structured_output": {{"verdict": "yes"}}}}))
elif mode == "bad_output":
    print(json.dumps({{**base, "subtype": "success", "is_error": False, "structured_output": {{"verdict": "maybe"}}}}))
elif mode == "budget":
    print(json.dumps({{**base, "subtype": "error_max_budget_usd", "is_error": True, "result": "budget"}}))
elif mode == "logged_out":
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": True,
                      "result": "Invalid API key · Please run /login"}}))
elif mode == "is_error":
    print(json.dumps({{**base, "subtype": "error_during_execution", "is_error": True, "result": "boom"}}))
'''


@pytest.fixture
def shim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hq_env) -> Path:
    d = tmp_path / "shim"
    d.mkdir()
    exe = d / "claude"
    exe.write_text(SHIM.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    (d / "mode").write_text("ok")
    monkeypatch.setenv("SHIM_DIR", str(d))
    monkeypatch.setenv("HQ_CLAUDE_BIN", str(exe))
    monkeypatch.setenv("PATH", f"{d}:{Path(sys.executable).parent}:/usr/bin:/bin")
    return d


def _mode(shim: Path, mode: str) -> None:
    (shim / "mode").write_text(mode)


async def test_claude_runner_uses_isolated_flags_and_accepts_valid_output(db, shim, monkeypatch):
    monkeypatch.setenv("HQ_SESSION_SECRET", "s" * 64)
    runner = ClaudeRunner(db)
    assert await runner.available() is True
    res = await runner.run("Check this. Secret: " + "s" * 64, schema=SCHEMA, system_prompt="You check.",
                           model="sonnet", max_budget_usd=0.3)
    assert res.output == {"verdict": "yes"} and res.cost_usd == pytest.approx(0.0421)
    argv = json.loads((shim / "argv.json").read_text())
    assert argv[:3] == ["-p", "--output-format", "json"]
    i = argv.index("--tools")
    assert argv[i + 1] == ""
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert argv[argv.index("--settings") + 1] == '{"disableAllHooks":true}'
    assert argv[argv.index("--max-budget-usd") + 1] == "0.30"
    assert not any("dangerously" in a or a == "--bare" for a in argv)
    assert "s" * 64 not in (shim / "stdin.txt").read_text()  # secrets are redacted before Claude sees them


@pytest.mark.parametrize("mode, exc", [("bad_output", ClaudeBadOutput), ("budget", ClaudeBudgetExceeded),
                                       ("is_error", ClaudeError)])
async def test_claude_runner_rejects_failures(db, shim, mode, exc):
    _mode(shim, mode)
    with pytest.raises(exc):
        await ClaudeRunner(db).run("x", schema=SCHEMA, system_prompt="s")


async def test_logged_out_claude_opens_one_need(db, shim):
    _mode(shim, "logged_out")
    runner = ClaudeRunner(db)
    assert await runner.available(force=True) is False
    assert await runner.available(force=True) is False
    with pytest.raises(ClaudeUnavailable):
        await runner.run("x", schema=SCHEMA, system_prompt="s")
    n = db.execute("SELECT COUNT(*) FROM needs_prerit WHERE title=? AND status='open'", (LOGIN_NEED_TITLE,)).fetchone()[0]
    assert n == 1


# ── router ───────────────────────────────────────────────────────────────────────────────────────────
class FakeManager:
    def __init__(self) -> None:
        self.used: list[str] = []

    def use(self, model_id: str):
        mgr = self

        class Ctx:
            async def __aenter__(self_inner):
                mgr.used.append(model_id)
                from hq.models.manager import Endpoint
                return Endpoint(model_id, "http://127.0.0.1:8101/v1", model_id, True)

            async def __aexit__(self_inner, *a):
                return False
        return Ctx()


def make_chat(replies: dict[str, list[str]]):
    calls: list[str] = []

    async def chat(base_url: str, model: str, messages: list[dict[str, str]], **kw: Any) -> llm_client.ChatResult:
        calls.append(model)
        text = replies[model].pop(0) if replies[model] else "garbage"
        return llm_client.ChatResult(text=text, prompt_tokens=10, completion_tokens=5, ttft_ms=5, tok_s=50,
                                     duration_ms=20, raw_text=text)
    chat.calls = calls  # type: ignore[attr-defined]
    return chat


def _setup_roles(db) -> None:
    with tx(db):
        upsert_models(db, [
            ModelInfo(id="mlx:q/Qwen3-4B", runtime="mlx", name="q/Qwen3-4B", complete=True, runtime_supported=True),
            ModelInfo(id="mlx:q/Qwen2.5-7B", runtime="mlx", name="q/Qwen2.5-7B", complete=True, runtime_supported=True),
            ModelInfo(id="mlx:l/Llama-8B", runtime="mlx", name="l/Llama-8B", complete=True, runtime_supported=True),
        ])
        for rank, mid in enumerate(("mlx:q/Qwen3-4B", "mlx:q/Qwen2.5-7B", "mlx:l/Llama-8B")):
            db.execute("INSERT INTO role_assignments(role, model_id, rank, score, source, created_at) VALUES "
                       "('eligibility', ?, ?, 0.5, 'auto', 'now')", (mid, rank))


async def test_router_first_model_with_one_repair(db):
    _setup_roles(db)
    chat = make_chat({"mlx:q/Qwen3-4B": ["not json", '{"verdict": "no", "confidence": 0.95}']})
    r = Router(db, FakeManager(), None, chat_fn=chat)
    res = await r.route("eligibility", [{"role": "user", "content": "x"}], SCHEMA)
    assert res.model_id == "mlx:q/Qwen3-4B" and res.escalation_level == 0 and res.output["verdict"] == "no"
    assert chat.calls == ["mlx:q/Qwen3-4B", "mlx:q/Qwen3-4B"]


async def test_router_escalates_to_a_different_family_then_claude(db, shim):
    _setup_roles(db)
    chat = make_chat({"mlx:q/Qwen3-4B": ["bad", "still bad"], "mlx:q/Qwen2.5-7B": [],
                      "mlx:l/Llama-8B": ['{"verdict": "yes", "confidence": 0.2}']})
    r = Router(db, FakeManager(), ClaudeRunner(db), chat_fn=chat)
    res = await r.route("eligibility", [{"role": "system", "content": "sys"}, {"role": "user", "content": "x"}],
                        SCHEMA, task_type="verify.eligibility_hard")
    # level 0 Qwen3 (bad JSON after repair) → level 1 skips same-family Qwen2.5 for Llama (low confidence) → Claude
    assert [a["model_id"] for a in res.attempts] == ["mlx:q/Qwen3-4B", "mlx:l/Llama-8B", "claude:sonnet"]
    assert res.escalation_level == 2 and res.output == {"verdict": "yes"} and res.cost_usd == pytest.approx(0.0421)
    runs = db.execute("SELECT model_id, escalated_from_run_id, status FROM agent_runs ORDER BY rowid").fetchall()
    assert [r["status"] for r in runs] == ["failed", "failed", "succeeded"]
    assert runs[1]["escalated_from_run_id"] and runs[2]["escalated_from_run_id"]
    assert db.execute("SELECT cost_usd_est FROM claude_usage WHERE subtype='success'").fetchone()[0] == pytest.approx(0.0421)
    esc = db.execute("SELECT COUNT(*) FROM events WHERE type='task.escalated'").fetchone()[0]
    assert esc == 2


async def test_router_respects_lineage_and_claude_permission(db):
    _setup_roles(db)
    chat = make_chat({"mlx:q/Qwen2.5-7B": ['{"verdict": "yes"}']})
    r = Router(db, FakeManager(), None, chat_fn=chat)
    res = await r.route("eligibility", [{"role": "user", "content": "x"}], SCHEMA,
                        lineage=("mlx:q/Qwen3-4B",), exclude_models={"mlx:l/Llama-8B"}, confidence_threshold=None)
    assert res.model_id == "mlx:q/Qwen2.5-7B"
    chat2 = make_chat({"mlx:q/Qwen3-4B": [], "mlx:q/Qwen2.5-7B": [], "mlx:l/Llama-8B": []})
    with pytest.raises(EscalationExhausted):
        await Router(db, FakeManager(), None, chat_fn=chat2).route("eligibility", [{"role": "user", "content": "x"}],
                                                                   SCHEMA, allow_claude=False)


async def test_router_defers_when_claude_budget_is_spent(db, shim):
    _setup_roles(db)
    with tx(db):
        db.execute("UPDATE settings SET value_json='0' WHERE key='claude_daily_budget_usd'")
    chat = make_chat({"mlx:q/Qwen3-4B": [], "mlx:q/Qwen2.5-7B": [], "mlx:l/Llama-8B": []})
    with pytest.raises(Deferred) as exc:
        await Router(db, FakeManager(), ClaudeRunner(db), chat_fn=chat).route(
            "eligibility", [{"role": "user", "content": "x"}], SCHEMA)
    assert exc.value.status == "deferred_budget"


async def test_worker_parks_deferred_tasks_without_burning_attempts(db, hq_env):
    from tests.conftest import drive, write_agent
    from hq.adapters.base import RunContext, RunResult
    from hq.worker import queue
    from hq.worker.orchestrator import Worker

    class Needy:
        name = "sim"

        async def health(self):
            return {"ok": True}

        async def run(self, task, ctx: RunContext) -> RunResult:
            raise Deferred("deferred_budget", "2999-01-01T00:00:00Z", "Claude daily budget or call cap reached")

    write_agent(hq_env.agents, "helper", capabilities=["summarize"])
    w = Worker(adapters={"sim": Needy()}, loop_interval=0.02, watch=False, schedule=False)
    w.startup()
    with tx(db):
        tid = queue.enqueue(db, "summarize", emit_event=False)
    assert await drive(w, lambda: queue.get_task(db, tid)["status"] == "deferred_budget")
    t = queue.get_task(db, tid)
    assert t["attempts"] == 0 and t["not_before"].startswith("2999")
    assert db.execute("SELECT 1 FROM events WHERE type='budget.capped'").fetchone()
