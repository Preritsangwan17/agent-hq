"""ChatGPT through the Codex CLI (`codex exec`) — the third cloud provider next to the Claude CLI and xAI.

Same contract as ClaudeRunner: `available()` (`codex login status`, cached 10 min) and `run(prompt, schema,
system_prompt, model, max_budget_usd)` → ClaudeResult with output validated against the schema. Codex runs from an
empty sandbox directory with a minimal environment, a read-only sandbox, no session files, no user config (so no MCP
servers, profiles or hooks), shell/browser/app tools switched off, and the redacted prompt on stdin. Codex versions
reject flags and feature names they don't know, so the runner asks the installed CLI which ones it has
(`codex exec --help`, `codex features list`) and only passes those. Never any `--dangerously-*` flag.

Signed in with a ChatGPT plan the CLI reports tokens, not dollars, so the cost is estimated from
config/cloud_prices.yaml `openai` (notional spend, like Claude's) and counted against the same daily budget.
When Codex is not logged in the runner opens ONE Needs Prerit item, and only while ChatGPT is the provider in use.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from hq import settings as paths
from hq.llm.claude import ClaudeBadOutput, ClaudeBudgetExceeded, ClaudeError, ClaudeRateLimited, ClaudeResult, \
    ClaudeUnavailable
from hq.llm.json_utils import parse_and_validate, repair_message
from hq.llm.xai import price_for
from hq.util.redact import redact

AVAILABILITY_TTL_S = 600
TIMEOUT_S = 240
DEFAULT_MODEL = "default"          # Codex's own default: no --model flag
NEED_TITLE = "Log in to the ChatGPT (Codex) CLI"
LOGIN_HINT = "not logged in — run `codex login` in Terminal"
# Passed only when this Codex version lists them in `codex exec --help`.
OPTIONAL_FLAGS = ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--json", "--color")
# Tools a text-in/JSON-out call never needs; each is disabled when `codex features list` shows it switched on.
OFF_FEATURES = ("shell_tool", "unified_exec", "browser_use", "browser_use_external", "computer_use", "in_app_browser",
                "apps", "plugins", "hooks", "multi_agent", "image_generation", "view_image", "memories",
                "web_search_request", "js_repl")
AUTH_MARKERS = ("not logged in", "login required", "please log in", "codex login", "401", "unauthorized",
                "refresh token", "token expired", "authentication")
RATE_MARKERS = ("usage limit", "rate limit", "rate_limit", "429", "too many requests", "quota", "limit reached",
                "try again at")


def codex_binary() -> str | None:
    env = os.environ.get("HQ_CODEX_BIN")
    if env:
        return env
    found = shutil.which("codex")
    if found:
        return found
    for p in (Path("/opt/homebrew/bin/codex"), Path("/usr/local/bin/codex"), Path.home() / ".npm-global" / "bin" / "codex",
              Path.home() / ".local" / "bin" / "codex"):
        if p.exists():
            return str(p)
    return None


def sandbox_dir() -> Path:
    d = paths.DATA / "codex_sandbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def minimal_env(binary: str) -> dict[str, str]:
    """PATH, HOME (Codex keeps its login in ~/.codex), USER, LANG, CODEX_HOME. The npm `codex` is a node script, so
    its own directory (where Homebrew also puts node) goes first on PATH even under launchd's short PATH."""
    env = {k: os.environ[k] for k in ("PATH", "HOME", "USER", "LANG", "CODEX_HOME") if k in os.environ}
    here = str(Path(binary).parent)
    env["PATH"] = os.pathsep.join(dict.fromkeys([here, *env.get("PATH", "/usr/bin:/bin").split(os.pathsep)]))
    return env


def build_argv(binary: str, *, model: str, last_file: Path, flags: set[str], features_off: list[str]) -> list[str]:
    argv = [binary, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--cd", str(sandbox_dir()),
            "--output-last-message", str(last_file)]
    if "--json" in flags:
        argv.append("--json")
    if "--color" in flags:
        argv += ["--color", "never"]
    argv += [f for f in ("--ephemeral", "--ignore-user-config", "--ignore-rules") if f in flags]
    for feat in features_off:
        argv += ["--disable", feat]
    if model and model != DEFAULT_MODEL:
        argv += ["--model", model]
    argv.append("-")   # the prompt comes on stdin
    return argv


def full_prompt(system_prompt: str, prompt: str, schema: dict[str, Any]) -> str:
    """`codex exec` has no system-prompt flag: the instructions, the answer format and the task go in one message."""
    return (f"{system_prompt}\n\nAnswer with ONE JSON object that matches this JSON Schema and nothing else — no prose, "
            "no code fences. Do not run commands, open files or browse: everything you need is in this message.\n\n"
            f"JSON SCHEMA:\n{json.dumps(schema, separators=(',', ':'))}\n\n---\n\n{prompt}")


def parse_events(stdout: str) -> tuple[str, dict[str, Any], str | None]:
    """Last agent message, summed usage and the turn failure (if any) from `--json` JSONL. `error` events alone are
    retry notices ("Reconnecting… 2/5"); only `turn.failed` ends a turn."""
    text, usage, failed = "", {"input_tokens": 0, "output_tokens": 0}, None
    last_error = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = ev.get("type")
        item = ev.get("item") if isinstance(ev.get("item"), dict) else {}
        if kind == "item.completed" and item.get("type") == "agent_message":
            text = str(item.get("text") or "")
        elif kind == "turn.completed":
            u = ev.get("usage") or {}
            for k in ("input_tokens", "output_tokens"):
                usage[k] += int(u.get(k) or 0)
        elif kind == "turn.failed":
            err = ev.get("error")
            failed = str((err.get("message") if isinstance(err, dict) else err) or "turn failed")
        elif kind == "error":
            last_error = str(ev.get("message") or "")
    return text, usage, failed or (last_error if not text else None)


def classify(text: str) -> type[ClaudeError]:
    low = (text or "").lower()
    if any(m in low for m in RATE_MARKERS):
        return ClaudeRateLimited
    if any(m in low for m in AUTH_MARKERS):
        return ClaudeUnavailable
    return ClaudeError


def cost_of(model: str, usage: dict[str, Any]) -> float:
    pin, pout = price_for(model, "openai")
    return round((usage.get("input_tokens") or 0) * pin / 1e6 + (usage.get("output_tokens") or 0) * pout / 1e6, 6)


def _parse_logged_in(text: str, returncode: int | None) -> bool:
    low = (text or "").lower()
    if "not logged in" in low:
        return False
    return returncode == 0 and "logged in" in low


def ensure_login_need(conn: sqlite3.Connection, reason: str) -> str | None:
    """Exactly one open 'log in' decision item; returns its id when newly created."""
    from hq.db import repo, serializers
    from hq.db.conn import tx

    if conn.execute("SELECT 1 FROM needs_prerit WHERE title=? AND status IN ('open','snoozed')", (NEED_TITLE,)).fetchone():
        return None
    with tx(conn):
        need_id = repo.insert_need(conn, {
            "kind": "decision", "title": NEED_TITLE, "priority": 60, "est_minutes": 2,
            "instructions_md": (f"ChatGPT is unavailable ({reason}). Cloud sign-off, polish and escalations wait; local "
                                "models keep working.\n\nOpen Terminal on this Mac and run (install first with "
                                "`npm install -g @openai/codex` if `codex` is missing):\n\n```\ncodex login\n```\n\n"
                                "Sign in with your ChatGPT account. HQ re-checks every 10 minutes. Mark this done once "
                                "you've logged in — or switch ChatGPT off in Settings › Budget."),
            "answers_json": json.dumps([{"label": "Command", "value": "codex login", "copy": True}]),
        })
        need = serializers.need_json(repo.get_need_row(conn, need_id))
        repo.emit(conn, "needs.created", need["title"], level="warn", data={"need": need})
    return need_id


class CodexRunner:
    provider = "codex"

    def __init__(self, conn: sqlite3.Connection | None = None, binary: str | None = None):
        self.conn = conn
        self.binary = binary
        self._checked_at = 0.0
        self._available: bool | None = None
        self.reason: str | None = None
        self.logged_in = False
        self.version: str | None = None
        self.nag = True     # raise the "log in" Needs item only while ChatGPT is the provider in use
        self._caps: tuple[str, set[str], list[str]] | None = None   # (binary, exec flags, features to switch off)

    def _bin(self) -> str | None:
        return self.binary or codex_binary()

    async def _exec(self, binary: str, *args: str, stdin: bytes | None = None,
                    timeout: float = 20) -> tuple[int | None, str, str]:
        proc = await asyncio.create_subprocess_exec(
            binary, *args, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=minimal_env(binary),
            cwd=str(sandbox_dir()))
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        return proc.returncode, (out or b"").decode("utf-8", "replace"), (err or b"").decode("utf-8", "replace")

    async def capabilities(self, binary: str) -> tuple[set[str], list[str]]:
        if self._caps and self._caps[0] == binary:
            return self._caps[1], self._caps[2]
        flags: set[str] = set()
        off: list[str] = []
        try:
            _, out, err = await self._exec(binary, "exec", "--help")
            flags = set(re.findall(r"(--[a-z][a-z0-9-]+)", out + err)) & set(OPTIONAL_FLAGS)
            _, out, _ = await self._exec(binary, "features", "list")
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0] in OFF_FEATURES and parts[-1] == "true" and "removed" not in parts:
                    off.append(parts[0])
        except (OSError, asyncio.TimeoutError):
            pass
        self._caps = (binary, flags, off)
        return flags, off

    async def available(self, force: bool = False) -> bool:
        if not force and self._available is not None and time.monotonic() - self._checked_at < AVAILABILITY_TTL_S:
            return self._available
        self._checked_at = time.monotonic()
        binary = self._bin()
        if not binary:
            return self._set_unavailable("the codex CLI is not installed — `npm install -g @openai/codex`")
        try:
            code, out, err = await self._exec(binary, "login", "status")
        except (OSError, asyncio.TimeoutError) as exc:
            return self._set_unavailable(f"could not run codex login status: {exc}")
        if not _parse_logged_in(out + "\n" + err, code):
            return self._set_unavailable(LOGIN_HINT)
        try:
            _, v, _ = await self._exec(binary, "--version")
            self.version = v.strip().split()[-1] if v.strip() else None
        except (OSError, asyncio.TimeoutError):
            self.version = None
        self._caps = None   # re-read flags/features after a login check (the CLI may have been updated)
        self._available, self.logged_in, self.reason = True, True, None
        return True

    def _set_unavailable(self, reason: str) -> bool:
        self._available, self.logged_in, self.reason = False, False, reason
        if self.conn is not None and self.nag:
            ensure_login_need(self.conn, reason)
        return False

    def mark_unavailable(self, reason: str) -> None:
        self._checked_at = time.monotonic()
        self._set_unavailable(reason)

    async def _once(self, binary: str, prompt: str, model: str, timeout_s: float) -> tuple[str, dict[str, Any]]:
        flags, off = await self.capabilities(binary)
        last = sandbox_dir() / f"last-{uuid.uuid4().hex}.txt"
        argv = build_argv(binary, model=model, last_file=last, flags=flags, features_off=off)
        try:
            try:
                code, out, err = await self._exec(*argv, stdin=prompt.encode(), timeout=timeout_s)
            except asyncio.TimeoutError:
                raise ClaudeError(f"codex timed out after {timeout_s:.0f} s") from None
            except OSError as exc:
                raise ClaudeUnavailable(f"could not start codex: {exc}") from exc
            text, usage, failed = parse_events(out)
            if last.exists():
                text = last.read_text(encoding="utf-8", errors="replace").strip() or text
        finally:
            last.unlink(missing_ok=True)
        if failed or (code != 0 and not text):
            err_lines = err.strip().splitlines()
            detail = failed or (err_lines[-1] if err_lines else "") or out.strip()[-300:] or f"exit {code}"
            cls = classify(f"{failed or ''} {err} {out[-2000:]}")
            if cls is ClaudeUnavailable:
                self.mark_unavailable(LOGIN_HINT)
            exc = cls(f"codex: {str(detail)[:300]}")
            exc.cost_usd = cost_of(model, usage) if usage["input_tokens"] else None  # type: ignore[attr-defined]
            raise exc
        return text, usage

    async def run(self, prompt: str, *, schema: dict[str, Any], system_prompt: str, model: str = DEFAULT_MODEL,
                  max_budget_usd: float = 0.5, timeout_s: float = TIMEOUT_S, **_: Any) -> ClaudeResult:
        binary = self._bin()
        if not binary:
            raise ClaudeUnavailable("the codex CLI is not installed")
        model = model.removeprefix("codex:") or DEFAULT_MODEL
        message = full_prompt(redact(system_prompt, self.conn), redact(prompt, self.conn), schema)
        pin, _ = price_for(model, "openai")
        if len(message) / 3.2 * pin / 1e6 > max_budget_usd:
            raise ClaudeBudgetExceeded(f"prompt alone would exceed the ${max_budget_usd:.2f} per-call cap")
        t0 = time.monotonic()
        tin = tout = 0
        cost = 0.0
        errors: list[str] = []
        for attempt in range(2):   # one repair turn on invalid JSON, like the local models
            text, usage = await self._once(binary, message, model, timeout_s)
            tin, tout = tin + usage["input_tokens"], tout + usage["output_tokens"]
            cost += cost_of(model, usage)
            value, errors = parse_and_validate(text, schema)
            if not errors:
                return ClaudeResult(output=value, cost_usd=round(cost, 8), input_tokens=tin or None,
                                    output_tokens=tout or None, cache_read_tokens=None,
                                    duration_ms=(time.monotonic() - t0) * 1000, model=f"codex:{model}",
                                    subtype="success", raw={"version": self.version})
            if cost >= max_budget_usd:
                break
            message = (f"{message}\n\n---\n\nYOUR PREVIOUS ANSWER:\n{text[:4000]}\n\n{repair_message(errors, schema)}")
        bad = ClaudeBadOutput("codex output invalid: " + "; ".join(errors[:3]))
        bad.cost_usd = round(cost, 8)  # type: ignore[attr-defined]
        raise bad

    def state(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {"available": bool(self._available), "logged_in": self.logged_in, "reason": self.reason,
                "installed": self._bin() is not None, "version": self.version,
                "model": settings.get("codex_model", DEFAULT_MODEL),
                "signoff_model": settings.get("codex_signoff_model", DEFAULT_MODEL),
                "checked": self._available is not None}
