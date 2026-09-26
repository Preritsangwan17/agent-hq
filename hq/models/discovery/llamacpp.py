"""llama.cpp: GGUF files found with Spotlight (`mdfind`) plus common directories; served by `llama-server`."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from hq.models.discovery.base import ModelInfo, estimate_ram_gb, params_from_name

COMMON_DIRS = ("~/models", "~/Models", "~/Downloads", "~/.cache/llama.cpp", "~/llama.cpp/models", "~/.lmstudio/models")


def llama_server() -> str | None:
    return shutil.which("llama-server") or (p if Path(p := "/opt/homebrew/bin/llama-server").exists() else None)


def _mdfind() -> list[Path]:
    if not shutil.which("mdfind"):
        return []
    try:
        out = subprocess.run(["mdfind", "kMDItemFSName == '*.gguf'"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [Path(line) for line in out.stdout.splitlines() if line.endswith(".gguf")]


def discover(extra_dirs: list[Path] | None = None) -> list[ModelInfo]:
    files: set[Path] = set(_mdfind())
    for d in [Path(p).expanduser() for p in COMMON_DIRS] + list(extra_dirs or []):
        if d.is_dir():
            files.update(d.rglob("*.gguf"))
    server = llama_server()
    out = []
    for f in sorted(files):
        if "mmproj" in f.name.lower():
            continue
        size = f.stat().st_size if f.exists() else None
        pb = params_from_name(f.name)
        partial = f.name.endswith(".part") or (size is not None and size < 50_000_000)
        out.append(ModelInfo(id=f"gguf:{f.resolve()}", runtime="llamacpp", name=f.stem, path=str(f.resolve()),
                             served_id=f.stem, size_bytes=size, params_b=pb, complete=not partial,
                             incomplete_reason="file looks partial" if partial else None,
                             runtime_supported=server is not None, supports_json_schema=True,
                             est_ram_gb=estimate_ram_gb(size, pb, 4),
                             extra={"server_bin": server} if server else {"server": "llama-server not installed"}))
    return out
