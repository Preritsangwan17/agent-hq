"""`discover_all()` scans every runtime; `rescan(conn)` upserts the results and announces new usable models."""
from __future__ import annotations

import logging
import sqlite3

from hq.db import repo
from hq.db.conn import tx
from hq.models.discovery import llamacpp, lmstudio, mlx, ollama
from hq.models.discovery.base import ModelInfo, upsert_models

log = logging.getLogger("hq.models")


def discover_all() -> list[ModelInfo]:
    out: list[ModelInfo] = []
    for name, fn in (("mlx", mlx.discover), ("ollama", ollama.discover), ("lmstudio", lmstudio.discover),
                     ("llamacpp", llamacpp.discover)):
        try:
            out.extend(fn())
        except Exception as exc:  # one broken runtime must not hide the others
            log.warning("discovery %s failed: %s", name, exc)
    return out


def rescan(conn: sqlite3.Connection, models: list[ModelInfo] | None = None) -> dict[str, list[str]]:
    found = discover_all() if models is None else models
    with tx(conn):
        new, usable = upsert_models(conn, found)
        for mid in usable:
            repo.emit(conn, "model.discovered", f"New usable model: {mid}", data={"model_id": mid})
        repo.emit(conn, "log", f"Model scan: {len(found)} found, {sum(m.usable for m in found)} usable, "
                  f"{sum(not m.complete for m in found)} incomplete", level="debug",
                  data={"found": len(found), "new": new})
    return {"new": new, "usable_new": usable, "all": [m.id for m in found]}
