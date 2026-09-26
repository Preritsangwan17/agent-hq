"""OpenAI-compatible chat client for local model servers (mlx_lm.server, Ollama, LM Studio, llama-server).

Streams so it can measure time-to-first-token and generation speed. Always sends `model` (the served id) and
`max_tokens`. Local servers only: the base URL must be loopback (the netguard enforces this for all traffic)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from hq.llm.json_utils import strip_think

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class LLMError(Exception):
    """The server answered with an error or an unusable response."""


class LLMUnavailable(LLMError):
    """Could not reach the server (not running, refused, timed out)."""


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    ttft_ms: float | None
    tok_s: float | None
    duration_ms: float
    finish_reason: str | None = None
    raw_text: str = ""


def _check_local(base_url: str) -> None:
    host = urlparse(base_url).hostname or ""
    if host not in LOCAL_HOSTS:
        raise LLMError(f"refusing non-local model endpoint {base_url!r}")


async def chat(base_url: str, model: str, messages: list[dict[str, str]], *, max_tokens: int = 900,
               temperature: float = 0.0, timeout_s: float = 180.0, api_key: str | None = None,
               response_format: dict | None = None, on_token: Callable[[int, float], None] | None = None,
               client: httpx.AsyncClient | None = None) -> ChatResult:
    """POST {base_url}/chat/completions with stream=true. `on_token(n_tokens, tok_s)` is called ~every 16 tokens."""
    _check_local(base_url)
    url = base_url.rstrip("/") + "/chat/completions"
    body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens,
                            "temperature": temperature, "stream": True,
                            "stream_options": {"include_usage": True}}
    if response_format:
        body["response_format"] = response_format
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    t0 = time.monotonic()
    first: float | None = None
    parts: list[str] = []
    usage: dict[str, Any] = {}
    finish: str | None = None
    n_chunks = 0
    own = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5.0))
    try:
        async with http.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                detail = (await resp.aread()).decode("utf-8", "replace")[:300]
                raise LLMError(f"HTTP {resp.status_code} from {url}: {detail}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content") or (choice.get("message") or {}).get("content")
                    if delta:
                        if first is None:
                            first = time.monotonic()
                        parts.append(delta)
                        n_chunks += 1
                        if on_token and n_chunks % 16 == 0:
                            gen = time.monotonic() - first
                            on_token(n_chunks, n_chunks / gen if gen > 0 else 0.0)
                    finish = choice.get("finish_reason") or finish
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
        raise LLMUnavailable(f"{type(exc).__name__} talking to {url}: {exc}") from exc
    finally:
        if own:
            await http.aclose()
    t1 = time.monotonic()
    raw = "".join(parts)
    completion = usage.get("completion_tokens") or n_chunks or None
    gen_s = (t1 - first) if first else None
    tok_s = (completion / gen_s) if completion and gen_s and gen_s > 0 else None
    return ChatResult(text=strip_think(raw), prompt_tokens=usage.get("prompt_tokens"), completion_tokens=completion,
                      ttft_ms=(first - t0) * 1000 if first else None, tok_s=round(tok_s, 1) if tok_s else None,
                      duration_ms=(t1 - t0) * 1000, finish_reason=finish, raw_text=raw)


async def list_models(base_url: str, timeout_s: float = 2.0) -> list[str]:
    _check_local(base_url)
    async with httpx.AsyncClient(timeout=timeout_s) as c:
        r = await c.get(base_url.rstrip("/") + "/models")
        r.raise_for_status()
        return [m.get("id") for m in r.json().get("data", []) if isinstance(m, dict)]
