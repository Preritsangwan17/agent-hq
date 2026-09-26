"""Agent registry: loads agents/*.yaml, validates with AgentConfig, mirrors them into the `agents` table and
hot-reloads with watchfiles. An invalid file never replaces the last good config; it only raises an `error` event."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import ValidationError

from hq.agents.schema import AgentConfig
from hq.db import repo, serializers
from hq.db.conn import dumps, tx
from hq.util.timeutil import now_iso

log = logging.getLogger("hq.registry")


class AgentFileError(ValueError):
    pass


def parse_agent_bytes(data: bytes, expected_id: str | None = None) -> AgentConfig:
    try:
        raw = yaml.safe_load(data.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise AgentFileError(f"not valid YAML: {exc}") from None
    if not isinstance(raw, dict):
        raise AgentFileError("top level must be a mapping")
    try:
        cfg = AgentConfig.model_validate(raw)
    except ValidationError as exc:
        msgs = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'config'}: {e['msg']}" for e in exc.errors())
        raise AgentFileError(msgs) from None
    if expected_id is not None and cfg.id != expected_id:
        raise AgentFileError(f"file name '{expected_id}.yaml' must match id '{cfg.id}'")
    return cfg


def parse_agent_file(path: Path) -> tuple[AgentConfig, str]:
    data = path.read_bytes()
    return parse_agent_bytes(data, path.name[: -len(".yaml")]), hashlib.sha256(data).hexdigest()


def dump_agent_yaml(cfg: AgentConfig) -> str:
    return yaml.safe_dump(cfg.to_yaml_dict(), sort_keys=False, allow_unicode=True, default_flow_style=None)


def write_agent_file(agents_dir: Path, cfg: AgentConfig) -> Path:
    """Atomic write of agents/<id>.yaml."""
    agents_dir.mkdir(parents=True, exist_ok=True)
    path = agents_dir / f"{cfg.id}.yaml"
    tmp = agents_dir / f".{cfg.id}.yaml.tmp"
    tmp.write_text(dump_agent_yaml(cfg))
    tmp.replace(path)
    return path


def upsert_agent(conn: sqlite3.Connection, cfg: AgentConfig, path: Path, config_hash: str) -> str | None:
    """Insert/update the agents row. Returns 'added' | 'updated' | None (unchanged). Emits the matching event.
    Must run inside a transaction so API and worker never both report the same change."""
    row = conn.execute("SELECT config_hash, config_json, enabled FROM agents WHERE id=?", (cfg.id,)).fetchone()
    now = now_iso()
    config_json = dumps(cfg.to_yaml_dict())
    if row is None:
        conn.execute(
            "INSERT INTO agents(id, config_path, config_hash, config_json, enabled, paused, status, updated_at, "
            "counters_date) VALUES (?,?,?,?,?,0,?,?,NULL)",
            (cfg.id, str(path), config_hash, config_json, int(cfg.enabled), "idle" if cfg.enabled else "disabled",
             now),
        )
        conn.execute("INSERT OR IGNORE INTO agent_live(agent_id, updated_at, seq) VALUES (?,?,0)", (cfg.id, now))
        change = "added"
    elif row["config_hash"] != config_hash:
        previous = serializers._loads(row["config_json"], {})
        enabled = row["enabled"]
        if previous.get("enabled", True) != cfg.enabled:  # a hand edit of `enabled:` in YAML wins
            enabled = int(cfg.enabled)
        conn.execute(
            "UPDATE agents SET config_path=?, config_hash=?, config_json=?, enabled=?, updated_at=? WHERE id=?",
            (str(path), config_hash, config_json, enabled, now, cfg.id),
        )
        conn.execute("INSERT OR IGNORE INTO agent_live(agent_id, updated_at, seq) VALUES (?,?,0)", (cfg.id, now))
        change = "updated"
    else:
        return None
    agent = serializers.agent_json_by_id(conn, cfg.id)
    verb = "joined the team" if change == "added" else "config updated"
    repo.emit(conn, f"agent.{change}", f"{cfg.name} {verb}", agent_id=cfg.id, data={"agent": agent})
    return change


def remove_agent(conn: sqlite3.Connection, agent_id: str, reason: str = "config removed") -> bool:
    agent = serializers.agent_json_by_id(conn, agent_id)
    if agent is None:
        return False
    conn.execute("DELETE FROM agent_live WHERE agent_id=?", (agent_id,))
    conn.execute("DELETE FROM agents WHERE id=?", (agent_id,))
    agent["status"] = "disabled"
    repo.emit(conn, "agent.removed", f"{agent['name']} left the team ({reason})", agent_id=agent_id,
              data={"agent": agent})
    return True


def sync_file(conn: sqlite3.Connection, path: Path) -> tuple[AgentConfig, str | None]:
    cfg, h = parse_agent_file(path)
    with tx(conn):
        change = upsert_agent(conn, cfg, path, h)
    return cfg, change


class Registry:
    """In-memory view of valid agent configs, kept in sync with the directory and the DB."""

    def __init__(self, agents_dir: Path, conn: sqlite3.Connection):
        self.dir = Path(agents_dir)
        self.conn = conn
        self.configs: dict[str, AgentConfig] = {}
        self.draining: set[str] = set()
        self._bad: dict[str, str] = {}
        for row in repo.agent_rows(conn):  # last good configs survive a restart even if a file is now broken
            try:
                self.configs[row["id"]] = AgentConfig.model_validate(serializers._loads(row["config_json"], {}))
            except ValidationError:
                continue

    def scan(self, running: dict[str, int] | None = None) -> list[tuple[str, str]]:
        """Reconcile the directory with the DB. Returns [(agent_id, 'added'|'updated'|'removed'|'error')]."""
        running = running or {}
        changes: list[tuple[str, str]] = []
        seen: set[str] = set()
        files = sorted(self.dir.glob("*.yaml")) if self.dir.exists() else []
        for path in files:
            stem = path.name[: -len(".yaml")]
            try:
                data = path.read_bytes()
            except OSError:
                continue
            digest = hashlib.sha256(data).hexdigest()
            try:
                cfg = parse_agent_bytes(data, stem)
                if cfg.id in seen:
                    raise AgentFileError(f"duplicate agent id '{cfg.id}'")
            except AgentFileError as exc:
                if stem in self.configs:
                    seen.add(stem)  # keep the last good config running
                if self._bad.get(str(path)) != digest:
                    self._bad[str(path)] = digest
                    kept = " — keeping the last good config" if stem in self.configs else ""
                    with tx(self.conn):
                        repo.emit(self.conn, "error", f"Agent config {path.name} rejected: {exc}{kept}",
                                  level="error", agent_id=stem if stem in self.configs else None,
                                  data={"file": path.name, "error": str(exc)})
                    changes.append((stem, "error"))
                continue
            self._bad.pop(str(path), None)
            seen.add(cfg.id)
            with tx(self.conn):
                change = upsert_agent(self.conn, cfg, path, digest)
            self.configs[cfg.id] = cfg
            self.draining.discard(cfg.id)
            if change:
                changes.append((cfg.id, change))
        for row in repo.agent_rows(self.conn):
            agent_id = row["id"]
            if agent_id in seen:
                continue
            self.draining.add(agent_id)
            if running.get(agent_id, 0) == 0:
                with tx(self.conn):
                    remove_agent(self.conn, agent_id)
                self.configs.pop(agent_id, None)
                self.draining.discard(agent_id)
                changes.append((agent_id, "removed"))
        return changes

    async def watch(self, on_change: Callable[[], Any], stop: asyncio.Event) -> None:
        """Call on_change() whenever a YAML file in the agents dir changes (debounced)."""
        from watchfiles import awatch

        self.dir.mkdir(parents=True, exist_ok=True)

        def only_yaml(_change: Any, p: str) -> bool:
            return p.endswith(".yaml") or p.endswith(".yaml.disabled")

        while not stop.is_set():
            try:
                async for _ in awatch(self.dir, watch_filter=only_yaml, debounce=300, step=50, stop_event=stop,
                                      recursive=False):
                    on_change()
            except Exception as exc:  # watcher backends can fail (e.g. dir recreated); retry after a pause
                log.warning("agent watcher error: %s", exc)
                await asyncio.sleep(2)
