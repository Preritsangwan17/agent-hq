"""Local-first policy, the Grok runner contract and the router's escalation ladder (local → different local → Grok)."""
from __future__ import annotations

from typing import Any

import pytest

from hq.adapters.base import Deferred
from hq.db.conn import tx
from hq.db.seed import get_settings, set_settings
from hq.llm import client as llm_client
from hq.llm import cloud, policy
from hq.llm.errors import CloudResult
from hq.llm.router import EscalationExhausted, Router
from hq.models import roles
from hq.models.discovery.base import ModelInfo, upsert_models

SCHEMA = {"type": "object", "required": ["verdict"], "properties": {"verdict": {"enum": ["yes", "no"]},
                                                                  "confidence": {"type": "number"}}}


class FakeCloud:
    """Stands in for hq.llm.cloud.CloudRunner (Grok): always reachable, fixed answer and cost."""

    def __init__(self) -> None:
        self.reason = None
        self.calls: list[str] = []

    async def available_for(self, model: str) -> bool:
        return True

    async def run(self, prompt: str, *, schema: dict[str, Any], system_prompt: str, model: str | None = None,
                  max_budget_usd: float = 0.5, **kw: Any) -> CloudResult:
        self.calls.append(model or "")
        return CloudResult(output={"verdict": "yes"}, cost_usd=0.0421, input_tokens=900, output_tokens=40,
                           cache_read_tokens=None, duration_ms=5.0, model=model or "", subtype="success",
                           cost_source="reported")


def _set(db, **values: Any) -> dict[str, Any]:
    with tx(db):
        set_settings(db, values)
    return get_settings(db)


# ── policy ───────────────────────────────────────────────────────────────────────────────────────────
def test_policy_saver_mode_keeps_optional_work_local(db):
    s = get_settings(db)
    assert policy.mode(s) == "saver" and policy.engines(s) == "both"
    d = policy.escalate(s, "needed")
    assert d.allowed and d.tier == "fast"
    assert not policy.escalate(s, "bulk").allowed
    assert not policy.escalate(s, "second_look", local_tried=True).allowed      # becomes a one-click decision
    top, low = {"fit_score": 90}, {"fit_score": 50}
    assert not policy.polish(s, top, "high fit").allowed                          # never optional polish
    assert policy.polish(s, top, "fix").allowed and not policy.polish(s, low, "fix").allowed
    d = policy.signoff(s, top, local_checker_available=True)
    assert d.allowed and d.tier is None                                            # free local sign-off
    d = policy.signoff(s, top, local_checker_available=False)
    assert d.allowed and d.tier == "fast"


def test_policy_balanced_and_quality_spend_on_important_applications(db):
    s = _set(db, cloud_mode="balanced")
    top, low = {"fit_score": 90}, {"fit_score": 50}
    assert policy.escalate(s, "second_look").allowed
    assert policy.polish(s, top, "high fit").allowed and not policy.polish(s, low, "high fit").allowed
    assert policy.signoff(s, top, local_checker_available=True).tier == "strong"
    assert policy.signoff(s, low, local_checker_available=True).tier is None
    s = _set(db, cloud_mode="quality")
    assert policy.signoff(s, low, local_checker_available=True).tier == "strong"


def test_policy_engine_switches(db):
    s = _set(db, **policy.engines_patch("local"))
    assert policy.engines(s) == "local" and not policy.escalate(s, "needed").allowed
    d = policy.signoff(s, None, local_checker_available=True)
    assert d.allowed and d.tier is None
    assert not policy.signoff(s, None, local_checker_available=False).allowed
    s = _set(db, **policy.engines_patch("cloud"))
    assert policy.engines(s) == "cloud" and policy.escalate(s, "bulk").allowed    # Cloud only: cloud does it all
    s = _set(db, **policy.engines_patch("none"))
    assert policy.engines(s) == "none" and not policy.escalate(s, "needed").allowed
    s = _set(db, **policy.engines_patch("both"), grok_enabled=False)
    assert policy.engines(s) == "local"                                            # no provider switched on
    s = _set(db, claude_cli_enabled=True)
    assert policy.engines(s) == "both" and policy.describe(s)["cloud_order"] == ["claude"]
    with pytest.raises(ValueError):
        policy.engines_patch("everything")


def test_cloud_order_prefers_subscriptions_and_respects_switches(db):
    s = _set(db, claude_cli_enabled=True, codex_cli_enabled=True)
    assert cloud.enabled_providers(s) == ["claude", "codex", "xai"]
    assert cloud.candidates(s, "fast") == ["claude:sonnet", "codex:default", "xai:grok-4-fast", "claude:opus",
                                           "xai:grok-4"]
    assert cloud.candidates(s, "strong")[0] == "claude:opus"
    s = _set(db, prefer_subscriptions=False)
    assert cloud.enabled_providers(s)[0] == "xai"
    s = _set(db, cloud_ai_enabled=False)
    assert cloud.enabled_providers(s) == []


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


async def test_router_escalates_to_a_different_family_then_grok(db):
    _setup_roles(db)
    chat = make_chat({"mlx:q/Qwen3-4B": ["bad", "still bad"], "mlx:q/Qwen2.5-7B": [],
                      "mlx:l/Llama-8B": ['{"verdict": "yes", "confidence": 0.2}']})
    r = Router(db, FakeManager(), FakeCloud(), chat_fn=chat)
    res = await r.route("eligibility", [{"role": "system", "content": "sys"}, {"role": "user", "content": "x"}],
                        SCHEMA, task_type="verify.eligibility_hard")
    # level 0 Qwen3 (bad JSON after repair) → level 1 skips same-family Qwen2.5 for Llama (low confidence) → Grok
    assert [a["model_id"] for a in res.attempts] == ["mlx:q/Qwen3-4B", "mlx:l/Llama-8B", "xai:grok-4-fast"]
    assert res.escalation_level == 2 and res.output == {"verdict": "yes"} and res.cost_usd == pytest.approx(0.0421)
    runs = db.execute("SELECT model_id, escalated_from_run_id, status FROM agent_runs ORDER BY rowid").fetchall()
    assert [r["status"] for r in runs] == ["failed", "failed", "succeeded"]
    assert runs[1]["escalated_from_run_id"] and runs[2]["escalated_from_run_id"]
    row = db.execute("SELECT cost_usd_est, cost_source FROM cloud_usage WHERE subtype='success'").fetchone()
    assert row[0] == pytest.approx(0.0421) and row[1] == "reported"
    esc = db.execute("SELECT COUNT(*) FROM events WHERE type='task.escalated'").fetchone()[0]
    assert esc == 2


async def test_router_respects_lineage_and_local_only_steps(db):
    _setup_roles(db)
    chat = make_chat({"mlx:q/Qwen2.5-7B": ['{"verdict": "yes"}']})
    r = Router(db, FakeManager(), None, chat_fn=chat)
    res = await r.route("eligibility", [{"role": "user", "content": "x"}], SCHEMA,
                        lineage=("mlx:q/Qwen3-4B",), exclude_models={"mlx:l/Llama-8B"}, confidence_threshold=None)
    assert res.model_id == "mlx:q/Qwen2.5-7B"
    chat2 = make_chat({"mlx:q/Qwen3-4B": [], "mlx:q/Qwen2.5-7B": [], "mlx:l/Llama-8B": []})
    with pytest.raises(EscalationExhausted):
        await Router(db, FakeManager(), None, chat_fn=chat2).route("eligibility", [{"role": "user", "content": "x"}],
                                                                   SCHEMA, cloud_use=None)


async def test_router_defers_when_grok_budget_is_spent(db):
    _setup_roles(db)
    with tx(db):
        db.execute("UPDATE settings SET value_json='0' WHERE key='cloud_daily_budget_usd'")
    chat = make_chat({"mlx:q/Qwen3-4B": [], "mlx:q/Qwen2.5-7B": [], "mlx:l/Llama-8B": []})
    with pytest.raises(Deferred) as exc:
        await Router(db, FakeManager(), FakeCloud(), chat_fn=chat).route(
            "eligibility", [{"role": "user", "content": "x"}], SCHEMA)
    assert exc.value.status == "deferred_budget"


async def test_router_obeys_the_on_off_switches(db):
    _setup_roles(db)
    grok = FakeCloud()
    _set(db, **policy.engines_patch("cloud"))
    chat = make_chat({"mlx:q/Qwen3-4B": ['{"verdict": "no"}']})
    res = await Router(db, FakeManager(), grok, chat_fn=chat).route("eligibility", [{"role": "user", "content": "x"}],
                                                                   SCHEMA, cloud_use="bulk")
    assert res.model_id == "xai:grok-4-fast" and chat.calls == []                 # local models never touched
    _set(db, **policy.engines_patch("local"))
    chat = make_chat({"mlx:q/Qwen3-4B": [], "mlx:q/Qwen2.5-7B": [], "mlx:l/Llama-8B": []})
    with pytest.raises(EscalationExhausted, match="cloud models are switched off"):
        await Router(db, FakeManager(), grok, chat_fn=chat).route("eligibility", [{"role": "user", "content": "x"}],
                                                                  SCHEMA)
    assert len(grok.calls) == 1
    _set(db, **policy.engines_patch("both"))
    with tx(db):
        db.execute("UPDATE models SET enabled=0 WHERE id='mlx:q/Qwen3-4B'")        # one model switched off
    assert roles.ranked(db, "eligibility") == ["mlx:q/Qwen2.5-7B", "mlx:l/Llama-8B"]
    chat = make_chat({"mlx:q/Qwen2.5-7B": ['{"verdict": "yes", "confidence": 0.9}']})
    res = await Router(db, FakeManager(), grok, chat_fn=chat).route("eligibility", [{"role": "user", "content": "x"}],
                                                                   SCHEMA)
    assert res.model_id == "mlx:q/Qwen2.5-7B" and "mlx:q/Qwen3-4B" not in chat.calls


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
            raise Deferred("deferred_budget", "2999-01-01T00:00:00Z", "Grok daily budget or call cap reached")

    write_agent(hq_env.agents, "helper", capabilities=["summarize"])
    w = Worker(adapters={"sim": Needy()}, loop_interval=0.02, watch=False, schedule=False)
    w.startup()
    with tx(db):
        tid = queue.enqueue(db, "summarize", emit_event=False)
    assert await drive(w, lambda: queue.get_task(db, tid)["status"] == "deferred_budget")
    t = queue.get_task(db, tid)
    assert t["attempts"] == 0 and t["not_before"].startswith("2999")
    assert db.execute("SELECT 1 FROM events WHERE type='budget.capped'").fetchone()
