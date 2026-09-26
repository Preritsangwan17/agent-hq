"""Recommended local models for Prerit's Mac (config/local_models.yaml) and their download state.

Downloads go through the local Ollama server (`POST 127.0.0.1:11434/api/pull`) — only when Prerit clicks Download
or runs `make models`; agents never download anything on their own.
"""
from __future__ import annotations

import shutil
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import yaml

from hq import settings as paths

OLLAMA = "http://127.0.0.1:11434"
MAC = {"chip": "Apple M4 Pro", "memory_gb": 48, "disk_tb": 1}


@lru_cache(maxsize=2)
def _load(path: str, mtime: float) -> list[dict[str, Any]]:
    return list((yaml.safe_load(Path(path).read_text()) or {}).get("models") or [])


def entries() -> list[dict[str, Any]]:
    p = paths.CONFIG_DIR / "local_models.yaml"
    return _load(str(p), p.stat().st_mtime) if p.exists() else []


def entry(name: str) -> dict[str, Any] | None:
    return next((e for e in entries() if e["ollama"] == name), None)


def core_set() -> list[str]:
    return [e["ollama"] for e in entries() if e.get("set") == "core"]


def ollama_running(timeout: float = 1.0) -> bool:
    try:
        return httpx.get(f"{OLLAMA}/api/version", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def _installed(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    out = {}
    for r in conn.execute("SELECT id, name, enabled, status FROM models WHERE runtime='ollama'"):
        name = r["name"] or r["id"].removeprefix("ollama:")
        out[name] = {"id": r["id"], "enabled": bool(r["enabled"]), "status": r["status"]}
        if name.endswith(":latest"):
            out[name.removesuffix(":latest")] = out[name]
    return out


def recommended_json(conn: sqlite3.Connection, s: dict[str, Any]) -> dict[str, Any]:
    installed = _installed(conn)
    pulls = s.get("model_pull_state") or {}
    try:
        free_gb = round(shutil.disk_usage(Path.home()).free / 1e9, 1)
    except OSError:
        free_gb = None
    items = []
    for e in entries():
        have = installed.get(e["ollama"])
        items.append({**e, "installed": have is not None, "model_id": have["id"] if have else None,
                      "enabled": have["enabled"] if have else None, "pull": pulls.get(e["ollama"])})
    missing_core = [i for i in items if i.get("set") == "core" and not i["installed"]]
    return {"mac": MAC, "pool_budget_gb": float(s.get("model_pool_budget_gb", 32)), "disk_free_gb": free_gb,
            "ollama_running": ollama_running(), "models": items,
            "core_missing_gb": round(sum(float(i.get("download_gb") or 0) for i in missing_core), 1),
            "install_hint": "brew install ollama && brew services start ollama"}
