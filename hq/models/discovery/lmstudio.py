"""LM Studio: `GET http://127.0.0.1:1234/v1/models` or a scan of ~/.lmstudio/models."""
from __future__ import annotations

from pathlib import Path

import httpx

from hq.models.discovery.base import ModelInfo, estimate_ram_gb, params_from_name

BASE = "http://127.0.0.1:1234/v1"


def discover(root: Path | None = None) -> list[ModelInfo]:
    try:
        r = httpx.get(f"{BASE}/models", timeout=2.0)
        r.raise_for_status()
        return [ModelInfo(id=f"lmstudio:{m['id']}", runtime="lmstudio", name=m["id"], served_id=m["id"],
                          base_url=BASE, complete=True, runtime_supported=True, supports_json_schema=True,
                          params_b=params_from_name(m["id"]),
                          modality="embedding" if "embed" in m["id"].lower() else "chat")
                for m in r.json().get("data", []) if isinstance(m, dict) and m.get("id")]
    except httpx.HTTPError:
        pass
    base = root or Path.home() / ".lmstudio" / "models"
    out = []
    if base.is_dir():
        for f in base.rglob("*.gguf"):
            size = f.stat().st_size
            pb = params_from_name(f.name)
            out.append(ModelInfo(id=f"lmstudio:{f.parent.name}/{f.stem}", runtime="lmstudio", name=f.stem, path=str(f),
                                 served_id=f.stem, base_url=BASE, size_bytes=size, params_b=pb, complete=True,
                                 runtime_supported=True, est_ram_gb=estimate_ram_gb(size, pb, 4),
                                 extra={"server": "not running"}))
    return out
