"""On/off switches per model source (local, Claude CLI, xAI, ChatGPT via the Codex CLI), the preferred-then-next
cloud order, resting a provider after a usage limit, and the Codex runner against a fake `codex` shim. Nothing here
runs a real CLI or reaches a model: switched-off providers must not even be asked for their login status."""
from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from hq import settings as paths
from hq.db.conn import tx
from hq.db.seed import SettingError, get_settings, set_settings, validate_patch
from hq.llm import cloud
from hq.llm.claude import ClaudeBadOutput, ClaudeRateLimited, ClaudeResult, ClaudeUnavailable
from hq.llm.codex import NEED_TITLE, CodexRunner, parse_events
from hq.llm.router import EscalationExhausted, Router

SCHEMA = {"type": "object", "required": ["verdict"], "properties": {"verdict": {"enum": ["yes", "no"]}}}
MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


class Fake:
    """A cloud runner that counts login checks and calls."""

    def __init__(self, ok: bool = True, exc: Exception | None = None):
        self.ok, self.exc = ok, exc
        self.checks = self.calls = 0
        self.nag = True
        self.reason: str | None = None

    async def available(self, force: bool = False) -> bool:
        self.checks += 1
        self.reason = None if self.ok else "not logged in"
        return self.ok

    async def run(self, prompt: str, *, schema: dict[str, Any], system_prompt: str, model: str,
                  max_budget_usd: float = 0.5, **_: Any) -> ClaudeResult:
        self.calls += 1
        if self.exc:
            raise self.exc
        return ClaudeResult(output={"verdict": "yes"}, cost_usd=0.01, input_tokens=10, output_tokens=5,
                            cache_read_tokens=None, duration_ms=1.0, model=model, subtype="success")

    def state(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {"available": self.ok and self.checks > 0, "reason": self.reason, "checked": self.checks > 0}

    def mark_unavailable(self, reason: str) -> None:
        self.ok, self.reason = False, reason


def runner(db, **fakes: Fake) -> cloud.CloudRunner:
    f = {"claude": Fake(), "xai": Fake(), "codex": Fake(), **fakes}
    return cloud.CloudRunner(db, claude=f["claude"], xai=f["xai"], codex=f["codex"])  # type: ignore[arg-type]


def put(db, **values: Any) -> None:
    with tx(db):
        set_settings(db, values)


@pytest.fixture(autouse=True)
def _no_xai_key(monkeypatch):
    monkeypatch.delenv("HQ_XAI_API_KEY", raising=False)


# ── settings and order ──────────────────────────────────────────────────────────────────────────────
def test_switches_are_editable_and_default_on(db):
    s = get_settings(db)
    assert all(s[k] is True for k in cloud.SWITCH.values())
    assert validate_patch({"llm_codex_enabled": False, "cloud_llm": "codex", "codex_model": "gpt-5.5"}) == {
        "llm_codex_enabled": False, "cloud_llm": "codex", "codex_model": "gpt-5.5"}
    with pytest.raises(SettingError):
        validate_patch({"llm_local_enabled": "no"})


def test_order_puts_the_preferred_provider_first_and_drops_switched_off_ones(db, monkeypatch):
    s = get_settings(db)
    assert cloud.order(s) == ["claude", "codex", "xai"] and cloud.main_model(s) == "sonnet"
    monkeypatch.setenv("HQ_XAI_API_KEY", "xai-" + "k" * 40)
    assert cloud.order(get_settings(db))[0] == "claude"                   # API key alone does not prioritize paid work
    put(db, cloud_llm="codex")
    assert cloud.order(get_settings(db)) == ["codex", "claude", "xai"]
    assert cloud.main_model(get_settings(db)) == "codex:default"
    put(db, llm_codex_enabled=False)                                        # preferred but off → next one
    s = get_settings(db)
    assert cloud.provider(s) == "claude" and "codex:default" not in cloud.signoff_candidates(s)
    put(db, llm_xai_enabled=False, llm_claude_enabled=False)
    s = get_settings(db)
    assert cloud.order(s) == [] and cloud.provider(s) is None and cloud.main_model(s) is None
    assert cloud.signoff_candidates(s) == []


# ── the runner never touches a switched-off provider ───────────────────────────────────────────────
async def test_switched_off_provider_is_never_checked_or_called(db):
    claude, codex = Fake(), Fake()
    r = runner(db, claude=claude, codex=codex)
    put(db, llm_claude_enabled=False)
    assert await r.available(model="sonnet") is False and "switched off" in (r.reason or "")
    with pytest.raises(ClaudeUnavailable):
        await r.run("p", schema=SCHEMA, system_prompt="s", model="opus")
    await r.check_all()
    assert claude.checks == 0 and claude.calls == 0
    assert codex.checks == 1                                               # the switched-on ones are checked
    st = r.state(get_settings(db))
    assert st["providers"]["claude"]["enabled"] is False and st["provider"] == "codex"


async def test_pick_falls_back_to_the_next_switched_on_provider(db):
    s = get_settings(db)
    r = runner(db, claude=Fake(ok=False))
    assert await cloud.pick(r, s) == "codex:default"
    assert await cloud.pick(r, s, exclude={"codex:default"}) == "xai:grok-4-fast"   # lineage skips an author
    put(db, llm_codex_enabled=False, llm_xai_enabled=False)
    s = get_settings(db)
    assert await cloud.pick(r, s) is None and "no switched-on cloud model" in cloud.why_none(r, s)
    put(db, llm_claude_enabled=False)
    assert cloud.why_none(r, get_settings(db)) == cloud.ALL_OFF


async def test_a_usage_limit_rests_the_provider_so_no_more_calls_are_spent(db):
    claude, codex = Fake(exc=ClaudeRateLimited("usage limit reached")), Fake()
    r = runner(db, claude=claude, codex=codex)
    with pytest.raises(ClaudeRateLimited):
        await r.run("p", schema=SCHEMA, system_prompt="s", model="sonnet")
    assert claude.calls == 1
    assert await r.available(model="sonnet") is False and "resting" in (r.reason or "")
    assert await cloud.pick(r, get_settings(db)) == "codex:default"         # others carry on
    with pytest.raises(ClaudeUnavailable):
        await r.run("p", schema=SCHEMA, system_prompt="s", model="sonnet")
    assert claude.calls == 1                                                # no second call while resting
    await r.check_all()
    assert r.state(get_settings(db))["providers"]["claude"]["resting"] is True
    r.resting["claude"] = (0.0, "over")                                     # the rest is over
    assert await r.available(model="sonnet") is True


# ── router ───────────────────────────────────────────────────────────────────────────────────────────
async def test_legacy_local_off_still_runs_local_and_never_spends_cloud(db):
    from tests.unit.test_llm import FakeManager, make_chat, _setup_roles
    _setup_roles(db)
    put(db, llm_local_enabled=False)
    mgr, claude = FakeManager(), Fake()
    chat = make_chat({"mlx:q/Qwen3-4B": ['{"verdict":"yes"}']})
    router = Router(db, mgr, runner(db, claude=claude), chat_fn=chat)
    res = await router.route("eligibility", MSGS, SCHEMA, allow_claude=False)
    assert res.model_id == "mlx:q/Qwen3-4B"
    assert claude.calls == 0 and mgr.used == ["mlx:q/Qwen3-4B"]
    assert get_settings(db)["llm_local_enabled"] is True


async def test_router_escalates_to_chatgpt_when_claude_is_off(db):
    put(db, llm_claude_enabled=False, cloud_llm="auto")
    codex = Fake()
    res = await Router(db, None, runner(db, codex=codex)).route("summarizer", MSGS, SCHEMA)
    assert res.model_id == "codex:default" and codex.calls == 1
    row = db.execute("SELECT adapter FROM agent_runs ORDER BY started_at DESC").fetchone()
    assert row["adapter"] == "codex"


async def test_everything_off_means_no_cloud_call(db):
    put(db, llm_claude_enabled=False, llm_xai_enabled=False, llm_codex_enabled=False)
    fakes = {k: Fake() for k in ("claude", "xai", "codex")}
    with pytest.raises(EscalationExhausted, match="switched off"):
        await Router(db, None, runner(db, **fakes)).route("summarizer", MSGS, SCHEMA)
    assert all(f.calls == 0 and f.checks == 0 for f in fakes.values())


def test_local_cannot_be_disabled(db):
    from hq.models.manager import ModelManager
    with pytest.raises(SettingError, match="always ON"):
        validate_patch({"llm_local_enabled": False})
    put(db, llm_local_enabled=False)
    assert not ModelManager(db).local_off()


# ── the Codex runner (fake `codex`) ─────────────────────────────────────────────────────────────────
SHIM = r'''#!{python}
import json, os, sys
state = os.path.dirname(os.path.abspath(__file__))
mode = open(os.path.join(state, "mode")).read().strip()
args = sys.argv[1:]
with open(os.path.join(state, "calls.jsonl"), "a") as f:
    f.write(json.dumps({{"args": args, "path": os.environ.get("PATH", "")}}) + "\n")
if args[:2] == ["login", "status"]:
    if mode == "logged_out":
        print("Not logged in", file=sys.stderr); sys.exit(1)
    print("Logged in using ChatGPT", file=sys.stderr); sys.exit(0)
if args == ["--version"]:
    print("codex-cli 0.137.0"); sys.exit(0)
if args[:2] == ["exec", "--help"]:
    print("Usage: codex exec [OPTIONS] [PROMPT]\n  --json\n  --color <COLOR>\n  --ephemeral\n  --ignore-user-config\n"
          "  -o, --output-last-message <FILE>"); sys.exit(0)
if args[:2] == ["features", "list"]:
    print("apps                removed      true\nshell_tool          stable       true\n"
          "unified_exec        stable       true\nweb_search_request  deprecated   false\n"); sys.exit(0)
prompt = sys.stdin.read()
count_file = os.path.join(state, "count")
n = int(open(count_file).read()) + 1 if os.path.exists(count_file) else 1
open(count_file, "w").write(str(n))
open(os.path.join(state, "stdin.txt"), "a").write(prompt + "\n=====\n")
last = args[args.index("--output-last-message") + 1]
emit = lambda ev: print(json.dumps(ev), flush=True)
emit({{"type": "thread.started", "thread_id": "t1"}})
emit({{"type": "turn.started"}})
if mode == "limit":
    emit({{"type": "turn.failed", "error": {{"message": "You've hit your usage limit. Try again at 5:00 PM."}}}}); sys.exit(1)
if mode == "expired":
    emit({{"type": "turn.failed", "error": {{"message": "401 Unauthorized: refresh token expired; run codex login"}}}}); sys.exit(1)
answer = {{"ok": '{{"verdict": "yes"}}', "bad": "I think yes", "repair": '{{"verdict": "maybe"}}' if n == 1 else '{{"verdict": "no"}}'}}[mode]
emit({{"type": "error", "message": "Reconnecting... 1/5"}})
emit({{"type": "item.completed", "item": {{"id": "i1", "type": "agent_message", "text": answer}}}})
emit({{"type": "turn.completed", "usage": {{"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 100}}}})
open(last, "w").write(answer)
'''


@pytest.fixture
def codex_shim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hq_env) -> Path:
    d = tmp_path / "codexbin"
    d.mkdir()
    exe = d / "codex"
    exe.write_text(SHIM.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    (d / "mode").write_text("ok")
    monkeypatch.setenv("HQ_CODEX_BIN", str(exe))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    return d


def calls(d: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (d / "calls.jsonl").read_text().splitlines()]


async def test_codex_runs_isolated_with_only_the_flags_this_version_knows(db, codex_shim, monkeypatch):
    monkeypatch.setenv("HQ_SESSION_SECRET", "s" * 64)
    r = CodexRunner(db)
    assert await r.available() is True and r.version == "0.137.0"
    res = await r.run("Check this. Secret: " + "s" * 64, schema=SCHEMA, system_prompt="You check.",
                      model="codex:default", max_budget_usd=0.3)
    assert res.output == {"verdict": "yes"} and res.model == "codex:default"
    assert res.input_tokens == 1000 and res.cost_usd == pytest.approx(1000 * 1.25 / 1e6 + 100 * 10 / 1e6)
    exec_call = next(c for c in calls(codex_shim) if c["args"][:1] == ["exec"] and "--help" not in c["args"])
    argv = exec_call["args"]
    assert argv[argv.index("--sandbox") + 1] == "read-only" and argv[-1] == "-"
    assert "--skip-git-repo-check" in argv and "--json" in argv and "--ephemeral" in argv
    assert "--ignore-user-config" in argv and "--ignore-rules" not in argv    # not in this version's --help
    disabled = [argv[i + 1] for i, a in enumerate(argv) if a == "--disable"]
    assert disabled == ["shell_tool", "unified_exec"]                         # removed/already-off ones skipped
    assert "--model" not in argv                                              # "default" = Codex's own model
    assert not any("dangerously" in a or "bypass" in a for a in argv)
    assert exec_call["path"].split(":")[0] == str(codex_shim)                 # node next to codex is found
    sent = (codex_shim / "stdin.txt").read_text()
    assert "s" * 64 not in sent and "You check." in sent and '"verdict"' in sent
    assert not list((paths.DATA / "codex_sandbox").glob("last-*"))           # temp answer file removed


async def test_codex_named_model_and_one_repair_turn(db, codex_shim):
    (codex_shim / "mode").write_text("repair")
    res = await CodexRunner(db).run("p", schema=SCHEMA, system_prompt="s", model="codex:gpt-5.5")
    assert res.output == {"verdict": "no"} and res.model == "codex:gpt-5.5"
    execs = [c["args"] for c in calls(codex_shim) if c["args"][:1] == ["exec"] and "--help" not in c["args"]]
    assert len(execs) == 2 and execs[0][execs[0].index("--model") + 1] == "gpt-5.5"
    assert "YOUR PREVIOUS ANSWER" in (codex_shim / "stdin.txt").read_text().split("=====")[1]


async def test_codex_bad_output_after_repair_is_rejected_with_its_cost(db, codex_shim):
    (codex_shim / "mode").write_text("bad")
    with pytest.raises(ClaudeBadOutput) as ei:
        await CodexRunner(db).run("p", schema=SCHEMA, system_prompt="s")
    assert getattr(ei.value, "cost_usd", 0) > 0


async def test_codex_usage_limit_and_expired_login(db, codex_shim):
    (codex_shim / "mode").write_text("limit")
    with pytest.raises(ClaudeRateLimited):
        await CodexRunner(db).run("p", schema=SCHEMA, system_prompt="s")
    (codex_shim / "mode").write_text("expired")
    r = CodexRunner(db)
    r.nag = False
    with pytest.raises(ClaudeUnavailable):
        await r.run("p", schema=SCHEMA, system_prompt="s")
    assert r.reason and "codex login" in r.reason


async def test_logged_out_codex_asks_once_and_only_while_it_is_the_provider_in_use(db, codex_shim):
    (codex_shim / "mode").write_text("logged_out")
    quiet = CodexRunner(db)
    quiet.nag = False
    assert await quiet.available(force=True) is False and "codex login" in (quiet.reason or "")
    assert db.execute("SELECT COUNT(*) FROM needs_prerit WHERE title=?", (NEED_TITLE,)).fetchone()[0] == 0
    loud = CodexRunner(db)
    assert await loud.available(force=True) is False
    assert await loud.available(force=True) is False
    assert db.execute("SELECT COUNT(*) FROM needs_prerit WHERE title=? AND status='open'",
                      (NEED_TITLE,)).fetchone()[0] == 1


async def test_codex_missing_binary_is_just_unavailable(db):
    r = CodexRunner(db)       # conftest points HQ_CODEX_BIN at a path that doesn't exist
    r.nag = False
    assert await r.available(force=True) is False


def test_parse_events_ignores_retry_notices():
    out = "\n".join(json.dumps(e) for e in [
        {"type": "error", "message": "Reconnecting... 2/5"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": '{"verdict":"yes"}'}},
        {"type": "turn.completed", "usage": {"input_tokens": 7, "output_tokens": 3}}])
    assert parse_events("WARNING: noise\n" + out) == ('{"verdict":"yes"}', {"input_tokens": 7, "output_tokens": 3}, None)
    assert parse_events(json.dumps({"type": "turn.failed", "error": {"message": "boom"}}))[2] == "boom"
