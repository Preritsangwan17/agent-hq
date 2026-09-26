"""script adapter (PLAN "Agent protocol"):
- built-in modules (`adapter_config.module: hq.pipeline…`) run in-process: `async def run(task, ctx) -> RunResult`;
- user scripts (`adapter_config.command`) run as a subprocess that reads the task as JSON on stdin and prints one
  JSON object `{"output": …, "summary": "…"}`; the environment carries no secrets and effects are ignored
  (wizard-created agents return data only).
"""
from __future__ import annotations

import asyncio
import importlib
import json
import shlex
from typing import Any

from hq import settings as paths
from hq.adapters.base import RunContext, RunResult, TransientError
from hq.llm.errors import minimal_env


class ScriptAdapter:
    name = "script"

    async def health(self) -> dict[str, Any]:
        return {"ok": True}

    async def run(self, task: dict[str, Any], ctx: RunContext) -> RunResult:
        cfg = ctx.agent.adapter_config or {}
        if cfg.get("module"):
            module = str(cfg["module"])
            if not module.startswith("hq."):
                raise TransientError("in-process modules must live under hq.")
            fn = getattr(importlib.import_module(module), str(cfg.get("function", "run")))
            return await fn(task, ctx)
        cmd = cfg.get("command")
        if not cmd:
            raise TransientError("script agent has neither `module` nor `command`")
        argv = cmd if isinstance(cmd, list) else shlex.split(str(cmd))
        ctx.progress(0.1, f"Running {argv[0]}…")
        proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, env=minimal_env(),
                                                    cwd=str(paths.ROOT))
        payload = json.dumps({"capability": task["capability"], "payload": task.get("payload") or {},
                              "opportunity_id": task.get("opportunity_id")}).encode()
        try:
            out, err = await asyncio.wait_for(proc.communicate(payload), timeout=float(cfg.get("timeout_s", 120)))
        except asyncio.TimeoutError:
            proc.kill()
            raise TransientError("script timed out") from None
        if proc.returncode != 0:
            raise TransientError(f"script exited {proc.returncode}: {err.decode(errors='replace')[:300]}")
        try:
            data = json.loads(out.decode().strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as exc:
            raise TransientError(f"script did not print a JSON object: {exc}") from exc
        if not isinstance(data, dict):
            raise TransientError("script output must be a JSON object")
        return RunResult(output={"result": data.get("output", data)}, summary=str(data.get("summary") or "done")[:200])
