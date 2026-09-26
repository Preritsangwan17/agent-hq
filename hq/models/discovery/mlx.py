"""MLX models in the Hugging Face cache (`~/.cache/huggingface/hub/models--<org>--<name>/`).

A snapshot is complete iff every file in `model.safetensors.index.json`'s weight_map resolves to an existing
blob with no `.incomplete` partial, or a single `model.safetensors`/`weights.safetensors` resolves. config.json
gives model_type, architecture, quantization and context length; runtime support = mlx_lm has
`mlx_lm.models.<model_type>`. Modality: chat when the tokenizer has a chat template, embedding for
sentence-transformer style repos, stt for whisper, tts for kokoro.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Callable

from hq.models.discovery.base import ModelInfo, estimate_ram_gb, params_from_name

QWEN3 = ("qwen3",)


def hf_cache_dir() -> Path:
    env = os.environ.get("HF_HUB_CACHE") or (os.environ.get("HF_HOME") and str(Path(os.environ["HF_HOME"]) / "hub"))
    return Path(env) if env else Path.home() / ".cache" / "huggingface" / "hub"


def mlx_installed() -> bool:
    try:
        return importlib.util.find_spec("mlx_lm") is not None
    except (ImportError, ValueError):
        return False


def mlx_supports(model_type: str | None) -> bool:
    if not model_type:
        return False
    try:
        return importlib.util.find_spec(f"mlx_lm.models.{model_type}") is not None
    except (ImportError, ValueError):
        return False


def _read_json(p: Path) -> dict[str, Any] | None:
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _resolved(p: Path) -> Path | None:
    """The blob a snapshot entry points to, or None when missing/partial."""
    if not p.exists():
        return None
    target = p.resolve()
    if not target.exists() or target.name.endswith(".incomplete"):
        return None
    if Path(str(target) + ".incomplete").exists():
        return None
    return target


def _snapshot(repo_dir: Path) -> tuple[Path | None, str | None]:
    ref = repo_dir / "refs" / "main"
    snaps = repo_dir / "snapshots"
    if ref.exists():
        rev = ref.read_text().strip()
        if (snaps / rev).is_dir():
            return snaps / rev, rev
    if snaps.is_dir():
        cands = sorted((d for d in snaps.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
        if cands:
            return cands[0], cands[0].name
    return None, (ref.read_text().strip() if ref.exists() else None)


def _modality(repo: str, snap: Path, cfg: dict[str, Any]) -> str:
    low = repo.lower()
    if "whisper" in low or cfg.get("model_type") == "whisper":
        return "stt"
    if "kokoro" in low or "tts" in low:
        return "tts"
    if (snap / "modules.json").exists() or "embed" in low or "e5-" in low or "bge-" in low or "minilm" in low:
        return "embedding"
    tok = _read_json(snap / "tokenizer_config.json") or {}
    if tok.get("chat_template") or (snap / "chat_template.jinja").exists() or (snap / "chat_template.json").exists():
        return "vision" if "vision_config" in cfg else "chat"
    return "other"


def scan_repo(repo_dir: Path, supports: Callable[[str | None], bool] = mlx_supports) -> ModelInfo | None:
    if not repo_dir.name.startswith("models--"):
        return None
    repo = repo_dir.name[len("models--"):].replace("--", "/")
    snap, rev = _snapshot(repo_dir)
    info = ModelInfo(id=f"mlx:{repo}", runtime="mlx", name=repo, served_id=repo, revision=rev,
                     params_b=params_from_name(repo))
    if snap is None:
        info.incomplete_reason = "only a ref — no snapshot downloaded"
        info.modality = "chat"
        return info
    info.path = str(snap)
    cfg = _read_json(snap / "config.json") or {}
    info.model_type = cfg.get("model_type") or (cfg.get("text_config") or {}).get("model_type")
    info.arch = (cfg.get("architectures") or [None])[0]
    q = cfg.get("quantization") or cfg.get("quantization_config") or {}
    bits = q.get("bits")
    info.quant = f"{bits}bit" + (f"/g{q['group_size']}" if q.get("group_size") else "") if bits else None
    info.ctx_len = cfg.get("max_position_embeddings") or (cfg.get("text_config") or {}).get("max_position_embeddings")
    info.modality = _modality(repo, snap, cfg)
    if not cfg:
        info.incomplete_reason = "config.json missing"
    index = _read_json(snap / "model.safetensors.index.json")
    size = 0
    if index and isinstance(index.get("weight_map"), dict):
        files = sorted(set(index["weight_map"].values()))
        missing = []
        for f in files:
            blob = _resolved(snap / f)
            if blob is None:
                missing.append(f)
            else:
                size += blob.stat().st_size
        if missing:
            info.incomplete_reason = f"{len(missing)} of {len(files)} weight shards missing or partial ({missing[0]})"
    else:
        single = next((b for n in ("model.safetensors", "weights.safetensors")
                       if (b := _resolved(snap / n)) is not None), None)
        if single is not None:
            size = single.stat().st_size
        elif not info.incomplete_reason:
            info.incomplete_reason = "no weights (no model.safetensors or index)"
    info.size_bytes = size or None
    info.complete = info.incomplete_reason is None
    info.runtime_supported = supports(info.model_type) if info.modality in ("chat", "vision") else False
    if info.modality in ("chat",) and info.model_type and not info.runtime_supported and info.complete:
        missing = supports is mlx_supports and not mlx_installed()
        info.incomplete_reason = ("MLX runs only on Apple Silicon Macs with macOS 14+ (mlx-lm is not installed here)"
                                  if missing else f"mlx_lm has no '{info.model_type}' model type")
    info.est_ram_gb = estimate_ram_gb(info.size_bytes, info.params_b, bits)
    info.extra = {"qwen3": any(info.model_type and info.model_type.startswith(p) for p in QWEN3),
                  "bits": bits}
    return info


def discover(cache: Path | None = None, supports: Callable[[str | None], bool] = mlx_supports) -> list[ModelInfo]:
    root = cache or hf_cache_dir()
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and d.name.startswith("models--"):
            info = scan_repo(d, supports)
            if info is not None:
                out.append(info)
    return out
