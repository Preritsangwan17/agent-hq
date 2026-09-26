"""Local-first routing with quality checks, task-aware external fallbacks and per-attempt provenance.
Local AI is required. Cloud pins choose an escalation target without skipping local work.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from hq.adapters.base import Deferred
from hq.db import repo
from hq.db.conn import dumps, tx
from hq.db.seed import get_settings
from hq.llm import client as llm_client
from hq.llm import cloud, modes, policy
from hq.llm.claude import ClaudeBadOutput, ClaudeBudgetExceeded, ClaudeError, ClaudeRateLimited, ClaudeRunner, \
    ClaudeUnavailable
from hq.llm.json_utils import parse_and_validate, repair_message
from hq.models import roles as roles_mod
from hq.models.discovery.base import model_family
from hq.models.manager import ModelBroken, ModelManager, WaitingMemory
from hq.util.ids import new_id
from hq.util.timeutil import iso_in, now_iso
from hq.worker import budget as budget_mod


class EscalationExhausted(Exception):
    def __init__(self, message: str, attempts: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.attempts = attempts or []



@dataclass
class LLMResult:
    model_id: str
    output: Any
    text: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tok_s: float | None = None
    ttft_ms: float | None = None
    cost_usd: float | None = None
    escalation_level: int = 0
    run_id: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)


ChatFn = Callable[..., Awaitable[llm_client.ChatResult]]


def schema_has_confidence(schema: dict[str, Any] | None) -> bool:
    return bool(schema and "confidence" in (schema.get("properties") or {}))


def _to_prompt(messages: list[dict[str, str]]) -> tuple[str, str]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system") or "You are a careful assistant."
    rest = "\n\n".join(f"{m['role'].upper()}:\n{m['content']}" if m["role"] != "user" else m["content"]
                       for m in messages if m["role"] != "system")
    return system, rest


class Router:
    def __init__(self, conn: sqlite3.Connection, manager: ModelManager | None, claude: ClaudeRunner | None = None,
                 chat_fn: ChatFn | None = None):
        self.conn = conn
        self.manager = manager
        self.claude = claude
        self.chat_fn = chat_fn or llm_client.chat

    def candidates(self, role: str, exclude: set[str]) -> list[str]:
        return [m for m in roles_mod.ranked(self.conn, role) if m not in exclude]

    def _family(self, model_id: str) -> str:
        row = self.conn.execute("SELECT name FROM models WHERE id=?", (model_id,)).fetchone()
        return model_family(row["name"] if row else model_id)

    def _ladder(self, role: str, exclude: set[str]) -> list[str]:
        cands = self.candidates(role, exclude)
        if not cands:
            return []
        first = cands[0]
        fam = self._family(first)
        second = next((m for m in cands[1:] if self._family(m) != fam), None) or (cands[1] if len(cands) > 1 else None)
        return [first] + ([second] if second else [])

    async def route(self, role: str, messages: list[dict[str, str]], schema: dict[str, Any] | None, *,
                    exclude_models: frozenset[str] | set[str] = frozenset(), lineage: tuple[str, ...] | list[str] = (),
                    allow_claude: bool = True, max_tokens: int = 900, temperature: float = 0.0,
                    task_type: str | None = None, confidence_threshold: float | None = None,
                    agent_id: str = "router", task_id: str | None = None, parent_run_id: str | None = None,
                    on_progress: Callable[[str, float | None, str | None], None] | None = None,
                    claude_model: str | None = None, pinned_model: str | None = None) -> LLMResult:
        s = get_settings(self.conn)
        threshold = confidence_threshold if confidence_threshold is not None else (
            float(s.get("eligibility_threshold", 0.8)) if schema_has_confidence(schema) else None)
        exclude = set(exclude_models) | {m for m in lineage if m}
        attempts: list[dict[str, Any]] = []
        prev_run: str | None = None
        level = 0
        task_type = task_type or role
        if pinned_model and cloud.is_cloud(pinned_model):
            claude_model = pinned_model.removeprefix("claude:")
            ladder = self._ladder(role, exclude)
        else:
            ladder = ([pinned_model] if pinned_model not in exclude else []) if pinned_model else self._ladder(role, exclude)
        for model_id in ladder:
            run_id = new_id()
            s = get_settings(self.conn)
            sufficient, reason = policy.local_quality(self.conn, role, model_id)
            route_meta = {"ai_mode": modes.current(s), "task_type": task_type,
                          "reason": ("Local fallback. " if level else "Local AI first. ") + reason}
            try:
                res = await self._local(model_id, messages, schema, max_tokens, temperature, on_progress)
            except WaitingMemory as exc:
                if level == 0:
                    raise Deferred("waiting_memory", iso_in(60), str(exc)) from exc
                attempts.append({"level": level, "model_id": model_id, "error": str(exc)})
                break
            except (ModelBroken, llm_client.LLMError) as exc:
                self._record(run_id, agent_id, task_id, parent_run_id, prev_run, model_id, None, "failed", str(exc), **route_meta)
                attempts.append({"level": level, "model_id": model_id, "error": str(exc)[:300]})
                prev_run, level = run_id, level + 1
                continue
            output, errors, chat = res
            if not errors and threshold is not None and isinstance(output, dict):
                conf = output.get("confidence")
                if isinstance(conf, (int, float)) and conf < threshold:
                    errors = [f"confidence {conf:.2f} below {threshold:.2f}"]
            if not errors and sufficient is False:
                errors = ["Local benchmark quality is below the required floor"]
            status = "succeeded" if not errors else "failed"
            self._record(run_id, agent_id, task_id, parent_run_id, prev_run, model_id, chat, status,
                         "; ".join(errors) or None, output, **route_meta)
            attempts.append({"level": level, "model_id": model_id, "error": "; ".join(errors) or None,
                             "tok_s": chat.tok_s if chat else None})
            if not errors:
                return LLMResult(model_id, output, chat.text, chat.prompt_tokens, chat.completion_tokens, chat.tok_s,
                                 chat.ttft_ms, None, level, run_id, attempts)
            self._escalated(task_id, agent_id, model_id, level, errors)
            prev_run, level = run_id, level + 1
        level = max(level, 2) if attempts else 2
        if not allow_claude or self.claude is None:
            why = f"no local model for {role} succeeded"
            raise EscalationExhausted(f"{why} and this step doesn't use the cloud", attempts)
        return await self._claude(role, messages, schema, task_type or f"escalation.{role}", agent_id, task_id,
                                  parent_run_id, prev_run, attempts, s, claude_model, lineage)

    async def _local(self, model_id: str, messages: list[dict[str, str]], schema: dict[str, Any] | None,
                     max_tokens: int, temperature: float,
                     on_progress: Callable[[str, float | None, str | None], None] | None):
        if self.manager is None:
            raise ModelBroken("no model manager")
        async with self.manager.use(model_id) as ep:
            def tick(n: int, tok_s: float) -> None:
                if on_progress:
                    on_progress(model_id, tok_s, None)
            chat = await self.chat_fn(ep.base_url, ep.served_id, messages, max_tokens=max_tokens,
                                      temperature=temperature, on_token=tick)
            output, errors = parse_and_validate(chat.text, schema)
            if errors and schema is not None:
                repair = messages + [{"role": "assistant", "content": chat.raw_text or chat.text},
                                     {"role": "user", "content": repair_message(errors, schema)}]
                chat2 = await self.chat_fn(ep.base_url, ep.served_id, repair, max_tokens=max_tokens,
                                           temperature=temperature, on_token=tick)
                output, errors = parse_and_validate(chat2.text, schema)
                chat = llm_client.ChatResult(
                    text=chat2.text, prompt_tokens=(chat.prompt_tokens or 0) + (chat2.prompt_tokens or 0),
                    completion_tokens=(chat.completion_tokens or 0) + (chat2.completion_tokens or 0),
                    ttft_ms=chat.ttft_ms, tok_s=chat2.tok_s or chat.tok_s, duration_ms=chat.duration_ms + chat2.duration_ms,
                    raw_text=chat2.raw_text)
                if not errors:
                    chat.finish_reason = "repaired"
            return output, errors, chat

    async def _claude(self, role: str, messages: list[dict[str, str]], schema: dict[str, Any] | None, task_type: str,
                      agent_id: str, task_id: str | None, parent_run_id: str | None, prev_run: str | None,
                      attempts: list[dict[str, Any]], s: dict[str, Any], claude_model: str | None,
                      lineage: tuple[str, ...] | list[str]) -> LLMResult:
        assert self.claude is not None
        excluded = {cloud.tag(m) for m in lineage if m}
        tried: set[str] = set()
        system, prompt = _to_prompt(messages)
        limited = False
        for _ in cloud.PROVIDERS:
            # Re-read on each attempt: changing mode applies without a worker restart.
            s = get_settings(self.conn)
            if claude_model:
                model = claude_model
                if cloud.tag(model) in excluded:
                    raise EscalationExhausted(f"{cloud.tag(model)} already authored this document", attempts)
                if (cloud.provider_of(model) in tried or not cloud.enabled(s, cloud.provider_of(model)) or
                        not await cloud.is_available(self.claude, model)):
                    break
            else:
                blocked = excluded | {cloud.tag(cloud.model_for(s, p)) for p in tried}
                model = await cloud.pick(self.claude, s, exclude=blocked, task_type=task_type)
                if model is None:
                    break
            p = cloud.provider_of(model)
            tried.add(p)
            mid = cloud.tag(model)
            run_id = new_id()
            reservation = budget_mod.reserve(self.conn, task_type, s, run_id=run_id)
            if reservation is None:
                raise Deferred("deferred_budget", budget_mod.to_iso(budget_mod.next_midnight_ist()),
                               "Cloud daily budget or call cap reached")
            meta = {"ai_mode": modes.current(s), "task_type": task_type,
                    "reason": policy.cloud_reason(task_type, p, bool(attempts))}
            t0 = time.monotonic()
            try:
                # CloudRunner checks the current mode again immediately before dispatch.
                res = await self.claude.run(prompt, schema=schema or {"type": "object"}, system_prompt=system,
                                            model=model, max_budget_usd=float(s.get("claude_per_call_cap_usd", 0.5)))
            except ClaudeError as exc:
                cost = getattr(exc, "cost_usd", None)
                if cost is not None or isinstance(exc, (ClaudeBadOutput, ClaudeBudgetExceeded)):
                    budget_mod.commit(self.conn, reservation, cost_usd=cost, model=model, subtype=exc.kind)
                else:
                    budget_mod.release(self.conn, reservation)
                self._record(run_id, agent_id, task_id, parent_run_id, prev_run, mid, None, "failed",
                             str(exc), cost=cost, duration_ms=(time.monotonic() - t0) * 1000, **meta)
                attempts.append({"level": 2, "model_id": mid, "error": str(exc)[:300]})
                self._escalated(task_id, agent_id, mid, 2, [str(exc)])
                prev_run = run_id
                limited = limited or isinstance(exc, ClaudeRateLimited)
                continue
            except BaseException:
                budget_mod.release(self.conn, reservation)
                raise
            budget_mod.commit(self.conn, reservation, cost_usd=res.cost_usd, model=model,
                              input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                              cache_read_tokens=res.cache_read_tokens)
            # Enforce the same output/confidence gate for external providers too.
            output, errors = parse_and_validate(json.dumps(res.output), schema)
            threshold = float(s.get("eligibility_threshold", 0.8)) if schema_has_confidence(schema) else None
            if not errors and threshold is not None and isinstance(output, dict):
                confidence = output.get("confidence")
                if isinstance(confidence, (int, float)) and confidence < threshold:
                    errors = [f"confidence {confidence:.2f} below {threshold:.2f}"]
            self._record(run_id, agent_id, task_id, parent_run_id, prev_run, mid, None,
                         "failed" if errors else "succeeded", "; ".join(errors) or None, res.output,
                         cost=res.cost_usd, duration_ms=res.duration_ms, prompt_tokens=res.input_tokens,
                         completion_tokens=res.output_tokens, **meta)
            attempts.append({"level": 2, "model_id": mid, "error": "; ".join(errors) or None,
                             "cost_usd": res.cost_usd})
            if errors:
                prev_run = run_id
                continue
            return LLMResult(mid, output, json.dumps(output), res.input_tokens, res.output_tokens,
                             None, None, res.cost_usd, 2, run_id, attempts)
        if limited:
            raise Deferred("queued", iso_in(3600), "Enabled cloud providers exhausted; usage-limited providers are resting")
        raise EscalationExhausted(cloud.why_none(self.claude, get_settings(self.conn)) +
                                  ("; all eligible attempts failed" if tried else ""), attempts)

    # ── records ─────────────────────────────────────────────────────────────────────────────────────
    def _record(self, run_id: str, agent_id: str, task_id: str | None, parent_run_id: str | None,
                escalated_from: str | None, model_id: str, chat: llm_client.ChatResult | None, status: str,
                error: str | None, output: Any = None, *, cost: float | None = None, duration_ms: float | None = None,
                prompt_tokens: int | None = None, completion_tokens: int | None = None, ai_mode: str | None = None, task_type: str | None = None,
                reason: str | None = None) -> None:
        with tx(self.conn):
            self.conn.execute(
                "INSERT INTO agent_runs(id, task_id, parent_run_id, escalated_from_run_id, agent_id, adapter, model_id, "
                "prompt_tokens, completion_tokens, tok_s, ttft_ms, cost_usd, duration_ms, status, error, started_at, "
                "finished_at, output_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, task_id, parent_run_id, escalated_from, agent_id,
                 "claude_code" if model_id.startswith("claude:") else "xai" if model_id.startswith("xai:")
                 else "codex" if model_id.startswith("codex:") else "openai_compatible", model_id,
                 prompt_tokens if chat is None else chat.prompt_tokens,
                 completion_tokens if chat is None else chat.completion_tokens, chat.tok_s if chat else None,
                 chat.ttft_ms if chat else None, cost,
                 int(duration_ms if duration_ms is not None else (chat.duration_ms if chat else 0)), status,
                 (error or None) and error[:2000], now_iso(), now_iso(),
                 dumps(output)[:20000] if output is not None else None))
            self.conn.execute("UPDATE agent_runs SET ai_mode=?, task_type=?, route_reason=?, execution=? WHERE id=?",
                              (ai_mode or modes.current(get_settings(self.conn)), task_type, reason,
                               "cloud" if cloud.is_cloud(model_id) else "local", run_id))

    def _escalated(self, task_id: str | None, agent_id: str, model_id: str, level: int, errors: list[str]) -> None:
        with tx(self.conn):
            repo.emit(self.conn, "task.escalated", f"Escalating from {model_id} (level {level}): {errors[0][:160]}",
                      level="warn", agent_id=agent_id if agent_id != "router" else None, task_id=task_id,
                      data={"task_id": task_id, "capability": None, "agent_id": agent_id, "from_model": model_id,
                            "level": level + 1, "reason": errors[0][:300]})
