"""ModelManager (CONTRACT_B §2, PLAN "Model manager › Memory policy"). Lives in the worker.

`async with manager.use(model_id) as ep:` makes sure the model is served and returns its endpoint
(`ep.base_url`, `ep.served_id`). MLX models get one `mlx_lm.server` process each on 127.0.0.1:8101–8120; GGUF files
get `llama-server`; Ollama and LM Studio manage their own memory, so their endpoints are returned as-is.

Loading policy: need = measured RAM (else estimate). Load only when pool_used + need ≤ pool budget AND system
available ≥ need + 4 GB AND memory pressure is normal; otherwise evict idle, unpinned servers in LRU order; if it
still doesn't fit, raise WaitingMemory and the task waits. Usability mode shrinks the pool to 8 GB while Prerit is
using the Mac, on battery or in quiet hours (so the 30B MoE unloads). Health is checked every 30 s; a server is
restarted at most 3 times in 10 minutes, then marked broken so routing falls back to the next model.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Protocol

import httpx

from hq import settings as paths
from hq.db import repo
from hq.db.conn import dumps, tx
from hq.db.seed import get_settings
from hq.models import memory as mem
from hq.util.ids import new_id
from hq.util.timeutil import IST, now_iso

log = logging.getLogger("hq.models")

PORTS = range(8101, 8121)
HEADROOM_GB = 4.0
USABILITY_POOL_GB = 8.0
IDLE_TTL_S = 20 * 60
HEALTH_EVERY_S = 30.0
LOAD_TIMEOUT_S = 120.0
MAX_RESTARTS, RESTART_WINDOW_S = 3, 600


class WaitingMemory(Exception):
    def __init__(self, model_id: str, need_gb: float, detail: str):
        super().__init__(f"{model_id} needs {need_gb:.1f} GB: {detail}")
        self.model_id, self.need_gb, self.detail = model_id, need_gb, detail


class ModelBroken(Exception):
    pass


class Proc(Protocol):
    pid: int

    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


Spawner = Callable[[list[str], int, str], Proc]


def default_spawner(argv: list[str], port: int, model_id: str) -> Proc:
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logf = open(paths.LOG_DIR / f"model-{port}.log", "a", buffering=1)
    logf.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {model_id} ---\n")
    return subprocess.Popen(argv, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            cwd=paths.ROOT, start_new_session=True)


async def default_health(base_url: str) -> bool:
    root = base_url.rsplit("/v1", 1)[0]
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            for path in ("/health", "/v1/models"):
                r = await c.get(root + path)
                if r.status_code == 200:
                    return True
    except httpx.HTTPError:
        return False
    return False


@dataclass
class Endpoint:
    model_id: str
    base_url: str
    served_id: str
    managed: bool


@dataclass
class Server:
    model_id: str
    port: int
    proc: Proc | None
    pid: int
    started: float
    last_used: float
    need_gb: float
    footprint_gb: float | None = None
    peak_gb: float | None = None
    in_use: int = 0
    row_id: str = field(default_factory=new_id)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def used_gb(self) -> float:
        return max(self.footprint_gb or 0.0, self.need_gb)


class ModelManager:
    def __init__(self, conn: sqlite3.Connection, *, spawner: Spawner | None = None,
                 health: Callable[[str], Any] | None = None,
                 memory_fn: Callable[[], mem.SystemMemory] = mem.system_memory,
                 footprint_fn: Callable[[int], tuple[float, float] | None] = mem.phys_footprint_gb,
                 active_fn: Callable[[], bool] = mem.user_active, battery_fn: Callable[[], bool] = mem.on_battery,
                 clock: Callable[[], float] = time.monotonic, load_timeout_s: float = LOAD_TIMEOUT_S,
                 python: str | None = None):
        self.conn = conn
        self.spawner = spawner or default_spawner
        self.health = health or default_health
        self.memory_fn = memory_fn
        self.footprint_fn = footprint_fn
        self.active_fn = active_fn
        self.battery_fn = battery_fn
        self.clock = clock
        self.load_timeout_s = load_timeout_s
        self.python = python or sys.executable
        self.servers: dict[str, Server] = {}
        self.restarts: dict[str, deque[float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_health = 0.0
        self._usability_reason: str | None = None

    # ── policy ──────────────────────────────────────────────────────────────────────────────────────
    def settings(self) -> dict[str, Any]:
        return get_settings(self.conn)

    def usability_reason(self, s: dict[str, Any] | None = None) -> str | None:
        s = s or self.settings()
        if not s.get("usability_mode", True):
            return None
        if _in_quiet_hours(s.get("quiet_hours") or {}):
            return "quiet hours"
        if self.battery_fn():
            return "on battery"
        if self.active_fn():
            return "you are using the Mac"
        return None

    def pool_budget_gb(self, s: dict[str, Any] | None = None) -> float:
        s = s or self.settings()
        budget = float(s.get("model_pool_budget_gb", 30))
        self._usability_reason = self.usability_reason(s)
        return min(budget, USABILITY_POOL_GB) if self._usability_reason else budget

    def pool_used_gb(self) -> float:
        return round(sum(sv.used_gb for sv in self.servers.values()), 2)

    def _model(self, model_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        if row is None:
            raise ModelBroken(f"unknown model {model_id}")
        d = dict(row)
        try:
            import json
            d["meta"] = json.loads(d.get("fingerprint") or "{}")
        except ValueError:
            d["meta"] = {}
        return d

    def need_gb(self, m: dict[str, Any]) -> float:
        return float(m.get("measured_ram_gb") or m.get("est_ram_gb") or 4.0)

    def _fits(self, need: float, budget: float) -> tuple[bool, str]:
        sysmem = self.memory_fn()
        used = self.pool_used_gb()
        if used + need > budget + 1e-9:
            return False, f"pool {used:.1f}+{need:.1f} GB > budget {budget:.1f} GB"
        if sysmem.available_gb < need + HEADROOM_GB:
            return False, f"only {sysmem.available_gb:.1f} GB free (need {need:.1f}+{HEADROOM_GB:.0f})"
        if sysmem.pressure != "normal":
            return False, f"memory pressure {sysmem.pressure}"
        return True, ""

    def _evictable(self, *, include_pinned: bool = False) -> list[Server]:
        pinned = {r["id"] for r in self.conn.execute("SELECT id FROM models WHERE pinned=1")}
        return sorted((sv for sv in self.servers.values()
                       if sv.in_use == 0 and (include_pinned or sv.model_id not in pinned)),
                      key=lambda sv: sv.last_used)

    # ── endpoints ───────────────────────────────────────────────────────────────────────────────────
    @contextlib.asynccontextmanager
    async def use(self, model_id: str) -> AsyncIterator[Endpoint]:
        ep = await self.ensure(model_id)
        sv = self.servers.get(model_id)
        if sv:
            sv.in_use += 1
        try:
            yield ep
        finally:
            if sv:
                sv.in_use = max(0, sv.in_use - 1)
                sv.last_used = self.clock()
                self._touch(sv)

    def local_off(self, s: dict[str, Any] | None = None) -> bool:
        """Compatibility hook: Local AI can no longer be switched off."""
        return False  # Local AI is required in every mode, including legacy databases.

    async def ensure(self, model_id: str) -> Endpoint:
        if self.local_off():
            raise ModelBroken("local models are switched off in Settings")
        m = self._model(model_id)
        meta = m["meta"]
        if m["runtime"] in ("ollama", "lmstudio"):
            return Endpoint(model_id, meta.get("base_url") or "", meta.get("served_id") or m["name"], managed=False)
        if m["status"] == "broken":
            raise ModelBroken(f"{model_id} is marked broken")
        if not (m["complete"] and m["runtime_supported"]):
            raise ModelBroken(f"{model_id} is not usable ({m['incomplete_reason'] or 'unsupported'})")
        lock = self._locks.setdefault(model_id, asyncio.Lock())
        async with lock:
            sv = self.servers.get(model_id)
            if sv and (sv.proc is None or sv.proc.poll() is None):
                sv.last_used = self.clock()
                return Endpoint(model_id, sv.base_url, meta.get("served_id") or m["name"], managed=True)
            if sv:
                self._forget(sv, "exited")
            need = self.need_gb(m)
            budget = self.pool_budget_gb()
            ok, why = self._fits(need, budget)
            if not ok:
                # never evict for a load that can't fit even with every idle, unpinned model gone
                victims = self._evictable()
                reclaim = sum(v.used_gb for v in victims)
                sysmem = self.memory_fn()
                if (self.pool_used_gb() - reclaim + need > budget + 1e-9
                        or sysmem.available_gb + reclaim < need + HEADROOM_GB or not victims):
                    raise WaitingMemory(model_id, need, why)
            while not ok:
                victims = self._evictable()
                if not victims:
                    raise WaitingMemory(model_id, need, why)
                await self._stop(victims[0], reason=f"evicted to make room for {model_id}")
                ok, why = self._fits(need, budget)
            sv = await self._start(m, need)
            return Endpoint(model_id, sv.base_url, meta.get("served_id") or m["name"], managed=True)

    def argv_for(self, m: dict[str, Any], port: int) -> list[str]:
        meta = m["meta"]
        if m["runtime"] == "mlx":
            argv = [self.python, "-m", "mlx_lm.server", "--model", meta.get("served_id") or m["name"],
                    "--host", "127.0.0.1", "--port", str(port), "--max-tokens", "2048"]
            if meta.get("qwen3") or (m.get("model_type") or "").startswith("qwen3"):
                argv += ["--chat-template-args", '{"enable_thinking":false}']
            return argv
        if m["runtime"] == "llamacpp":
            server = meta.get("server_bin") or "llama-server"
            return [server, "-m", m["path"], "--host", "127.0.0.1", "--port", str(port), "-c", "8192", "--jinja"]
        raise ModelBroken(f"don't know how to serve runtime {m['runtime']}")

    def _free_port(self) -> int:
        used = {sv.port for sv in self.servers.values()}
        used |= {r[0] for r in self.conn.execute("SELECT port FROM model_servers WHERE status IN ('starting','running')")
                 if r[0]}
        for p in PORTS:
            if p not in used:
                return p
        raise WaitingMemory("?", 0, "all model-server ports 8101–8120 are in use")

    async def _start(self, m: dict[str, Any], need: float) -> Server:
        port = self._free_port()
        argv = self.argv_for(m, port)
        with tx(self.conn):
            repo.emit(self.conn, "model.status", f"Loading {m['name']} on :{port} (~{need:.1f} GB)",
                      data={"model_id": m["id"], "status": "loading", "port": port})
        proc = self.spawner(argv, port, m["id"])
        now = self.clock()
        sv = Server(m["id"], port, proc, proc.pid, now, now, need)
        self.servers[m["id"]] = sv
        with tx(self.conn):
            self.conn.execute("INSERT INTO model_servers(id, model_id, pid, port, started_at, last_used_at, status) "
                              "VALUES (?,?,?,?,?,?, 'starting')", (sv.row_id, m["id"], proc.pid, port, now_iso(), now_iso()))
        deadline = time.monotonic() + self.load_timeout_s
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                self._forget(sv, "failed to start")
                self._record_restart(m["id"], f"server exited with {proc.poll()} while loading")
                raise ModelBroken(f"{m['id']}: server exited while loading (see data/logs/model-{port}.log)")
            if await self.health(sv.base_url):
                break
            await asyncio.sleep(0.5)
        else:
            await self._stop(sv, reason="load timed out")
            self._record_restart(m["id"], "load timed out")
            raise ModelBroken(f"{m['id']}: not healthy after {self.load_timeout_s:.0f} s")
        self._measure(sv)
        with tx(self.conn):
            self.conn.execute("UPDATE model_servers SET status='running', footprint_gb=? WHERE id=?",
                              (sv.footprint_gb, sv.row_id))
            self.conn.execute("UPDATE models SET status='loaded', updated_at=? WHERE id=?", (now_iso(), m["id"]))
            repo.emit(self.conn, "model.status", f"Loaded {m['name']} on :{port}",
                      data={"model_id": m["id"], "status": "loaded", "port": port, "footprint_gb": sv.footprint_gb})
        return sv

    def _measure(self, sv: Server) -> None:
        fp = self.footprint_fn(sv.pid) if sv.pid else None
        if fp:
            sv.footprint_gb, peak = round(fp[0], 2), round(fp[1], 2)
            sv.peak_gb = max(sv.peak_gb or 0, peak)
            with tx(self.conn):
                self.conn.execute("UPDATE models SET measured_ram_gb=MAX(COALESCE(measured_ram_gb,0), ?) WHERE id=?",
                                  (sv.peak_gb, sv.model_id))

    def _touch(self, sv: Server) -> None:
        try:
            self.conn.execute("UPDATE model_servers SET last_used_at=? WHERE id=?", (now_iso(), sv.row_id))
        except sqlite3.Error:
            pass

    async def _stop(self, sv: Server, *, reason: str) -> None:
        if sv.proc is not None and sv.proc.poll() is None:
            sv.proc.terminate()
            for _ in range(40):
                if sv.proc.poll() is not None:
                    break
                await asyncio.sleep(0.25)
            else:
                sv.proc.kill()
        elif sv.proc is None and sv.pid:
            _kill_pid(sv.pid)
        self._forget(sv, reason)

    def _forget(self, sv: Server, reason: str) -> None:
        self.servers.pop(sv.model_id, None)
        with tx(self.conn):
            self.conn.execute("UPDATE model_servers SET status='stopped' WHERE id=?", (sv.row_id,))
            self.conn.execute("UPDATE models SET status='available', updated_at=? WHERE id=? AND status='loaded'",
                              (now_iso(), sv.model_id))
            repo.emit(self.conn, "model.status", f"Unloaded {sv.model_id} ({reason})", level="debug",
                      data={"model_id": sv.model_id, "status": "available", "reason": reason})

    def _record_restart(self, model_id: str, why: str) -> bool:
        """Count a failure; returns True when the model just crossed into `broken`."""
        q = self.restarts.setdefault(model_id, deque())
        now = self.clock()
        q.append(now)
        while q and now - q[0] > RESTART_WINDOW_S:
            q.popleft()
        if len(q) > MAX_RESTARTS:
            with tx(self.conn):
                self.conn.execute("UPDATE models SET status='broken', updated_at=? WHERE id=?", (now_iso(), model_id))
                repo.emit(self.conn, "model.status", f"{model_id} marked broken after {len(q)} failures in 10 min "
                          f"({why}); routing falls back", level="error",
                          data={"model_id": model_id, "status": "broken", "reason": why})
            return True
        return False

    async def unload(self, model_id: str, reason: str = "unloaded by Prerit") -> bool:
        sv = self.servers.get(model_id)
        if not sv:
            return False
        await self._stop(sv, reason=reason)
        return True

    # ── upkeep ──────────────────────────────────────────────────────────────────────────────────────
    async def tick(self, force: bool = False) -> None:
        now = self.clock()
        if not force and now - self._last_health < HEALTH_EVERY_S:
            return
        self._last_health = now
        if self.local_off():
            for sv in list(self.servers.values()):
                if sv.in_use == 0:
                    await self._stop(sv, reason="local models switched off")
            return
        budget = self.pool_budget_gb()
        for sv in list(self.servers.values()):
            alive = sv.proc.poll() is None if sv.proc is not None else _pid_alive(sv.pid)
            healthy = alive and await self.health(sv.base_url)
            if not healthy:
                self._forget(sv, "crashed" if not alive else "unhealthy")
                if sv.proc is not None and sv.proc.poll() is None:
                    sv.proc.kill()
                if not self._record_restart(sv.model_id, "health check failed"):
                    try:
                        await self.ensure(sv.model_id)
                        with tx(self.conn):
                            repo.emit(self.conn, "model.status", f"Restarted {sv.model_id} after a failed health check",
                                      level="warn", data={"model_id": sv.model_id, "status": "loaded"})
                    except (WaitingMemory, ModelBroken) as exc:
                        log.warning("restart of %s failed: %s", sv.model_id, exc)
                continue
            self._measure(sv)
            pinned = bool(self.conn.execute("SELECT pinned FROM models WHERE id=?", (sv.model_id,)).fetchone()[0])
            if sv.in_use == 0 and not pinned and now - sv.last_used > IDLE_TTL_S:
                await self._stop(sv, reason="idle for 20 min")
        # usability mode / pool shrink: unload until the pool fits (pinned too — the Mac's usability wins)
        while self.pool_used_gb() > budget + 1e-9:
            victims = self._evictable(include_pinned=True)
            if not victims:
                break
            await self._stop(victims[0], reason=f"pool budget {budget:.0f} GB ({self._usability_reason or 'settings'})")

    def adopt_or_reap(self) -> dict[str, int]:
        """Startup: servers recorded by a previous worker are killed (their memory is unaccounted for)."""
        reaped = 0
        rows = self.conn.execute("SELECT * FROM model_servers WHERE status IN ('starting','running')").fetchall()
        with tx(self.conn):
            for r in rows:
                if r["pid"] and _pid_alive(r["pid"]) and _looks_like_model_server(r["pid"]):
                    _kill_pid(r["pid"])
                    reaped += 1
                self.conn.execute("UPDATE model_servers SET status='stopped' WHERE id=?", (r["id"],))
            self.conn.execute("UPDATE models SET status='available' WHERE status='loaded'")
        return {"reaped": reaped}

    async def shutdown(self) -> None:
        for sv in list(self.servers.values()):
            await self._stop(sv, reason="worker stopping")

    def state(self) -> dict[str, Any]:
        s = self.settings()
        sysmem = self.memory_fn()
        budget = self.pool_budget_gb(s)
        return {"total_gb": sysmem.total_gb, "available_gb": sysmem.available_gb, "pool_used_gb": self.pool_used_gb(),
                "pool_budget_gb": budget, "pressure": sysmem.pressure, "user_active": self.active_fn(),
                "on_battery": self.battery_fn(), "usability_mode": bool(s.get("usability_mode", True)),
                "usability_reason": self._usability_reason,
                "servers": [{"model_id": sv.model_id, "port": sv.port, "pid": sv.pid, "footprint_gb": sv.footprint_gb,
                             "need_gb": sv.need_gb, "in_use": sv.in_use} for sv in self.servers.values()]}

    def publish_state(self) -> None:
        """The API process can't see this object: mirror the memory state into settings for GET /api/models."""
        from hq.db.seed import set_settings

        with tx(self.conn):
            set_settings(self.conn, {"model_manager_state": {**self.state(), "at": now_iso()}}, by="worker")


def _in_quiet_hours(q: dict[str, Any], now: datetime | None = None) -> bool:
    if not q.get("enabled"):
        return False
    n = (now or datetime.now(IST)).astimezone(IST)
    m = n.hour * 60 + n.minute
    a = int(q["start"][:2]) * 60 + int(q["start"][3:])
    b = int(q["end"][:2]) * 60 + int(q["end"][3:])
    return a <= m < b if a <= b else m >= a or m < b


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _looks_like_model_server(pid: int) -> bool:
    try:
        import psutil

        cmd = " ".join(psutil.Process(pid).cmdline())
    except Exception:
        return False
    return "mlx_lm.server" in cmd or "llama-server" in cmd


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def dumps_state(state: dict[str, Any]) -> str:
    return dumps(state)
