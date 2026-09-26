"""openai_compatible adapter (PLAN "Agent protocol"): a local model runs the agent's prompt file on the task.

adapter_config: {prompt: prompts/x.md, schema: schemas/x.json, max_tokens: 900, managed: true} routes through the
role's leaderboard model (agent `model: auto`) or a pinned `model: mlx:<repo>`, with escalation; `managed: false`
plus `base_url` + `served_model` talks to an already-running local server (Ollama, LM Studio) directly.
"""
from __future__ import annotations

import json
import os
from typing import Any

from hq.adapters.base import RunContext, RunResult, TransientError
from hq.llm import client as llm_client
from hq.llm.json_utils import parse_and_validate, repair_message
from hq.llm.prompts import load_prompt, load_schema
from hq.models.roles import AGENT_ROLE

DEFAULT_SYSTEM = "You are a careful assistant. Answer with a single JSON object."


def task_message(task: dict[str, Any], ctx: RunContext) -> str:
    opp = None
    if task.get("opportunity_id"):
        rows = ctx.query("SELECT company_name, title, kind, city, country_iso2, url, summary FROM opportunities "
                         "WHERE id=?", (task["opportunity_id"],))
        opp = rows[0] if rows else None
    return json.dumps({"capability": task["capability"], "payload": task.get("payload") or {}, "opportunity": opp},
                      ensure_ascii=False, default=str)


class OpenAICompatibleAdapter:
    name = "openai_compatible"

    async def health(self) -> dict[str, Any]:
        return {"ok": True}

    async def run(self, task: dict[str, Any], ctx: RunContext) -> RunResult:
        cfg = ctx.agent.adapter_config or {}
        system = load_prompt(cfg["prompt"]) if cfg.get("prompt") else DEFAULT_SYSTEM
        schema = load_schema(cfg["schema"]) if cfg.get("schema") else None
        messages = [{"role": "system", "content": system}, {"role": "user", "content": task_message(task, ctx)}]
        max_tokens = int(cfg.get("max_tokens", 900))
        ctx.progress(0.1, f"Running {task['capability']}…")
        if cfg.get("managed") is False and cfg.get("base_url"):
            key = os.environ.get(cfg["api_key_env"]) if cfg.get("api_key_env") else None
            chat = await llm_client.chat(cfg["base_url"], cfg.get("served_model") or ctx.agent.model or "", messages,
                                         max_tokens=max_tokens, api_key=key)
            out, errors = parse_and_validate(chat.text, schema) if schema else (chat.text, [])
            if errors:
                chat = await llm_client.chat(cfg["base_url"], cfg.get("served_model") or "", messages + [
                    {"role": "assistant", "content": chat.raw_text}, {"role": "user", "content": repair_message(errors, schema)}],
                    max_tokens=max_tokens, api_key=key)
                out, errors = parse_and_validate(chat.text, schema)
                if errors:
                    raise TransientError("invalid JSON from the model after one repair: " + "; ".join(errors[:2]))
            return RunResult(output={"result": out}, summary=f"{task['capability']} done",
                             model_id=f"openai:{cfg.get('served_model')}", prompt_tokens=chat.prompt_tokens,
                             completion_tokens=chat.completion_tokens, tok_s=chat.tok_s, ttft_ms=chat.ttft_ms)
        role = cfg.get("role") or AGENT_ROLE.get(ctx.agent.role, ctx.agent.role)
        pinned = ctx.agent.model if ctx.agent.model and ctx.agent.model != "auto" else None
        res = await ctx.llm(role, messages, schema, max_tokens=max_tokens, pinned_model=pinned,
                            now_line=f"Running {task['capability']}…")
        return RunResult(output={"result": res.output}, summary=f"{task['capability']} via {res.model_id}",
                         model_id=res.model_id, prompt_tokens=res.prompt_tokens,
                         completion_tokens=res.completion_tokens, tok_s=res.tok_s, ttft_ms=res.ttft_ms,
                         cost_usd=res.cost_usd)
