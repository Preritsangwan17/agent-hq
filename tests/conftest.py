"""Shared pytest fixtures. Every test runs against a throwaway DB/.env/agents dir under tmp_path, and the
module-level defaults below make sure nothing can fall back to Prerit's real `.env` or `data/hq.db`."""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

_SESSION_DIR = Path(tempfile.mkdtemp(prefix="hq-pytest-"))
for _key, _value in {
    "HQ_DB_PATH": _SESSION_DIR / "default.db",
    "HQ_ENV_FILE": _SESSION_DIR / "default.env",
    "HQ_AGENTS_DIR": _SESSION_DIR / "agents",
    "HQ_RUN_DIR": _SESSION_DIR / "run",
    "HQ_LOG_DIR": _SESSION_DIR / "logs",
}.items():
    os.environ.setdefault(_key, str(_value))

REPO_AGENTS = Path(__file__).resolve().parent.parent / "agents"
MUTATE = {"X-HQ": "1", "Origin": "http://localhost:5173"}
PASSCODE = "correct-horse-42"


@pytest.fixture
def hq_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    from hq import settings

    env = SimpleNamespace(root=tmp_path, db=tmp_path / "hq.db", env_file=tmp_path / ".env",
                          agents=tmp_path / "agents", run=tmp_path / "run", logs=tmp_path / "logs")
    env.agents.mkdir()
    for attr, value in {"DATA": tmp_path, "DB_PATH": env.db, "ENV_PATH": env.env_file, "AGENTS_DIR": env.agents,
                        "RUN_DIR": env.run, "LOG_DIR": env.logs, "ARTIFACTS": tmp_path / "artifacts",
                        "WEB_DIST": tmp_path / "web-dist"}.items():
        monkeypatch.setattr(settings, attr, value)
    for key, value in {"HQ_DB_PATH": env.db, "HQ_ENV_FILE": env.env_file, "HQ_AGENTS_DIR": env.agents,
                       "HQ_RUN_DIR": env.run, "HQ_LOG_DIR": env.logs}.items():
        monkeypatch.setenv(key, str(value))
    for key in ("HQ_PASSCODE_HASH", "HQ_SESSION_SECRET", "HQ_LAN", "HQ_ALLOWED_HOSTS"):
        monkeypatch.delenv(key, raising=False)
    return env


@pytest.fixture
def db(hq_env: SimpleNamespace):
    from hq.db.conn import connect, tx
    from hq.db.migrate import migrate
    from hq.db.seed import seed_settings

    conn = connect()
    migrate(conn)
    with tx(conn):
        seed_settings(conn)
    yield conn
    conn.close()


@pytest.fixture
def team(hq_env: SimpleNamespace) -> Path:
    """The real 10 starting agents copied into the temp agents dir."""
    for path in REPO_AGENTS.glob("*.yaml"):
        shutil.copy(path, hq_env.agents / path.name)
    return hq_env.agents


def write_agent(agents_dir: Path, agent_id: str, **overrides: Any) -> Path:
    import yaml

    cfg: dict[str, Any] = {"id": agent_id, "name": agent_id.title(), "avatar": "🤖", "color": "#94A3B8",
                           "role": agent_id, "adapter": "sim", "capabilities": ["summarize"], "concurrency": 1,
                           "schedule": {"mode": "on_demand"}, "enabled": True, "builtin": False}
    cfg.update(overrides)
    path = agents_dir / f"{agent_id}.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    return path


@pytest.fixture
def app(hq_env: SimpleNamespace, db):
    from hq.api.app import create_app

    return create_app()


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        yield c


@pytest.fixture
def authed(client):
    r = client.post("/api/auth/setup", json={"passcode": PASSCODE}, headers=MUTATE)
    assert r.status_code == 200, r.text
    assert client.cookies.get("hq_session")
    return client


async def drive(worker: Any, predicate: Callable[[], bool], timeout: float = 10.0) -> bool:
    """Tick a Worker (already started) until predicate() is true or the timeout passes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await worker.tick()
        if predicate():
            return True
        await asyncio.sleep(worker.loop_interval)
    return predicate()
