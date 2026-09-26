"""ModelInfo shared by the runtime scanners, plus the upsert into `models`."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any

from hq.db.conn import dumps
from hq.util.timeutil import now_iso


@dataclass
class ModelInfo:
    id: str                       # mlx:<repo> | ollama:<name> | lmstudio:<id> | gguf:<abs path>
    runtime: str                  # mlx | ollama | lmstudio | llamacpp
    name: str
    path: str | None = None
    revision: str | None = None
    model_type: str | None = None
    arch: str | None = None
    quant: str | None = None
    params_b: float | None = None
    size_bytes: int | None = None
    ctx_len: int | None = None
    modality: str = "chat"        # chat | embedding | stt | tts | vision | other
    complete: bool = False
    incomplete_reason: str | None = None
    runtime_supported: bool = False
    supports_json_schema: bool = False
    est_ram_gb: float | None = None
    served_id: str | None = None   # what to send as `model` to the server
    base_url: str | None = None    # externally managed servers (ollama, lm studio)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.complete and self.runtime_supported and self.modality == "chat"

    def family(self) -> str:
        return model_family(self.name)


def model_family(name: str) -> str:
    """'mlx-community/Qwen3-4B-Instruct-2507-4bit' → 'qwen'; 'llama3.1:8b' → 'llama'."""
    base = name.split("/")[-1].lower()
    for fam in ("qwen", "llama", "gemma", "mistral", "mixtral", "phi", "deepseek", "granite", "smollm", "olmo",
                "command", "yi", "internlm", "glm", "falcon", "hermes"):
        if fam in base:
            return fam
    return re.split(r"[-_.:0-9]", base)[0] or base


def params_from_name(name: str) -> float | None:
    m = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)\s?[bB](?![a-zA-Z])", name.split("/")[-1])
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)[bB]-A\d", name)
    return float(m.group(1)) if m else None


def estimate_ram_gb(size_bytes: int | None, params_b: float | None, bits: int | None) -> float | None:
    """Weights on disk + ~15% for KV cache/activations at our context sizes, min 0.5 GB."""
    if size_bytes:
        return round(max(0.5, size_bytes / 1e9 * 1.15), 1)
    if params_b:
        return round(max(0.5, params_b * (bits or 4) / 8 * 1.2), 1)
    return None


def upsert_models(conn: sqlite3.Connection, models: list[ModelInfo]) -> tuple[list[str], list[str]]:
    """Insert/update rows. Returns (new_ids, newly_usable_ids). Keeps pinned/status/measured_ram. Caller owns tx."""
    new, newly_usable = [], []
    now = now_iso()
    for m in models:
        row = conn.execute("SELECT complete, runtime_supported, modality, status FROM models WHERE id=?",
                           (m.id,)).fetchone()
        status = "unsupported" if not m.runtime_supported else ("broken" if not m.complete else "available")
        values = (m.runtime, m.name, m.path, m.revision, m.model_type, m.arch, m.quant, m.params_b, m.size_bytes,
                  m.ctx_len, m.modality, int(m.complete), m.incomplete_reason, int(m.runtime_supported),
                  int(m.supports_json_schema), m.est_ram_gb, dumps({"served_id": m.served_id, "base_url": m.base_url,
                                                                    **m.extra}))
        if row is None:
            conn.execute(
                "INSERT INTO models(id, runtime, name, path, revision, model_type, arch, quant, params_b, size_bytes, "
                "ctx_len, modality, complete, incomplete_reason, runtime_supported, supports_json_schema, est_ram_gb, "
                "fingerprint, status, discovered_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m.id, *values, status, now, now))
            new.append(m.id)
            if m.usable:
                newly_usable.append(m.id)
        else:
            was_usable = bool(row["complete"] and row["runtime_supported"] and row["modality"] == "chat")
            keep = row["status"] if row["status"] == "loaded" and status == "available" else status
            conn.execute(
                "UPDATE models SET runtime=?, name=?, path=?, revision=?, model_type=?, arch=?, quant=?, params_b=?, "
                "size_bytes=?, ctx_len=?, modality=?, complete=?, incomplete_reason=?, runtime_supported=?, "
                "supports_json_schema=?, est_ram_gb=?, fingerprint=?, status=?, updated_at=? WHERE id=?",
                (*values, keep, now, m.id))
            if m.usable and not was_usable:
                newly_usable.append(m.id)
    return new, newly_usable


def as_dict(m: ModelInfo) -> dict[str, Any]:
    return asdict(m)
