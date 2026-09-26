"""Ollama: `GET http://127.0.0.1:11434/api/tags` (2 s) or the manifests under ~/.ollama/models."""
from __future__ import annotations

from pathlib import Path

import httpx

from hq.models.discovery.base import ModelInfo, estimate_ram_gb, params_from_name

BASE = "http://127.0.0.1:11434"


def _from_api() -> list[ModelInfo] | None:
    try:
        r = httpx.get(f"{BASE}/api/tags", timeout=2.0)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    out = []
    for m in r.json().get("models", []):
        name = m.get("name") or m.get("model")
        details = m.get("details") or {}
        size = m.get("size")
        params = details.get("parameter_size")
        pb = params_from_name(params or name or "")
        out.append(ModelInfo(id=f"ollama:{name}", runtime="ollama", name=name, served_id=name,
                             base_url=f"{BASE}/v1", size_bytes=size, params_b=pb, quant=details.get("quantization_level"),
                             model_type=details.get("family"), modality="embedding" if "embed" in name else "chat",
                             complete=True, runtime_supported=True, supports_json_schema=True,
                             est_ram_gb=estimate_ram_gb(size, pb, 4)))
    return out


def _from_manifests(root: Path | None = None) -> list[ModelInfo]:
    base = root or Path.home() / ".ollama" / "models" / "manifests"
    out = []
    if not base.is_dir():
        return out
    for f in base.rglob("*"):
        if f.is_file():
            parts = f.relative_to(base).parts  # registry/library/<name>/<tag>
            if len(parts) >= 2:
                name = f"{parts[-2]}:{parts[-1]}"
                out.append(ModelInfo(id=f"ollama:{name}", runtime="ollama", name=name, served_id=name,
                                     base_url=f"{BASE}/v1", complete=True, runtime_supported=True,
                                     supports_json_schema=True, params_b=params_from_name(name),
                                     incomplete_reason=None, extra={"server": "not running"}))
    return out


def discover() -> list[ModelInfo]:
    api = _from_api()
    return api if api is not None else _from_manifests()
