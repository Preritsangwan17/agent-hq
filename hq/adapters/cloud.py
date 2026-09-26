"""cloud adapter: Grok (xAI's API, no tools) runs the agent's prompt on the task, budgeted and redacted.
Only for agents Prerit explicitly sets to `adapter: cloud`; the pipeline's own agents are local first."""
from __future__ import annotations

from typing import Any

from hq.adapters.base import RunContext, RunResult
from hq.adapters.openai_compatible import task_message
from hq.llm import cloud
from hq.llm.prompts import load_prompt, load_schema


class CloudAdapter:
    name = "cloud"

    async def health(self) -> dict[str, Any]:
        return {"ok": True}

    async def run(self, task: dict[str, Any], ctx: RunContext) -> RunResult:
        cfg = ctx.agent.adapter_config or {}
        system = load_prompt(cfg["prompt"]) if cfg.get("prompt") else "You are a careful assistant."
        schema = load_schema(cfg["schema"]) if cfg.get("schema") else {"type": "object"}
        model = cloud.tag(ctx.agent.model) if ctx.agent.model and cloud.is_cloud(cloud.tag(ctx.agent.model)) else None
        res = await ctx.cloud(task["capability"], task_message(task, ctx), schema, system_prompt=system, model=model)
        return RunResult(output={"result": res.output}, summary=f"{task['capability']} via Grok {res.model}",
                         model_id=cloud.tag(res.model), prompt_tokens=res.input_tokens,
                         completion_tokens=res.output_tokens, cost_usd=res.cost_usd)
