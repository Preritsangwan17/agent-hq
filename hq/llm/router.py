"""Model router with the escalation ladder (CONTRACT_B §2, PLAN "Orchestrator › Failures").

`await router.route(role, messages, schema, …)` tries, in order:
  level 0 — the highest-ranked model assigned to the role (not excluded, not in the document lineage),
  level 1 — the next-ranked DIFFERENT local model (a different family when one exists),
  level 2 — Grok (the paid cloud model), only when the caller's policy allows it and within today's budget,
and raises EscalationExhausted otherwise. A level fails on invalid JSON after one repair turn, or when the output
carries a `confidence` below the threshold. Every attempt is an `agent_runs` row linked by `escalated_from_run_id`.
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
from hq.llm import cloud, policy
from hq.llm.errors import CloudBadOutput, CloudBudgetExceeded, CloudError, CloudRateLimited, CloudUnavailable
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
    def __init__(self, conn: sqlite3.Connection, manager: ModelManager | None, cloud_runner: Any = None,
                 chat_fn: ChatFn | None = None):
        self.conn = conn
        self.manager = manager
        self.cloud = cloud_runner
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
                    cloud_use: str | None = "needed", max_tokens: int = 900, temperature: float = 0.0,
                    task_type: str | None = None, confidence_threshold: float | None = None,
                    agent_id: str = "router", task_id: str | None = None, parent_run_id: str | None = None,
                    on_progress: Callable[[str, float | None, str | None], None] | None = None,
                    cloud_model: str | None = None, pinned_model: str | None = None) -> LLMResult:
        s = get_settings(self.conn)
        threshold = confidence_threshold if confidence_threshold is not None else (
            float(s.get("eligibility_threshold", 0.8)) if schema_has_confidence(schema) else None)
        exclude = set(exclude_models) | {m for m in lineage if m}
        attempts: list[dict[str, Any]] = []
        prev_run: str | None = None
        level = 0
        local_on = policy.local_on(s)
        ladder = [pinned_model] if pinned_model and not cloud.is_cloud(pinned_model) else self._ladder(role, exclude)
        if pinned_model and cloud.is_cloud(pinned_model):
            ladder, cloud_model = [], pinned_model
        if not local_on:
            ladder = []
        for model_id in ladder:
            run_id = new_id()
            try:
                res = await self._local(model_id, messages, schema, max_tokens, temperature, on_progress)
            except WaitingMemory as exc:
                if level == 0:
                    raise Deferred("waiting_memory", iso_in(60), str(exc)) from exc
                attempts.append({"level": level, "model_id": model_id, "error": str(exc)})
                break
            except (ModelBroken, llm_client.LLMError) as exc:
                self._record(run_id, agent_id, task_id, parent_run_id, prev_run, model_id, None, "failed", str(exc))
                attempts.append({"level": level, "model_id": model_id, "error": str(exc)[:300]})
                prev_run, level = run_id, level + 1
                continue
            output, errors, chat = res
            if not errors and threshold is not None and isinstance(output, dict):
                conf = output.get("confidence")
                if isinstance(conf, (int, float)) and conf < threshold:
                    errors = [f"confidence {conf:.2f} below {threshold:.2f}"]
            status = "succeeded" if not errors else "failed"
            self._record(run_id, agent_id, task_id, parent_run_id, prev_run, model_id, chat, status,
                         "; ".join(errors) or None, output)
            attempts.append({"level": level, "model_id": model_id, "error": "; ".join(errors) or None,
                             "tok_s": chat.tok_s if chat else None})
            if not errors:
                return LLMResult(model_id, output, chat.text, chat.prompt_tokens, chat.completion_tokens, chat.tok_s,
                                 chat.ttft_ms, None, level, run_id, attempts)
            self._escalated(task_id, agent_id, model_id, level, errors)
            prev_run, level = run_id, level + 1
        level = max(level, 2) if attempts else 2
        if cloud_use is None:
            raise EscalationExhausted(f"no local model for {role} succeeded (this step stays local)", attempts)
        decision = policy.escalate(s, cloud_use, local_tried=bool(attempts))
        if pinned_model and cloud.is_cloud(pinned_model) and policy.grok_on(s):
            decision = policy.Decision(True, pinned_model, "pinned to Grok")
        if not decision.allowed or self.cloud is None:
            raise EscalationExhausted(f"no local model for {role} succeeded; Grok not used: "
                                      f"{decision.reason or 'no cloud runner'}", attempts)
        cloud_model = cloud_model or decision.model
        return await self._cloud(role, messages, schema, task_type or f"escalation.{role}", agent_id, task_id,
                                 parent_run_id, prev_run, attempts, s, cloud_model, lineage)

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

    async def _cloud(self, role: str, messages: list[dict[str, str]], schema: dict[str, Any] | None, task_type: str,
                     agent_id: str, task_id: str | None, parent_run_id: str | None, prev_run: str | None,
                     attempts: list[dict[str, Any]], s: dict[str, Any], cloud_model: str | None,
                     lineage: tuple[str, ...] | list[str]) -> LLMResult:
        assert self.cloud is not None
        model = cloud_model or cloud.fast_model(s)
        mid, who = cloud.tag(model), cloud.label(model)
        if mid in set(lineage):
            raise EscalationExhausted(f"{mid} already authored this document", attempts)
        if not await cloud.is_available(self.cloud, model):
            raise EscalationExhausted(f"{who} unavailable ({self.cloud.reason})", attempts)
        reservation = budget_mod.reserve(self.conn, task_type, s)
        if reservation is None:
            raise Deferred("deferred_budget", budget_mod.to_iso(budget_mod.next_midnight_ist()),
                           "Cloud daily budget or call cap reached")
        system, prompt = _to_prompt(messages)
        run_id = new_id()
        t0 = time.monotonic()
        try:
            res = await self.cloud.run(prompt, schema=schema or {"type": "object"}, system_prompt=system, model=model,
                                       max_budget_usd=float(s.get("cloud_per_call_cap_usd", 0.5)))
        except CloudError as exc:
            cost = getattr(exc, "cost_usd", None)
            if cost is not None or isinstance(exc, (CloudBadOutput, CloudBudgetExceeded)):
                budget_mod.commit(self.conn, reservation, cost_usd=cost, model=model, subtype=exc.kind)
            else:
                budget_mod.release(self.conn, reservation)
            self._record(run_id, agent_id, task_id, parent_run_id, prev_run, mid, None, "failed",
                         str(exc), cost=cost, duration_ms=(time.monotonic() - t0) * 1000)
            attempts.append({"level": 2, "model_id": mid, "error": str(exc)[:300]})
            if isinstance(exc, CloudRateLimited):
                raise Deferred("queued", iso_in(3600), f"{who} rate-limited: {exc}") from exc
            if isinstance(exc, CloudUnavailable):
                raise EscalationExhausted(f"{who} unavailable: {exc}", attempts) from exc
            raise EscalationExhausted(f"{who} failed: {exc}", attempts) from exc
        budget_mod.commit(self.conn, reservation, cost_usd=res.cost_usd, model=model, input_tokens=res.input_tokens,
                          output_tokens=res.output_tokens, cache_read_tokens=res.cache_read_tokens,
                          cost_source=getattr(res, "cost_source", None))
        self._record(run_id, agent_id, task_id, parent_run_id, prev_run, mid, None, "succeeded", None,
                     res.output, cost=res.cost_usd, duration_ms=res.duration_ms, prompt_tokens=res.input_tokens,
                     completion_tokens=res.output_tokens)
        attempts.append({"level": 2, "model_id": mid, "error": None, "cost_usd": res.cost_usd})
        return LLMResult(mid, res.output, json.dumps(res.output), res.input_tokens, res.output_tokens,
                         None, None, res.cost_usd, 2, run_id, attempts)

    # ── records ─────────────────────────────────────────────────────────────────────────────────────
    def _record(self, run_id: str, agent_id: str, task_id: str | None, parent_run_id: str | None,
                escalated_from: str | None, model_id: str, chat: llm_client.ChatResult | None, status: str,
                error: str | None, output: Any = None, *, cost: float | None = None, duration_ms: float | None = None,
                prompt_tokens: int | None = None, completion_tokens: int | None = None) -> None:
        with tx(self.conn):
            self.conn.execute(
                "INSERT INTO agent_runs(id, task_id, parent_run_id, escalated_from_run_id, agent_id, adapter, model_id, "
                "prompt_tokens, completion_tokens, tok_s, ttft_ms, cost_usd, duration_ms, status, error, started_at, "
                "finished_at, output_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, task_id, parent_run_id, escalated_from, agent_id,
                 "xai" if model_id.startswith("xai:") else "openai_compatible", model_id,
                 prompt_tokens if chat is None else chat.prompt_tokens,
                 completion_tokens if chat is None else chat.completion_tokens, chat.tok_s if chat else None,
                 chat.ttft_ms if chat else None, cost,
                 int(duration_ms if duration_ms is not None else (chat.duration_ms if chat else 0)), status,
                 (error or None) and error[:2000], now_iso(), now_iso(),
                 dumps(output)[:20000] if output is not None else None))

    def _escalated(self, task_id: str | None, agent_id: str, model_id: str, level: int, errors: list[str]) -> None:
        with tx(self.conn):
            repo.emit(self.conn, "task.escalated", f"Escalating from {model_id} (level {level}): {errors[0][:160]}",
                      level="warn", agent_id=agent_id if agent_id != "router" else None, task_id=task_id,
                      data={"task_id": task_id, "capability": None, "agent_id": agent_id, "from_model": model_id,
                            "level": level + 1, "reason": errors[0][:300]})
