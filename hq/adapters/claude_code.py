"""claude_code adapter: a headless cloud model (no tools, no hooks) runs the agent's prompt on the task, budgeted.
The agent's `model` pins one (e.g. "sonnet", "xai:grok-4", "codex:default"); empty or "auto" uses the first
switched-on cloud provider that is reachable."""
from __future__ import annotations

from typing import Any

from hq.adapters.base import RunContext, RunResult
from hq.adapters.openai_compatible import task_message
from hq.llm import cloud
from hq.llm.prompts import load_prompt, load_schema


class ClaudeCodeAdapter:
    name = "claude_code"

    async def health(self) -> dict[str, Any]:
        return {"ok": True}

    async def run(self, task: dict[str, Any], ctx: RunContext) -> RunResult:
        cfg = ctx.agent.adapter_config or {}
        system = load_prompt(cfg["prompt"]) if cfg.get("prompt") else "You are a careful assistant."
        schema = load_schema(cfg["schema"]) if cfg.get("schema") else {"type": "object"}
        model = (ctx.agent.model or "").removeprefix("claude:")
        res = await ctx.claude(task["capability"], task_message(task, ctx), schema, system_prompt=system,
                               model=None if model in ("", "auto") else model)
        return RunResult(output={"result": res.output},
                         summary=f"{task['capability']} via {cloud.label(res.model)} {res.model.split(':')[-1]}",
                         model_id=cloud.tag(res.model), prompt_tokens=res.input_tokens,
                         completion_tokens=res.output_tokens, cost_usd=res.cost_usd)
