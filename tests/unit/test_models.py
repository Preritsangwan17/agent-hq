"""Phase (b): discovery, memory helpers, the model manager, JSON utils + client, roles, budget and API routes."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
import respx

from hq.db.conn import tx
from hq.llm import client as llm_client
from hq.llm.json_utils import JSONExtractError, extract_json, parse_and_validate, strip_think
from hq.models import memory as mem
from hq.models import roles
from hq.models.discovery import mlx
from hq.models.discovery.base import ModelInfo, model_family, params_from_name, upsert_models
from hq.models.manager import ModelBroken, ModelManager, WaitingMemory
from hq.worker import budget
from tests.conftest import MUTATE


# ── discovery: fake HF cache ─────────────────────────────────────────────────────────────────────────
def _repo(root: Path, name: str, *, files: dict[str, bytes | None], config: dict | None, chat: bool = True,
          index: list[str] | None = None, ref_only: bool = False, extra: dict[str, str] | None = None) -> Path:
    repo = root / f"models--{name.replace('/', '--')}"
    (repo / "refs").mkdir(parents=True)
    rev = "abc123"
    (repo / "refs" / "main").write_text(rev)
    if ref_only:
        return repo
    snap = repo / "snapshots" / rev
    blobs = repo / "blobs"
    snap.mkdir(parents=True)
    blobs.mkdir()
    all_files = dict(files)
    if config is not None:
        all_files["config.json"] = json.dumps(config).encode()
    all_files["tokenizer_config.json"] = json.dumps({"chat_template": "{{x}}"} if chat else {}).encode()
    if index is not None:
        all_files["model.safetensors.index.json"] = json.dumps({"weight_map": {f"w{i}": f for i, f in
                                                                               enumerate(index)}}).encode()
    for fname, data in {**all_files, **{k: v.encode() for k, v in (extra or {}).items()}}.items():
        sha = f"blob-{fname}"
        if data is None:  # partial download: only the .incomplete blob exists
            (blobs / f"{sha}.incomplete").write_bytes(b"x")
        else:
            (blobs / sha).write_bytes(data)
        (snap / fname).symlink_to(blobs / sha)
    return repo


@pytest.fixture
def hf_cache(tmp_path: Path) -> Path:
    root = tmp_path / "hub"
    root.mkdir()
    q = {"model_type": "qwen3", "architectures": ["Qwen3ForCausalLM"], "quantization": {"bits": 4, "group_size": 64},
         "max_position_embeddings": 32768}
    _repo(root, "mlx-community/Qwen3-4B-Instruct-2507-4bit", files={"model.safetensors": b"w" * 1000}, config=q)
    _repo(root, "mlx-community/Qwen2.5-14B-Instruct-4bit", files={"a.safetensors": b"w", "b.safetensors": None},
          config={**q, "model_type": "qwen2"}, index=["a.safetensors", "b.safetensors"])
    _repo(root, "mlx-community/Qwen2.5-1.5B-Instruct-4bit", files={}, config=None, ref_only=True)
    _repo(root, "mlx-community/Qwen3.5-2B-4bit", files={}, config={**q, "model_type": "qwen3_5"})
    _repo(root, "mlx-community/Weird-1B", files={"model.safetensors": b"w"}, config={**q, "model_type": "nope"})
    _repo(root, "sentence-transformers/all-MiniLM-L6-v2", files={"model.safetensors": b"w"}, config={"model_type": "bert"},
          chat=False, extra={"modules.json": "[]"})
    _repo(root, "mlx-community/whisper-large-v3-turbo", files={"weights.safetensors": b"w"},
          config={"model_type": "whisper"}, chat=False)
    return root


def test_mlx_discovery_classifies_complete_partial_and_unsupported(hf_cache: Path):
    supported = {"qwen3", "qwen2", "bert"}
    found = {m.name: m for m in mlx.discover(hf_cache, supports=lambda t: t in supported)}
    ok = found["mlx-community/Qwen3-4B-Instruct-2507-4bit"]
    assert ok.usable and ok.id == "mlx:mlx-community/Qwen3-4B-Instruct-2507-4bit" and ok.quant == "4bit/g64"
    assert ok.extra["qwen3"] is True and ok.params_b == 4 and ok.ctx_len == 32768
    partial = found["mlx-community/Qwen2.5-14B-Instruct-4bit"]
    assert not partial.complete and "1 of 2 weight shards" in partial.incomplete_reason
    ref = found["mlx-community/Qwen2.5-1.5B-Instruct-4bit"]
    assert not ref.complete and "only a ref" in ref.incomplete_reason
    noweights = found["mlx-community/Qwen3.5-2B-4bit"]
    assert not noweights.complete and "no weights" in noweights.incomplete_reason
    weird = found["mlx-community/Weird-1B"]
    assert weird.complete and not weird.runtime_supported and "nope" in weird.incomplete_reason
    assert found["sentence-transformers/all-MiniLM-L6-v2"].modality == "embedding"
    assert found["mlx-community/whisper-large-v3-turbo"].modality == "stt"
    usable = [m for m in found.values() if m.usable]
    assert [m.name for m in usable] == ["mlx-community/Qwen3-4B-Instruct-2507-4bit"]


def test_upsert_announces_newly_usable_models(db, hf_cache: Path):
    models = mlx.discover(hf_cache, supports=lambda t: t in {"qwen3", "qwen2"})
    with tx(db):
        new, usable = upsert_models(db, models)
    assert len(new) == len(models) and usable == ["mlx:mlx-community/Qwen3-4B-Instruct-2507-4bit"]
    with tx(db):
        new2, usable2 = upsert_models(db, models)
    assert new2 == [] and usable2 == []
    status = dict(db.execute("SELECT name, status FROM models").fetchall())
    assert status["mlx-community/Qwen2.5-14B-Instruct-4bit"] == "broken"
    assert status["mlx-community/Weird-1B"] == "unsupported"


def test_name_helpers():
    assert model_family("mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-DWQ") == "qwen"
    assert model_family("llama3.1:8b") == "llama"
    assert params_from_name("mlx-community/Qwen3-Coder-30B-A3B-Instruct") == 30
    assert params_from_name("Qwen3-0.6B-4bit") == 0.6


# ── memory ───────────────────────────────────────────────────────────────────────────────────────────
def test_memory_helpers():
    fp = mem.phys_footprint_gb(os.getpid())
    assert fp and fp[0] > 0 and fp[1] >= fp[0] * 0.5
    sample = ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 100.\n"
              "Pages inactive: 50.\nPages purgeable: 10.\nPages speculative: 40.\n")
    assert mem.parse_vm_stat(sample) == 200 * 16384
    s = mem.system_memory()
    assert s.total_gb > 0 and s.pressure in ("normal", "warn", "critical")


# ── manager ──────────────────────────────────────────────────────────────────────────────────────────
class FakeProc:
    _pid = 50000

    def __init__(self) -> None:
        FakeProc._pid += 1
        self.pid = FakeProc._pid
        self.code: int | None = None

    def poll(self) -> int | None:
        return self.code

    def terminate(self) -> None:
        self.code = 0

    def kill(self) -> None:
        self.code = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.code or 0


class Harness:
    def __init__(self, db, *, available: float = 40.0, active: bool = False):
        self.spawned: list[list[str]] = []
        self.procs: dict[int, FakeProc] = {}
        self.healthy = True
        self.available = available
        self.active = active
        self.t = 0.0
        self.mgr = ModelManager(db, spawner=self.spawn, health=self.health, memory_fn=self.memory,
                                footprint_fn=lambda pid: None, active_fn=lambda: self.active, battery_fn=lambda: False,
                                clock=lambda: self.t, load_timeout_s=0.3)

    def spawn(self, argv: list[str], port: int, model_id: str) -> FakeProc:
        self.spawned.append(argv)
        p = FakeProc()
        self.procs[port] = p
        return p

    async def health(self, url: str) -> bool:
        return self.healthy

    def memory(self) -> mem.SystemMemory:
        return mem.SystemMemory(48.0, self.available, "normal")


def _add_model(db, mid: str, ram: float, *, qwen3: bool = False) -> None:
    with tx(db):
        upsert_models(db, [ModelInfo(id=mid, runtime="mlx", name=mid.split(":", 1)[1], served_id=mid.split(":", 1)[1],
                                     complete=True, runtime_supported=True, est_ram_gb=ram,
                                     model_type="qwen3" if qwen3 else "qwen2", extra={"qwen3": qwen3})])


async def test_manager_loads_evicts_lru_and_waits_for_memory(db):
    for mid, ram in (("mlx:a/A-7B", 6.0), ("mlx:b/B-4B", 3.0), ("mlx:c/C-30B", 16.0), ("mlx:d/D-big", 40.0)):
        _add_model(db, mid, ram, qwen3=mid.endswith("4B"))
    h = Harness(db)
    with tx(db):
        db.execute("UPDATE settings SET value_json='20' WHERE key='model_pool_budget_gb'")
    ep = await h.mgr.ensure("mlx:a/A-7B")
    assert ep.base_url == "http://127.0.0.1:8101/v1" and "--max-tokens" in h.spawned[0]
    h.t = 10
    await h.mgr.ensure("mlx:b/B-4B")
    assert "--chat-template-args" in h.spawned[1]
    assert h.mgr.pool_used_gb() == 9.0
    h.t = 20
    async with h.mgr.use("mlx:b/B-4B"):
        await h.mgr.ensure("mlx:c/C-30B")  # 9 + 16 > 20 → evict the LRU idle one (A); B is busy
    assert set(h.mgr.servers) == {"mlx:b/B-4B", "mlx:c/C-30B"}
    with pytest.raises(WaitingMemory):
        await h.mgr.ensure("mlx:d/D-big")
    assert db.execute("SELECT status FROM models WHERE id='mlx:c/C-30B'").fetchone()[0] == "loaded"


async def test_pinned_models_survive_eviction_and_headroom_is_checked(db):
    _add_model(db, "mlx:a/A", 6.0)
    _add_model(db, "mlx:b/B", 6.0)
    h = Harness(db, available=20.0)
    with tx(db):
        db.execute("UPDATE settings SET value_json='10' WHERE key='model_pool_budget_gb'")
        db.execute("UPDATE models SET pinned=1 WHERE id='mlx:a/A'")
    await h.mgr.ensure("mlx:a/A")
    with pytest.raises(WaitingMemory, match="pool"):
        await h.mgr.ensure("mlx:b/B")  # A is pinned, so nothing can be evicted
    h2 = Harness(db, available=5.0)
    with pytest.raises(WaitingMemory, match="free"):
        await h2.mgr.ensure("mlx:b/B")  # 5 GB free < 6 + 4 headroom


async def test_usability_mode_shrinks_pool_and_unloads(db):
    _add_model(db, "mlx:c/C-30B", 18.0)
    h = Harness(db)
    await h.mgr.ensure("mlx:c/C-30B")
    h.active = True
    assert h.mgr.pool_budget_gb() == 8.0 and h.mgr.usability_reason() == "you are using the Mac"
    await h.mgr.tick(force=True)
    assert h.mgr.servers == {}


async def test_restarts_are_capped_then_model_is_broken(db):
    _add_model(db, "mlx:a/A", 4.0)
    h = Harness(db)
    await h.mgr.ensure("mlx:a/A")
    h.healthy = False
    await h.mgr.tick(force=True)          # health check fails (1), restart fails to load (2)
    for _ in range(2):                    # the next tasks retry loading (3, 4 → broken)
        with pytest.raises(ModelBroken):
            await h.mgr.ensure("mlx:a/A")
    assert db.execute("SELECT status FROM models WHERE id='mlx:a/A'").fetchone()[0] == "broken"
    h.healthy = True
    with pytest.raises(ModelBroken, match="broken"):
        await h.mgr.ensure("mlx:a/A")


# ── json utils + client ──────────────────────────────────────────────────────────────────────────────
def test_extract_json_handles_think_fences_and_prose():
    assert extract_json('<think>hmm {"no": 1}</think>\nSure! ```json\n{"a": [1, 2,]}\n``` done') == {"a": [1, 2]}
    assert extract_json('Result: {"s": "brace } in string", "n": 2} trailing') == {"s": "brace } in string", "n": 2}
    assert strip_think("<think>unclosed reasoning {\"x\":1}") == '{"x":1}'
    with pytest.raises(JSONExtractError):
        extract_json("no json here")
    out, errors = parse_and_validate('{"verdict": "maybe"}', {"type": "object", "properties": {
        "verdict": {"enum": ["yes", "no"]}}, "required": ["verdict"]})
    assert errors and "verdict" in errors[0]


def _sse(chunks: list[str], usage: dict | None = None) -> str:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}" for c in chunks]
    if usage:
        lines.append(f"data: {json.dumps({'choices': [], 'usage': usage})}")
    lines.append("data: [DONE]")
    return "\n\n".join(lines) + "\n\n"


@respx.mock
async def test_client_streams_and_measures():
    route = respx.post("http://127.0.0.1:8101/v1/chat/completions").mock(return_value=httpx.Response(
        200, text=_sse(["<think>x</think>", '{"ok"', ": true}"], {"prompt_tokens": 12, "completion_tokens": 3})))
    res = await llm_client.chat("http://127.0.0.1:8101/v1", "m", [{"role": "user", "content": "hi"}], max_tokens=50)
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "m" and body["max_tokens"] == 50 and body["stream"] is True
    assert res.text == '{"ok": true}' and res.prompt_tokens == 12 and res.completion_tokens == 3
    assert res.ttft_ms is not None
    with pytest.raises(llm_client.LLMError, match="non-local"):
        await llm_client.chat("https://api.example.com/v1", "m", [])


# ── roles ────────────────────────────────────────────────────────────────────────────────────────────
def _bench(db, mid: str, task: str, *, acc: float, rec: float | None = None, prec: float | None = None,
           f1: float | None = None, tok_s: float = 50, jv: float = 1.0) -> None:
    from hq.util.ids import new_id
    from hq.util.timeutil import now_iso

    with tx(db):
        db.execute("INSERT INTO benchmarks(id, model_id, suite_version, task, n, accuracy, precision, recall, f1, "
                   "json_valid_first, json_valid_after_repair, tok_s_gen, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (new_id(), mid, "t", task, 10, acc, prec, rec, f1, jv, jv, tok_s, now_iso()))


def test_roles_assign_checker_first_and_keep_writer_independent(db):
    for mid, ram in (("mlx:q/Qwen3-30B", 17.0), ("mlx:q/Qwen2.5-7B", 5.0), ("mlx:l/Llama-3.1-8B", 5.0)):
        _add_model(db, mid, ram)
    _bench(db, "mlx:q/Qwen3-30B", "factcheck", acc=0.9, rec=0.95, prec=0.9, f1=0.9)
    _bench(db, "mlx:q/Qwen3-30B", "write_paragraph", acc=0.95)
    _bench(db, "mlx:q/Qwen2.5-7B", "factcheck", acc=0.8, rec=0.7, prec=0.95, f1=0.75)  # below recall floor
    _bench(db, "mlx:q/Qwen2.5-7B", "write_paragraph", acc=0.8)
    _bench(db, "mlx:l/Llama-3.1-8B", "write_paragraph", acc=0.78)
    roles.assign(db, 30)
    assert roles.ranked(db, "fact_checker") == ["mlx:q/Qwen3-30B"]
    writers = roles.ranked(db, "writer")
    assert writers[0] != "mlx:q/Qwen3-30B" and "mlx:q/Qwen3-30B" not in writers
    assert writers[0] == "mlx:l/Llama-3.1-8B"  # different family from the checker wins a near-tie
    assert not roles.needs_cloud_signoff(db)
    with pytest.raises(roles.IndependenceError):
        roles.set_override(db, "writer", "mlx:q/Qwen3-30B")
    roles.set_override(db, "writer", "mlx:q/Qwen2.5-7B")
    roles.assign(db, 30)  # overrides survive re-benchmarks
    assert roles.ranked(db, "writer")[0] == "mlx:q/Qwen2.5-7B"
    assert roles.checker_allowed("mlx:q/Qwen3-30B", ["mlx:q/Qwen2.5-7B", "xai:grok-4-fast"])
    assert not roles.checker_allowed("xai:grok-4-fast", ["mlx:q/Qwen2.5-7B", "xai:grok-4-fast"])


def test_no_checker_meeting_floor_means_cloud_signoff(db):
    _add_model(db, "mlx:q/Small", 1.0)
    _bench(db, "mlx:q/Small", "factcheck", acc=0.6, rec=0.5, prec=0.9, f1=0.6)
    roles.assign(db, 30)
    assert roles.needs_cloud_signoff(db)
    assert roles.roles_json(db)[0]["needs_cloud_signoff"] is True


# ── budget ───────────────────────────────────────────────────────────────────────────────────────────
def test_budget_reserve_commit_and_cap(db):
    with tx(db):
        db.execute("UPDATE settings SET value_json='0.2' WHERE key='cloud_daily_budget_usd'")
    r1 = budget.reserve(db, "factcheck.signoff")
    assert r1 and r1.estimate_usd == pytest.approx(0.04)
    budget.commit(db, r1, cost_usd=0.12)
    r2 = budget.reserve(db, "factcheck.signoff")  # EMA now above the seed
    assert r2 and r2.estimate_usd > 0.04
    assert budget.reserve(db, "factcheck.signoff") is None  # 0.12 + reserved + est > 0.2
    budget.release(db, r2)
    state = budget.budget_state(db)
    assert state["spent_usd"] == pytest.approx(0.12) and state["calls"] == 1 and state["reserved_usd"] == 0


def test_budget_call_cap_and_ist_day_rollover(db):
    with tx(db):
        db.execute("UPDATE settings SET value_json='1' WHERE key='cloud_daily_call_cap'")
    r = budget.reserve(db, "polish.final")
    budget.commit(db, r, cost_usd=0.01)
    assert budget.reserve(db, "polish.final") is None
    with tx(db):
        db.execute("UPDATE cloud_usage SET date_local='2000-01-01'")  # yesterday's calls don't count today
    assert budget.reserve(db, "polish.final") is not None
    nxt = budget.next_midnight_ist()
    assert nxt.hour == 0 and nxt.minute == 0 and str(nxt.tzinfo) == "Asia/Kolkata"


def test_deferred_tasks_revive_after_their_time(db):
    from hq.worker import queue

    with tx(db):
        tid = queue.enqueue(db, "factcheck.signoff", emit_event=False)
        budget.defer_task(db, tid)
        assert queue.get_task(db, tid)["status"] == "deferred_budget"
        assert budget.revive_deferred(db) == 0
        db.execute("UPDATE tasks SET not_before='2000-01-01T00:00:00Z' WHERE id=?", (tid,))
        assert budget.revive_deferred(db) == 1


# ── API ──────────────────────────────────────────────────────────────────────────────────────────────
def test_models_roles_budget_routes(authed, db):
    _add_model(db, "mlx:q/Qwen3-30B", 17.0)
    _add_model(db, "mlx:q/Qwen2.5-7B", 5.0)
    _bench(db, "mlx:q/Qwen3-30B", "factcheck", acc=0.9, rec=0.95, prec=0.9, f1=0.9)
    _bench(db, "mlx:q/Qwen2.5-7B", "write_paragraph", acc=0.8)
    roles.assign(db, 30)
    body = authed.get("/api/models").json()
    assert {m["id"] for m in body["models"]} == {"mlx:q/Qwen3-30B", "mlx:q/Qwen2.5-7B"}
    q30 = next(m for m in body["models"] if m["id"] == "mlx:q/Qwen3-30B")
    assert q30["roles"] == ["fact_checker"] and q30["scores"]["factcheck"]["recall"] == 0.95
    assert body["memory"]["total_gb"] > 0 and body["benchmark"] == {"running": False}
    r = authed.patch("/api/roles", json={"role": "writer", "model_id": "mlx:q/Qwen3-30B"}, headers=MUTATE)
    assert r.status_code == 409 and r.json()["error"] == "independence"
    assert authed.patch("/api/roles", json={"role": "writer", "model_id": "mlx:q/Qwen2.5-7B"},
                        headers=MUTATE).status_code == 200
    r = authed.post("/api/models/mlx:q/Qwen2.5-7B/pin", json={"pinned": True}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["pinned"] is True
    assert authed.post("/api/models/benchmark", json={"suite": "quick"}, headers=MUTATE).json() == {"queued": True}
    b = authed.get("/api/budget").json()
    assert b["budget_usd"] == 2.0 and b["call_cap"] == 40 and b["calls"] == 0


# ── benchmark suite (fake model) ─────────────────────────────────────────────────────────────────────
async def test_quick_benchmark_fills_leaderboard_and_assigns_roles(db, hq_env):
    from hq.models.benchmark.suite import run_suite

    _add_model(db, "mlx:q/Qwen3-4B", 3.0)

    async def fake_chat(base_url, model, messages, **kw):
        system = messages[0]["content"]
        if "fact-checker" in system:
            n = messages[-1]["content"].count("SENTENCE:")
            text = json.dumps({"results": [{"i": i, "verdict": "supported"} for i in range(n)]})
        elif "filter job titles" in system:
            n = messages[-1]["content"].count("\n") + 1
            text = json.dumps({"results": [{"i": i, "target": "intern" in messages[-1]["content"].lower()} for i in range(n)]})
        elif "classify an email" in system:
            text = '{"label": "interview_invite", "lock": true, "confidence": 0.9}'
        elif "decide whether a posting accepts" in system:
            text = '{"verdict": "ineligible", "requirements": [], "confidence": 0.9}'
        elif "extract structured data" in system:
            text = '{"parse_ok": true, "company": "GE HealthCare", "title": "Research Intern - AI", "kind": "internship", "location": {"city": "Bengaluru"}, "requirements": [], "apply": {}}'
        else:
            text = json.dumps({"sentences": [{"text": "I built an item-based collaborative-filtering book recommender.",
                                              "kind": "claim", "fact_ids": ["F-BOOK-CF"], "job_quote_ids": []}]})
        return llm_client.ChatResult(text=text, prompt_tokens=100, completion_tokens=20, ttft_ms=50.0, tok_s=60.0,
                                     duration_ms=100.0, raw_text=text)

    h = Harness(db)
    summary = await run_suite(db, h.mgr, quick=True, chat_fn=fake_chat)
    res = summary["mlx:q/Qwen3-4B"]
    assert set(res) == {"parse_job", "eligibility", "title_filter", "write_paragraph", "factcheck", "classify_email"}
    assert res["factcheck"]["recall"] == 0.0 and res["factcheck"]["precision"] == 1.0  # passes everything
    assert res["classify_email"]["json_valid_first"] == 1.0 and res["classify_email"]["tok_s_gen"] == 60.0
    assert db.execute("SELECT COUNT(*) FROM benchmarks").fetchone()[0] == 6
    assert roles.needs_cloud_signoff(db)  # a checker that flags nothing is below the floor
    # one model can't be both writer and checker: the writer role stays empty (the Writer escalates to Grok)
    assert roles.ranked(db, "fact_checker") == ["mlx:q/Qwen3-4B"] and roles.ranked(db, "writer") == []
    assert roles.ranked(db, "classifier") == ["mlx:q/Qwen3-4B"]
    assert (hq_env.root / "artifacts" / "bench" / "mlx_q_Qwen3-4B" / "factcheck.json").exists()
    assert db.execute("SELECT 1 FROM events WHERE type='benchmark.done'").fetchone()


# ── local-first switches, Grok usage dashboard, model downloads ──────────────────────────────────────
async def test_switched_off_models_and_local_ai_are_never_loaded(db):
    _add_model(db, "mlx:a/A-7B", 6.0)
    _add_model(db, "mlx:b/B-4B", 3.0)
    h = Harness(db)
    await h.mgr.ensure("mlx:a/A-7B")
    with tx(db):
        db.execute("UPDATE models SET enabled=0 WHERE id='mlx:a/A-7B'")
    with pytest.raises(ModelBroken, match="switched off"):
        await h.mgr.ensure("mlx:a/A-7B")
    await h.mgr.tick(force=True)
    assert "mlx:a/A-7B" not in h.mgr.servers                                    # its memory is freed
    from hq.db.seed import set_settings
    with tx(db):
        set_settings(db, {"local_ai_enabled": False})
    with pytest.raises(ModelBroken, match="local AI is switched off"):
        await h.mgr.ensure("mlx:b/B-4B")


def test_engine_switch_and_per_model_switch_routes(authed, db):
    _add_model(db, "mlx:q/Qwen3-30B", 17.0)
    r = authed.post("/api/ai/engines", json={"engines": "local"}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["policy"]["engines"] == "local"
    assert authed.get("/api/settings").json()["settings"]["cloud_ai_enabled"] is False
    assert authed.post("/api/ai/engines", json={"engines": "some"}, headers=MUTATE).status_code == 400
    assert authed.post("/api/ai/engines", json={"engines": "none"}, headers=MUTATE).json()["policy"]["engines"] == "none"
    r = authed.post("/api/models/mlx:q/Qwen3-30B/enabled", json={"enabled": False}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert db.execute("SELECT kind FROM commands WHERE kind='model_unload'").fetchone()
    body = authed.get("/api/models").json()
    assert body["policy"]["engines"] == "none" and body["models"][0]["enabled"] is False


def test_recommended_models_and_pull_only_from_the_catalog(authed, db):
    rec = authed.get("/api/models/recommended").json()
    names = [m["ollama"] for m in rec["models"]]
    assert rec["mac"]["memory_gb"] == 48 and "qwen3:30b-a3b" in names
    core = [m for m in rec["models"] if m["set"] == "core"]
    assert len({m["family"] for m in core}) >= 3                                 # independent checkers exist
    assert all(not m["installed"] for m in rec["models"])
    r = authed.post("/api/models/pull", json={"name": "qwen3:4b"}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["queued"] is True
    assert authed.post("/api/models/pull", json={"name": "random/evil:latest"}, headers=MUTATE).status_code == 400


def test_grok_usage_labels_exact_and_estimated_figures(authed, db):
    r1 = budget.reserve(db, "factcheck.signoff")
    budget.commit(db, r1, cost_usd=0.03, model="xai:grok-4", input_tokens=1000, output_tokens=200,
                  cost_source="reported")
    r2 = budget.reserve(db, "polish.final")
    budget.commit(db, r2, cost_usd=None, model="xai:grok-4-fast")                # no cost → the estimate stands
    u = authed.get("/api/usage").json()
    assert u["today"]["calls"] == 2 and u["today"]["spent_usd"] == pytest.approx(0.04)
    assert u["cost_sources"] == {"reported": 1, "estimated": 1}
    assert u["budget"]["is_estimate"] is False and u["budget"]["remaining_today_usd"] == pytest.approx(1.96)
    assert u["credit"] is None                                                   # nothing entered yet
    assert {m["model"] for m in u["by_model"]} == {"xai:grok-4", "xai:grok-4-fast"}
    assert len(u["daily"]) == 30 and u["daily"][-1]["calls"] == 2
    assert authed.patch("/api/settings", json={"grok_credit_usd": 25.0}, headers=MUTATE).status_code == 200
    r3 = budget.reserve(db, "escalation.writer")
    budget.commit(db, r3, cost_usd=0.5, model="xai:grok-4-fast", cost_source="reported")
    c = authed.get("/api/usage").json()["credit"]
    assert c["is_estimate"] is True and c["estimated_remaining_usd"] == pytest.approx(24.5)
    assert authed.patch("/api/settings", json={"grok_credit_usd": None}, headers=MUTATE).status_code == 200
    assert authed.get("/api/usage").json()["credit"] is None
