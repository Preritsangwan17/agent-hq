"""xAI (Grok) as a cloud provider: availability, structured output, cost, failures, redaction, net guard, and the
provider switch / independent sign-off choice. All traffic goes to an httpx MockTransport with a fake key."""
from __future__ import annotations

import json

import httpx
import pytest

from hq.db.conn import tx
from hq.db.seed import get_settings, set_settings
from hq.llm import cloud
from hq.llm.claude import ClaudeBudgetExceeded, ClaudeRateLimited, ClaudeUnavailable
from hq.llm.xai import NEED_TITLE, XaiRunner, cost_of
from hq.util import netguard
from hq.util.redact import redact

FAKE_KEY = "xai-" + "T3st" * 10
SCHEMA = {"type": "object", "required": ["score"], "properties": {"score": {"type": "integer"}}}


class Api:
    def __init__(self, replies: list[httpx.Response] | None = None, models=("grok-4-0709", "grok-4-fast-reasoning")):
        self.replies = list(replies or [])
        self.models = models
        self.seen: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.seen.append(req)
        if req.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": m} for m in self.models]})
        return self.replies.pop(0)


def ok(content: str, **usage) -> httpx.Response:
    return httpx.Response(200, json={"id": "r1", "choices": [{"message": {"content": content}}],
                                     "usage": {"prompt_tokens": 100, "completion_tokens": 20, **usage}})


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("HQ_XAI_API_KEY", FAKE_KEY)


async def test_no_key_means_unavailable_and_asks_prerit_only_when_xai_is_in_use(db, monkeypatch):
    monkeypatch.delenv("HQ_XAI_API_KEY", raising=False)
    quiet = XaiRunner(db)
    quiet.nag = False
    assert not await quiet.available() and "HQ_XAI_API_KEY" in quiet.reason
    assert db.execute("SELECT COUNT(*) FROM needs_prerit WHERE title=?", (NEED_TITLE,)).fetchone()[0] == 0
    loud = XaiRunner(db)
    assert not await loud.available()
    assert db.execute("SELECT COUNT(*) FROM needs_prerit WHERE title=?", (NEED_TITLE,)).fetchone()[0] == 1


async def test_available_lists_models_and_resolves_drifting_names(db, key):
    api = Api()
    x = XaiRunner(db, transport=httpx.MockTransport(api))
    assert await x.available()
    assert api.seen[0].method == "GET" and api.seen[0].headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert x.resolve("grok-4-fast") == "grok-4-fast-reasoning" and x.resolve("grok-4") == "grok-4-0709"


async def test_run_sends_redacted_structured_request_and_validates(db, key):
    from hq.profile.fields import update_field

    with tx(db):
        update_field(db, "phone", "+91 98111 22334")
    api = Api([ok('{"score": 4}', cost_in_usd_ticks=12_345_000)])
    x = XaiRunner(db, transport=httpx.MockTransport(api))
    await x.available()
    res = await x.run(f"Call me on +91 98111 22334. key={FAKE_KEY}", schema=SCHEMA, system_prompt="Rate it.",
                      model="grok-4-fast", max_budget_usd=0.5)
    assert res.output == {"score": 4} and res.model == "xai:grok-4-fast-reasoning"
    assert res.cost_usd == pytest.approx(0.0012345) and res.input_tokens == 100
    req = api.seen[-1]
    body = json.loads(req.content)
    assert req.method == "POST" and req.url.path == "/v1/chat/completions"
    assert body["response_format"]["type"] == "json_schema" and body["temperature"] == 0
    sent = json.dumps(body["messages"])
    assert "98111" not in sent and FAKE_KEY not in sent and "tools" not in body


async def test_invalid_output_gets_one_repair_round(db, key):
    api = Api([ok("not json at all"), ok('{"score": 5}')])
    x = XaiRunner(db, transport=httpx.MockTransport(api))
    res = await x.run("p", schema=SCHEMA, system_prompt="s", model="grok-4-fast")
    assert res.output == {"score": 5}
    assert res.cost_usd == pytest.approx(2 * cost_of("grok-4-fast", {"prompt_tokens": 100, "completion_tokens": 20}))
    assert "invalid" in json.loads(api.seen[-1].content)["messages"][-1]["content"]


async def test_no_credit_becomes_one_needs_item_and_rate_limit_defers(db, key):
    api = Api([httpx.Response(403, json={"error": "Your team has no credits left. Purchase credits."})])
    x = XaiRunner(db, transport=httpx.MockTransport(api))
    with pytest.raises(ClaudeUnavailable, match="no credit"):
        await x.run("p", schema=SCHEMA, system_prompt="s", model="grok-4-fast")
    need = db.execute("SELECT * FROM needs_prerit WHERE title=?", (NEED_TITLE,)).fetchone()
    assert need and "console.x.ai" in need["instructions_md"] and "credit" in need["instructions_md"]
    x2 = XaiRunner(db, transport=httpx.MockTransport(Api([httpx.Response(429, json={"error": "slow down"})])))
    with pytest.raises(ClaudeRateLimited):
        await x2.run("p", schema=SCHEMA, system_prompt="s", model="grok-4-fast")


async def test_models_without_structured_outputs_fall_back_to_prompt_json(db, key):
    api = Api([httpx.Response(400, json={"error": "response_format json_schema is not supported"}), ok('{"score": 3}')])
    res = await XaiRunner(db, transport=httpx.MockTransport(api)).run("p", schema=SCHEMA, system_prompt="s",
                                                                    model="grok-3-mini")
    assert res.output == {"score": 3} and "response_format" not in json.loads(api.seen[-1].content)


async def test_per_call_cap_is_enforced_before_sending(db, key):
    api = Api()
    with pytest.raises(ClaudeBudgetExceeded):
        await XaiRunner(db, transport=httpx.MockTransport(api)).run("x" * 400_000, schema=SCHEMA, system_prompt="s",
                                                                    model="grok-4", max_budget_usd=0.05)
    assert not [r for r in api.seen if r.method == "POST"]


def test_net_guard_allows_only_the_model_api_on_xai():
    netguard.check("POST", "https://api.x.ai/v1/chat/completions")
    for method, url in (("POST", "https://api.x.ai/admin"), ("POST", "https://x.ai/v1/chat/completions"),
                        ("PUT", "https://api.x.ai/v1/chat/completions")):
        with pytest.raises(netguard.NetGuardError):
            netguard.check(method, url)


def test_api_keys_are_redacted_even_without_env():
    assert "[redacted-key]" in redact("my key is xai-abcdefghijklmnopqrstuvwxyz0123456789")


async def test_provider_switch_and_independent_signoff(db, key, monkeypatch):
    s = get_settings(db)
    assert cloud.provider(s) == "xai" and cloud.main_model(s) == "xai:grok-4-fast"
    assert cloud.signoff_candidates(s)[:2] == ["xai:grok-4", "xai:grok-4-fast"]
    with tx(db):
        set_settings(db, {"cloud_llm": "claude"})
    s = get_settings(db)
    assert cloud.main_model(s) == "sonnet" and cloud.signoff_candidates(s)[0] == "opus"
    monkeypatch.delenv("HQ_XAI_API_KEY")
    with tx(db):
        set_settings(db, {"cloud_llm": "auto"})
    assert cloud.provider(get_settings(db)) == "claude"

    class Runner:
        async def available_for(self, model: str) -> bool:
            return model.startswith("xai:")

    monkeypatch.setenv("HQ_XAI_API_KEY", FAKE_KEY)
    s = get_settings(db)
    assert await cloud.signoff_model(Runner(), s, set()) == "xai:grok-4"
    assert await cloud.signoff_model(Runner(), s, {"xai:grok-4"}) == "xai:grok-4-fast"
    assert await cloud.signoff_model(Runner(), s, {"xai:grok-4", "xai:grok-4-fast"}) is None   # Claude unreachable


async def test_router_escalates_to_xai_when_no_local_model(db, key):
    from hq.llm.router import Router

    api = Api([ok('{"score": 2}')])
    runner = cloud.CloudRunner(db, xai=XaiRunner(db, transport=httpx.MockTransport(api)))
    res = await Router(db, None, runner).route("summarizer", [{"role": "system", "content": "s"},
                                                              {"role": "user", "content": "u"}], SCHEMA)
    assert res.model_id == "xai:grok-4-fast" and res.output == {"score": 2}
    row = db.execute("SELECT adapter, model_id, cost_usd FROM agent_runs ORDER BY started_at DESC").fetchone()
    assert row["adapter"] == "xai" and row["cost_usd"] > 0
    assert db.execute("SELECT COUNT(*) FROM claude_usage").fetchone()[0] == 1          # same daily budget
