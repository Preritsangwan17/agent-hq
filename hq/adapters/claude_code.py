"""claude_code adapter: headless Claude (no tools, no hooks) runs the agent's prompt on the task, budgeted."""
from __future__ import annotations

from typing import Any

from hq.adapters.base import RunContext, RunResult
from hq.adapters.openai_compatible import task_message
from hq.llm.prompts import load_prompt, load_schema


class ClaudeCodeAdapter:
    name = "claude_code"

    async def health(self) -> dict[str, Any]:
        return {"ok": True}

    async def run(self, task: dict[str, Any], ctx: RunContext) -> RunResult:
        cfg = ctx.agent.adapter_config or {}
        system = load_prompt(cfg["prompt"]) if cfg.get("prompt") else "You are a careful assistant."
        schema = load_schema(cfg["schema"]) if cfg.get("schema") else {"type": "object"}
        model = (ctx.agent.model or "").removeprefix("claude:") or None
        res = await ctx.claude(task["capability"], task_message(task, ctx), schema, system_prompt=system, model=model)
        return RunResult(output={"result": res.output}, summary=f"{task['capability']} via Claude {res.model}",
                         model_id=f"claude:{res.model}", prompt_tokens=res.input_tokens,
                         completion_tokens=res.output_tokens, cost_usd=res.cost_usd)
