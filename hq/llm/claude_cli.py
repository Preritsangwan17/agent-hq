"""Claude CLI runner — optional subscription provider (switch: `claude_cli_enabled`).

Claude runs ONLY with no tools, no MCP servers, no hooks, no slash commands and no session persistence, from an
empty sandbox directory with a minimal environment, the (redacted) prompt on stdin and a JSON schema for the answer.
A result is accepted only when `is_error` is false, `subtype == "success"` and `structured_output` validates.

Calls draw on the Claude plan's usage windows, not on HQ's Grok budget: HQ records them at $0 with the CLI's
API-equivalent figure kept as "notional". A "usage limit reached" answer pauses this provider until the reset.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from hq.llm.cli_common import LimitTracker, looks_rate_limited, sandbox_dir
from hq.llm.errors import CloudBadOutput, CloudBudgetExceeded, CloudError, CloudRateLimited, CloudResult, \
    CloudUnavailable, minimal_env
from hq.llm.json_utils import validate
from hq.util.redact import redact

AVAILABILITY_TTL_S = 600
TIMEOUT_S = 180
PROVIDER = "claude"
LABEL = "Claude (CLI)"
LOGIN_NEED_TITLE = "Log in to the Claude CLI"
AUTH_MARKERS = ("failed to authenticate", "not logged in", "invalid api key", "please run /login", "authentication",
                "oauth token", "401")


def claude_binary() -> str | None:
    env = os.environ.get("HQ_CLAUDE_BIN")
    if env:
        return env
    found = shutil.which("claude")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "claude"
    return str(local) if local.exists() else None


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


def classify_failure(text: str, subtype: str | None) -> type[CloudError]:
    low = (text or "").lower()
    if subtype and "budget" in subtype:
        return CloudBudgetExceeded
    if any(m in low for m in AUTH_MARKERS):
        return CloudUnavailable
    if looks_rate_limited(low) or "overloaded" in low:
        return CloudRateLimited
    return CloudError


class ClaudeCliRunner:
    provider = PROVIDER

    def __init__(self, conn: sqlite3.Connection | None = None, binary: str | None = None):
        self.conn = conn
        self.binary = binary
        self._checked_at = 0.0
        self._available: bool | None = None
        self.reason: str | None = None
        self.installed = False
        self.nag = False     # "log in" Needs item only while Prerit has this provider switched on
        self.limits = LimitTracker("reported by the Claude CLI")

    def _bin(self) -> str | None:
        return self.binary or claude_binary()

    async def available(self, force: bool = False) -> bool:
        if self.limits.blocked():
            self.reason = f"usage limit reached — resets {self.limits.limited_until}"
            return False
        if not force and self._available is not None and time.monotonic() - self._checked_at < AVAILABILITY_TTL_S:
            return self._available
        self._checked_at = time.monotonic()
        binary = self._bin()
        self.installed = bool(binary)
        if not binary:
            return self._set_unavailable("the claude CLI is not installed", nag=False)
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "auth", "status", stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=minimal_env(), cwd=str(sandbox_dir("claude")))
            out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
        except (OSError, asyncio.TimeoutError) as exc:
            return self._set_unavailable(f"could not run claude auth status: {exc}")
        text = (out or b"").decode("utf-8", "replace") + (err or b"").decode("utf-8", "replace")
        if not _parse_logged_in(text):
            return self._set_unavailable("not logged in — run `claude auth login` in Terminal")
        self._available, self.reason = True, None
        return True

    def _set_unavailable(self, reason: str, *, nag: bool = True) -> bool:
        self._available, self.reason = False, reason
        if self.conn is not None and self.nag and nag:
            ensure_login_need(self.conn, reason)
        return False

    def mark_unavailable(self, reason: str) -> None:
        self._checked_at = time.monotonic()
        self._set_unavailable(reason)

    async def run(self, prompt: str, *, schema: dict[str, Any], system_prompt: str, model: str = "sonnet",
                  max_budget_usd: float = 0.5, timeout_s: float = TIMEOUT_S, **_: Any) -> CloudResult:
        binary = self._bin()
        if not binary:
            raise CloudUnavailable("the claude CLI is not installed")
        model = model.removeprefix("claude:")
        argv = build_argv(binary, schema=schema, system_prompt=redact(system_prompt, self.conn), model=model,
                          max_budget_usd=max_budget_usd)
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=minimal_env(), cwd=str(sandbox_dir("claude")))
        except OSError as exc:
            raise CloudUnavailable(f"could not start claude: {exc}") from exc
        try:
            out, err = await asyncio.wait_for(proc.communicate(redact(prompt, self.conn).encode()), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise CloudError(f"claude timed out after {timeout_s:.0f} s") from None
        duration = (time.monotonic() - t0) * 1000
        stdout = (out or b"").decode("utf-8", "replace").strip()
        stderr = (err or b"").decode("utf-8", "replace").strip()
        try:
            data = json.loads(stdout.splitlines()[-1] if stdout else "{}")
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict) and data:
            self.limits.saw_json(data)
        if not isinstance(data, dict) or not data:
            self._fail(classify_failure(stdout + " " + stderr, None), f"claude exited {proc.returncode}: "
                                                                        f"{(stderr or stdout)[:300]}")
        subtype = str(data.get("subtype") or "")
        usage = data.get("usage") or {}
        notional = data.get("total_cost_usd")
        if data.get("is_error") or subtype != "success":
            self._fail(classify_failure(f"{data.get('result', '')} {stderr}", subtype),
                       f"claude {subtype or 'error'}: {str(data.get('result') or stderr)[:300]}")
        output = data.get("structured_output")
        errors = ["missing structured_output"] if output is None else validate(output, schema)
        if errors:
            raise CloudBadOutput("structured_output invalid: " + "; ".join(errors[:3]))
        return CloudResult(output=output, cost_usd=0.0, input_tokens=usage.get("input_tokens"),
                           output_tokens=usage.get("output_tokens"),
                           cache_read_tokens=usage.get("cache_read_input_tokens"), duration_ms=duration,
                           model=f"claude:{model}", subtype=subtype, cost_source="subscription",
                           raw={"notional_usd": notional, "session_id": data.get("session_id")})

    def _fail(self, cls: type[CloudError], message: str) -> None:
        if cls is CloudUnavailable:
            self.mark_unavailable("not logged in — run `claude auth login` in Terminal")
        if cls is CloudRateLimited:
            self.limits.saw_limit(message)
        raise cls(message)

    def state(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {"available": bool(self._available) and not self.limits.blocked(), "reason": self.reason,
                "installed": self.installed or bool(self._bin()), "checked": self._available is not None,
                "model": settings.get("claude_cli_model", "sonnet"),
                "strong_model": settings.get("claude_cli_strong_model", "opus"), "limits": self.limits.state()}


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


def ensure_login_need(conn: sqlite3.Connection, reason: str) -> str | None:
    """Exactly one open 'log in' decision item; returns its id when newly created."""
    from hq.db import repo, serializers
    from hq.db.conn import tx

    if conn.execute("SELECT id FROM needs_prerit WHERE title=? AND status IN ('open','snoozed')",
                    (LOGIN_NEED_TITLE,)).fetchone():
        return None
    with tx(conn):
        need_id = repo.insert_need(conn, {
            "kind": "decision", "title": LOGIN_NEED_TITLE, "priority": 50, "est_minutes": 1,
            "instructions_md": (f"The Claude CLI is switched on in HQ but unavailable ({reason}). Local models and "
                                "the other providers keep working.\n\nOpen Terminal on this Mac and run:\n\n"
                                "```\nclaude auth login\n```\n\nHQ re-checks every 10 minutes. Or switch the "
                                "Claude CLI off in Settings › AI & budget."),
            "answers_json": json.dumps([{"label": "Command", "value": "claude auth login", "copy": True}]),
        })
        need = serializers.need_json(repo.get_need_row(conn, need_id))
        repo.emit(conn, "needs.created", need["title"], level="warn", data={"need": need})
    return need_id
