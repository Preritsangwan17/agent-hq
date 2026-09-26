"""Headless Claude Code runner (CONTRACT_B §1).

Claude runs ONLY with no tools, no MCP servers, no hooks, no slash commands and no session persistence, from an
empty sandbox directory with a minimal environment, the prompt on stdin, a per-call `--max-budget-usd` cap and a
JSON schema for the answer. A result is accepted only when `is_error` is false, `subtype == "success"` and
`structured_output` validates. Never `--bare`, never any permission-bypass flag.

When the CLI is not logged in the runner marks Claude unavailable, opens ONE Needs Prerit item ("Log in to the
Claude CLI") and re-checks at most every 10 minutes, so local-only work carries on.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hq import settings as paths
from hq.llm.json_utils import validate
from hq.util.redact import redact

AVAILABILITY_TTL_S = 600
TIMEOUT_S = 180
MODEL_ALIASES = {"sonnet", "opus", "haiku"}


class ClaudeError(Exception):
    kind = "error"


class ClaudeUnavailable(ClaudeError):
    kind = "auth"


class ClaudeBudgetExceeded(ClaudeError):
    kind = "budget"


class ClaudeRateLimited(ClaudeError):
    kind = "rate_limit"


class ClaudeBadOutput(ClaudeError):
    kind = "structured_output"


@dataclass
class ClaudeResult:
    output: Any
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    duration_ms: float
    model: str
    subtype: str
    raw: dict[str, Any] = field(default_factory=dict)


def claude_binary() -> str | None:
    env = os.environ.get("HQ_CLAUDE_BIN")
    if env:
        return env
    found = shutil.which("claude")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "claude"
    return str(local) if local.exists() else None


def sandbox_dir() -> Path:
    d = paths.DATA / "claude_sandbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def minimal_env() -> dict[str, str]:
    return {k: os.environ[k] for k in ("PATH", "HOME", "USER", "LANG") if k in os.environ}


def build_argv(binary: str, *, schema: dict[str, Any], system_prompt: str, model: str,
               max_budget_usd: float) -> list[str]:
    return [
        binary, "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema, separators=(",", ":")),
        "--tools", "",
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--settings", '{"disableAllHooks":true}',
        "--setting-sources", "project",
        "--disable-slash-commands",
        "--system-prompt", system_prompt,
        "--no-session-persistence",
        "--max-budget-usd", f"{max_budget_usd:.2f}",
        "--model", model,
    ]


AUTH_MARKERS = ("failed to authenticate", "not logged in", "invalid api key", "please run /login", "authentication",
                "oauth token", "401")
RATE_MARKERS = ("usage limit", "rate limit", "rate_limit", "429", "overloaded", "too many requests", "limit reached")


def classify_failure(text: str, subtype: str | None) -> type[ClaudeError]:
    low = (text or "").lower()
    if subtype and "budget" in subtype:
        return ClaudeBudgetExceeded
    if any(m in low for m in AUTH_MARKERS):
        return ClaudeUnavailable
    if any(m in low for m in RATE_MARKERS):
        return ClaudeRateLimited
    return ClaudeError


class ClaudeRunner:
    """One per worker. `available()` caches the login check; `run()` executes one budgeted call."""

    def __init__(self, conn: sqlite3.Connection | None = None, binary: str | None = None):
        self.conn = conn
        self.binary = binary
        self._checked_at = 0.0
        self._available: bool | None = None
        self.reason: str | None = None
        self.logged_in = False
        self.nag = True     # raise the "log in" Needs item (off while another cloud provider is in use)

    def _bin(self) -> str | None:
        return self.binary or claude_binary()

    async def available(self, force: bool = False) -> bool:
        if not force and self._available is not None and time.monotonic() - self._checked_at < AVAILABILITY_TTL_S:
            return self._available
        self._checked_at = time.monotonic()
        binary = self._bin()
        if not binary:
            return self._set_unavailable("the claude CLI is not installed")
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "auth", "status", stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=minimal_env(), cwd=str(sandbox_dir()))
            out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
        except (OSError, asyncio.TimeoutError) as exc:
            return self._set_unavailable(f"could not run claude auth status: {exc}")
        text = (out or b"").decode("utf-8", "replace") + (err or b"").decode("utf-8", "replace")
        logged_in = _parse_logged_in(text)
        if not logged_in:
            return self._set_unavailable("not logged in — run `claude auth login` in Terminal")
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

    async def run(self, prompt: str, *, schema: dict[str, Any], system_prompt: str, model: str = "sonnet",
                  max_budget_usd: float = 0.5, timeout_s: float = TIMEOUT_S) -> ClaudeResult:
        binary = self._bin()
        if not binary:
            raise ClaudeUnavailable("the claude CLI is not installed")
        argv = build_argv(binary, schema=schema, system_prompt=redact(system_prompt, self.conn), model=model,
                          max_budget_usd=max_budget_usd)
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=minimal_env(), cwd=str(sandbox_dir()))
        except OSError as exc:
            raise ClaudeUnavailable(f"could not start claude: {exc}") from exc
        try:
            out, err = await asyncio.wait_for(proc.communicate(redact(prompt, self.conn).encode()), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ClaudeError(f"claude timed out after {timeout_s:.0f} s") from None
        duration = (time.monotonic() - t0) * 1000
        stdout = (out or b"").decode("utf-8", "replace").strip()
        stderr = (err or b"").decode("utf-8", "replace").strip()
        try:
            data = json.loads(stdout.splitlines()[-1] if stdout else "{}")
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict) or not data:
            cls = classify_failure(stdout + " " + stderr, None)
            if cls is ClaudeUnavailable:
                self.mark_unavailable("not logged in — run `claude auth login` in Terminal")
            raise cls(f"claude exited {proc.returncode}: {(stderr or stdout)[:300]}")
        subtype = str(data.get("subtype") or "")
        usage = data.get("usage") or {}
        if data.get("is_error") or subtype != "success":
            cls = classify_failure(f"{data.get('result', '')} {stderr}", subtype)
            if cls is ClaudeUnavailable:
                self.mark_unavailable("not logged in — run `claude auth login` in Terminal")
            err_obj = cls(f"claude {subtype or 'error'}: {str(data.get('result') or stderr)[:300]}")
            err_obj.cost_usd = data.get("total_cost_usd")  # type: ignore[attr-defined]
            raise err_obj
        output = data.get("structured_output")
        errors = ["missing structured_output"] if output is None else validate(output, schema)
        if errors:
            bad = ClaudeBadOutput("structured_output invalid: " + "; ".join(errors[:3]))
            bad.cost_usd = data.get("total_cost_usd")  # type: ignore[attr-defined]
            raise bad
        return ClaudeResult(output=output, cost_usd=data.get("total_cost_usd"),
                            input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                            cache_read_tokens=usage.get("cache_read_input_tokens"), duration_ms=duration, model=model,
                            subtype=subtype, raw={k: data.get(k) for k in ("session_id", "num_turns", "duration_ms")})

    def state(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {"available": bool(self._available), "logged_in": self.logged_in, "reason": self.reason,
                "model": settings.get("claude_model", "sonnet"),
                "signoff_model": settings.get("claude_signoff_model", "opus"),
                "checked": self._available is not None}


def _parse_logged_in(text: str) -> bool:
    try:
        data = json.loads(text.strip().splitlines()[0]) if text.strip().startswith("{") else json.loads(text)
        if isinstance(data, dict):
            for key in ("loggedIn", "logged_in", "authenticated"):
                if key in data:
                    return bool(data[key])
    except (json.JSONDecodeError, IndexError):
        pass
    low = text.lower()
    if "not logged in" in low or "loggedin: false" in low or '"loggedin":false' in low.replace(" ", ""):
        return False
    return "logged in" in low or "authenticated" in low


LOGIN_NEED_TITLE = "Log in to the Claude CLI"


def ensure_login_need(conn: sqlite3.Connection, reason: str) -> str | None:
    """Exactly one open 'log in' decision item; returns its id when newly created."""
    from hq.db import repo, serializers
    from hq.db.conn import tx

    exists = conn.execute("SELECT id FROM needs_prerit WHERE title=? AND status IN ('open','snoozed')",
                          (LOGIN_NEED_TITLE,)).fetchone()
    if exists:
        return None
    with tx(conn):
        need_id = repo.insert_need(conn, {
            "kind": "decision", "title": LOGIN_NEED_TITLE, "priority": 60, "est_minutes": 1,
            "instructions_md": (f"Claude is unavailable ({reason}). Sign-off, polish and the Strategist wait; local "
                                "models keep working.\n\nOpen Terminal on this Mac and run:\n\n"
                                "```\nclaude auth login\n```\n\nHQ re-checks every 10 minutes. Mark this done "
                                "once you've logged in."),
            "answers_json": json.dumps([{"label": "Command", "value": "claude auth login", "copy": True}]),
        })
        need = serializers.need_json(repo.get_need_row(conn, need_id))
        repo.emit(conn, "needs.created", need["title"], level="warn", data={"need": need})
        repo.emit(conn, "claude.status", f"Claude unavailable: {reason}", level="warn",
                  data={"available": False, "reason": reason})
    return need_id
