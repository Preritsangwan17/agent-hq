"""http adapter: synchronous `POST <endpoint>/run` with the (redacted) task. The endpoint must be loopback or
listed in the `http_allowlist` setting; the API key comes from an env var named in adapter_config."""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx

from hq.adapters.base import RunContext, RunResult, TransientError
from hq.util.redact import redact

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class HttpAdapter:
    name = "http"

    async def health(self) -> dict[str, Any]:
        return {"ok": True}

    async def run(self, task: dict[str, Any], ctx: RunContext) -> RunResult:
        cfg = ctx.agent.adapter_config or {}
        endpoint = str(cfg.get("endpoint") or "").rstrip("/")
        host = urlparse(endpoint).hostname or ""
        allow = set(ctx.settings.get("http_allowlist") or [])
        if host not in LOOPBACK and host not in allow:
            raise TransientError(f"endpoint host {host!r} is not loopback or allowlisted")
        headers = {}
        if cfg.get("api_key_env") and os.environ.get(cfg["api_key_env"]):
            headers["Authorization"] = f"Bearer {os.environ[cfg['api_key_env']]}"
        body = {"capability": task["capability"], "payload": task.get("payload") or {},
                "opportunity_id": task.get("opportunity_id")}
        import json as _json
        red = _json.loads(redact(_json.dumps(body), ctx.conn))
        ctx.progress(0.1, f"POST {endpoint}/run")
        try:
            async with httpx.AsyncClient(timeout=float(cfg.get("timeout_s", 60))) as c:
                r = await c.post(f"{endpoint}/run", json=red, headers=headers)
        except httpx.HTTPError as exc:
            raise TransientError(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code >= 500:
            raise TransientError(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        return RunResult(output={"result": data.get("output", data) if isinstance(data, dict) else data},
                         summary=str((data or {}).get("summary", "done"))[:200] if isinstance(data, dict) else "done")
