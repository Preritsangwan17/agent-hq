"""ChatGPT's Codex CLI runner — optional subscription provider (switch: `codex_cli_enabled`).

Uses the `codex` CLI logged in with Prerit's ChatGPT account (`codex login`). Each call runs `codex exec` in an empty
read-only sandbox directory with a minimal environment, the (redacted) prompt on stdin, and asks for JSON matching
the task's schema; the answer is validated like every other model's. Calls draw on the ChatGPT plan's usage windows,
not on HQ's Grok budget. When the CLI's JSON events carry a rate-limit snapshot (percent of the 5-hour / weekly
window used), HQ shows it as "reported by Codex CLI"; a "usage limit" error pauses this provider until the reset.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from hq.llm.cli_common import LimitTracker, looks_rate_limited, sandbox_dir
from hq.llm.errors import CloudBadOutput, CloudError, CloudRateLimited, CloudResult, CloudUnavailable, minimal_env
from hq.llm.json_utils import parse_and_validate
from hq.util.redact import redact

AVAILABILITY_TTL_S = 600
TIMEOUT_S = 240
PROVIDER = "codex"
LABEL = "ChatGPT (Codex CLI)"
LOGIN_NEED_TITLE = "Log in to the Codex CLI (ChatGPT)"
AUTH_MARKERS = ("not logged in", "please log in", "codex login", "unauthorized", "401", "authentication")
PREAMBLE = ("Answer directly. Do not run commands, read files or use tools. Reply with ONLY the JSON object the "
            "instructions ask for.")


def codex_binary() -> str | None:
    env = os.environ.get("HQ_CODEX_BIN")
    if env:
        return env
    found = shutil.which("codex")
    if found:
        return found
    for p in (Path("/opt/homebrew/bin/codex"), Path("/usr/local/bin/codex"), Path.home() / ".local" / "bin" / "codex"):
        if p.exists():
            return str(p)
    return None


def build_argv(binary: str, *, workdir: Path, schema_path: Path | None, out_path: Path, model: str | None) -> list[str]:
    argv = [binary, "exec", "--json", "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never",
            "-C", str(workdir), "--output-last-message", str(out_path)]
    if schema_path is not None:
        argv += ["--output-schema", str(schema_path)]
    if model:
        argv += ["-m", model]
    return argv + ["-"]


def _events(stdout: str) -> list[dict[str, Any]]:
    out = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _message_text(events: list[dict[str, Any]]) -> str:
    """The last agent message, across the old ({msg: {type: agent_message}}) and new ({item: {type:
    agent_message}}) JSON event formats."""
    text = ""
    for e in events:
        item = e.get("item") if isinstance(e.get("item"), dict) else None
        msg = e.get("msg") if isinstance(e.get("msg"), dict) else None
        if item and item.get("type") in ("agent_message", "assistant_message") and item.get("text"):
            text = str(item["text"])
        elif msg and msg.get("type") == "agent_message" and msg.get("message"):
            text = str(msg["message"])
    return text


def _usage(events: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    tin = tout = None
    for e in events:
        u = e.get("usage") if isinstance(e.get("usage"), dict) else None
        msg = e.get("msg") if isinstance(e.get("msg"), dict) else {}
        info = msg.get("info") if isinstance(msg.get("info"), dict) else {}
        last = info.get("last_token_usage") or info.get("total_token_usage")
        src = u or (last if isinstance(last, dict) else None)
        if src:
            tin = src.get("input_tokens", tin)
            tout = src.get("output_tokens", tout)
    return tin, tout


def _errors(events: list[dict[str, Any]]) -> str:
    parts = []
    for e in events:
        t = str(e.get("type") or (e.get("msg") or {}).get("type") or "")
        if t in ("error", "turn.failed", "stream_error"):
            err = e.get("error") if isinstance(e.get("error"), dict) else e.get("msg") or e
            parts.append(str((err or {}).get("message") or err))
    return " ".join(parts)


class CodexCliRunner:
    provider = PROVIDER

    def __init__(self, conn: sqlite3.Connection | None = None, binary: str | None = None):
        self.conn = conn
        self.binary = binary
        self._checked_at = 0.0
        self._available: bool | None = None
        self.reason: str | None = None
        self.installed = False
        self.nag = False
        self.limits = LimitTracker("reported by the Codex CLI")
        self.schema_flag = True    # older CLIs without --output-schema: prompt-only JSON + validation

    def _bin(self) -> str | None:
        return self.binary or codex_binary()

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
            return self._set_unavailable("the codex CLI is not installed (brew install codex)", nag=False)
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "login", "status", stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=minimal_env(), cwd=str(sandbox_dir("codex")))
            out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
        except (OSError, asyncio.TimeoutError) as exc:
            return self._set_unavailable(f"could not run codex login status: {exc}")
        text = ((out or b"") + b" " + (err or b"")).decode("utf-8", "replace").lower()
        if "not logged in" in text or ("logged in" not in text and proc.returncode != 0):
            return self._set_unavailable("not logged in — run `codex login` in Terminal (sign in with ChatGPT)")
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

    async def run(self, prompt: str, *, schema: dict[str, Any], system_prompt: str, model: str | None = None,
                  max_budget_usd: float = 0.5, timeout_s: float = TIMEOUT_S, **_: Any) -> CloudResult:
        binary = self._bin()
        if not binary:
            raise CloudUnavailable("the codex CLI is not installed")
        name = (model or "").removeprefix("codex:")
        name = None if name in ("", "default") else name
        work = sandbox_dir("codex")
        tag = uuid.uuid4().hex[:12]
        schema_path, out_path = work.parent / f"codex_schema_{tag}.json", work.parent / f"codex_out_{tag}.txt"
        schema_path.write_text(json.dumps(_strict(schema)))
        text_in = (f"{PREAMBLE}\n\nINSTRUCTIONS:\n{redact(system_prompt, self.conn)}\n\nTASK:\n{redact(prompt, self.conn)}"
                   f"\n\nJSON SCHEMA:\n{json.dumps(schema)}")
        t0 = time.monotonic()
        try:
            stdout, stderr, code = await self._exec(build_argv(binary, workdir=work, out_path=out_path, model=name,
                                                               schema_path=schema_path if self.schema_flag else None),
                                                    text_in, timeout_s)
            if code != 0 and self.schema_flag and "schema" in f"{stderr} {_errors(_events(stdout))}".lower():
                self.schema_flag = False   # old CLI without --output-schema, or a schema it won't accept
                stdout, stderr, code = await self._exec(build_argv(binary, workdir=work, out_path=out_path, model=name,
                                                                   schema_path=None), text_in, timeout_s)
            events = _events(stdout)
            for e in events:
                self.limits.saw_json(e)
            answer = out_path.read_text().strip() if out_path.exists() else ""
            answer = answer or _message_text(events)
        finally:
            for p in (schema_path, out_path):
                p.unlink(missing_ok=True)
        problems = f"{_errors(events)} {stderr}".strip()
        if code != 0 or (not answer and problems):
            low = problems.lower()
            if any(m in low for m in AUTH_MARKERS):
                self.mark_unavailable("not logged in — run `codex login` in Terminal (sign in with ChatGPT)")
                raise CloudUnavailable(problems[:300])
            if looks_rate_limited(low):
                self.limits.saw_limit(problems)
                raise CloudRateLimited(problems[:300])
            raise CloudError(f"codex exited {code}: {problems[:300]}")
        value, errors = parse_and_validate(answer, schema)
        if errors:
            raise CloudBadOutput("Codex output invalid: " + "; ".join(errors[:3]))
        tin, tout = _usage(events)
        return CloudResult(output=value, cost_usd=0.0, input_tokens=tin, output_tokens=tout, cache_read_tokens=None,
                           duration_ms=(time.monotonic() - t0) * 1000, model=f"codex:{name or 'default'}",
                           subtype="success", cost_source="subscription", raw={})

    async def _exec(self, argv: list[str], stdin_text: str, timeout_s: float) -> tuple[str, str, int]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=minimal_env(), cwd=str(sandbox_dir("codex")))
        except OSError as exc:
            raise CloudUnavailable(f"could not start codex: {exc}") from exc
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin_text.encode()), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise CloudError(f"codex timed out after {timeout_s:.0f} s") from None
        return (out or b"").decode("utf-8", "replace"), (err or b"").decode("utf-8", "replace"), proc.returncode or 0

    def state(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {"available": bool(self._available) and not self.limits.blocked(), "reason": self.reason,
                "installed": self.installed or bool(self._bin()), "checked": self._available is not None,
                "model": settings.get("codex_model") or "default", "limits": self.limits.state()}


def _strict(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI structured outputs want additionalProperties:false on objects; add it where it's missing."""
    if not isinstance(schema, dict):
        return schema
    out = {k: (_strict(v) if isinstance(v, dict) else [_strict(x) for x in v] if isinstance(v, list) else v)
           for k, v in schema.items()}
    if out.get("type") == "object" and "additionalProperties" not in out:
        out["additionalProperties"] = False
    if isinstance(out.get("properties"), dict):
        out["properties"] = {k: _strict(v) for k, v in out["properties"].items()}
    return out


def ensure_login_need(conn: sqlite3.Connection, reason: str) -> str | None:
    from hq.db import repo, serializers
    from hq.db.conn import tx

    if conn.execute("SELECT id FROM needs_prerit WHERE title=? AND status IN ('open','snoozed')",
                    (LOGIN_NEED_TITLE,)).fetchone():
        return None
    with tx(conn):
        need_id = repo.insert_need(conn, {
            "kind": "decision", "title": LOGIN_NEED_TITLE, "priority": 50, "est_minutes": 1,
            "instructions_md": (f"The Codex CLI is switched on in HQ but unavailable ({reason}). Local models and "
                                "the other providers keep working.\n\nOpen Terminal on this Mac and run:\n\n"
                                "```\ncodex login\n```\n\nand sign in with your ChatGPT account. HQ re-checks every "
                                "10 minutes. Or switch it off in Settings › AI & budget."),
            "answers_json": json.dumps([{"label": "Command", "value": "codex login", "copy": True}]),
        })
        need = serializers.need_json(repo.get_need_row(conn, need_id))
        repo.emit(conn, "needs.created", need["title"], level="warn", data={"need": need})
    return need_id
