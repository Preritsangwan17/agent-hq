"""Process lifecycle: supervisor children never outlive a killed supervisor, stop.sh reaps leftovers safely,
and the start.sh bootstrap line is human-readable."""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.conftest import REPO_AGENTS

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie still answers kill -0; ask ps for the real state
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def _wait(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── parentwatch ──────────────────────────────────────────────────────────────────────────────────────
def test_watch_is_a_noop_without_a_supervisor(monkeypatch):
    from hq.util import parentwatch

    monkeypatch.delenv(parentwatch.ENV_KEY, raising=False)
    assert parentwatch.watch(lambda: None) is None


def test_watch_consumes_the_env_var_so_grandchildren_do_not_inherit_it(monkeypatch):
    from hq.util import parentwatch

    monkeypatch.setenv(parentwatch.ENV_KEY, str(os.getppid()))
    fired: list[bool] = []
    thread = parentwatch.watch(lambda: fired.append(True), interval_s=0.05)
    assert thread is not None and thread.daemon
    assert parentwatch.ENV_KEY not in os.environ
    time.sleep(0.2)
    assert not fired  # our parent is alive, so nothing happens


def test_watch_fires_when_the_expected_parent_is_not_our_parent(monkeypatch):
    from hq.util import parentwatch

    monkeypatch.setenv(parentwatch.ENV_KEY, "1" if os.getppid() != 1 else "2")
    fired: list[bool] = []
    thread = parentwatch.watch(lambda: fired.append(True), interval_s=0.05)
    assert thread is not None
    thread.join(2)
    assert fired == [True]


FAKE_SUPERVISOR = """
import os, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", sys.argv[1]], env={**os.environ, "HQ_SUPERVISOR_PID": str(os.getpid())})
print(child.pid, flush=True)
time.sleep(60)
"""
WATCHED_CHILD = """
import os, time
from hq.util import parentwatch
parentwatch.watch(lambda: os._exit(0), interval_s=0.1)
time.sleep(60)
"""


def test_child_exits_when_its_supervisor_is_killed():
    sup = subprocess.Popen([PY, "-c", FAKE_SUPERVISOR, WATCHED_CHILD], cwd=ROOT, stdout=subprocess.PIPE, text=True)
    try:
        child_pid = int(sup.stdout.readline())
        time.sleep(0.5)
        assert _alive(child_pid)
        sup.kill()
        sup.wait()
        assert _wait(lambda: not _alive(child_pid), 5), "child outlived its supervisor"
    finally:
        sup.kill()
        sup.wait()


# ── the real supervisor ──────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def stack_env(tmp_path: Path) -> dict[str, str]:
    agents = tmp_path / "agents"
    agents.mkdir()
    for path in REPO_AGENTS.glob("*.yaml"):
        shutil.copy(path, agents / path.name)
    env = {**os.environ, "HQ_DB_PATH": str(tmp_path / "hq.db"), "HQ_ENV_FILE": str(tmp_path / ".env"),
           "HQ_RUN_DIR": str(tmp_path / "run"), "HQ_LOG_DIR": str(tmp_path / "logs"), "HQ_AGENTS_DIR": str(agents),
           "HQ_PORT": str(_free_port())}
    for key in ("HQ_LAN", "HQ_PASSCODE_HASH", "HQ_SESSION_SECRET", "HQ_SUPERVISOR_PID"):
        env.pop(key, None)
    return env


def _pidfile(env: dict[str, str], name: str) -> int | None:
    path = Path(env["HQ_RUN_DIR"]) / f"{name}.pid"
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return None


def _healthy(env: dict[str, str]) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{env['HQ_PORT']}/api/health", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


def test_supervisor_kill9_leaves_no_orphans_and_stop_sh_cleans_up(stack_env):
    sup = subprocess.Popen([PY, "-m", "hq.supervisor"], cwd=ROOT, env=stack_env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    try:
        assert _wait(lambda: _healthy(stack_env) and _pidfile(stack_env, "worker"), 30), "stack did not come up"
        api, worker = _pidfile(stack_env, "api"), _pidfile(stack_env, "worker")
        assert api and worker and _alive(api) and _alive(worker)
        sup.send_signal(signal.SIGKILL)
        sup.wait()
        assert _wait(lambda: not _alive(api) and not _alive(worker), 15), "API/worker outlived the supervisor"
        assert _wait(lambda: not _healthy(stack_env), 2)  # the port is free again
        out = subprocess.run(["bash", str(ROOT / "stop.sh")], env=stack_env, capture_output=True, text=True,
                             timeout=60)
        assert out.returncode == 0, out.stderr
        assert "stale pidfile" in out.stdout
        run = Path(stack_env["HQ_RUN_DIR"])
        assert not (run / "supervisor.pid").exists() and not (run / "api.pid").exists()
        assert not (run / "worker.pid").exists()
    finally:
        if sup.poll() is None:
            sup.kill()
            sup.wait()


def test_clean_supervisor_stop_removes_child_pidfiles(stack_env):
    sup = subprocess.Popen([PY, "-m", "hq.supervisor"], cwd=ROOT, env=stack_env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    try:
        assert _wait(lambda: _healthy(stack_env) and _pidfile(stack_env, "worker"), 30), "stack did not come up"
        api, worker = _pidfile(stack_env, "api"), _pidfile(stack_env, "worker")
        out = subprocess.run(["bash", str(ROOT / "stop.sh")], env=stack_env, capture_output=True, text=True,
                             timeout=60)
        assert out.returncode == 0 and "stopped" in out.stdout, out.stdout + out.stderr
        assert sup.wait(5) == 0
        assert not _alive(api) and not _alive(worker)
        assert not any((Path(stack_env["HQ_RUN_DIR"]) / f"{n}.pid").exists() for n in ("supervisor", "api", "worker"))
    finally:
        if sup.poll() is None:
            sup.kill()
            sup.wait()


# ── stop.sh reaping ──────────────────────────────────────────────────────────────────────────────────
def test_stop_sh_reaps_a_leftover_worker_but_never_an_unrelated_pid(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    # looks like `python -m hq.worker` to ps; sleeps until signalled
    leftover = subprocess.Popen([PY, "-c", "import time; time.sleep(60)", "-m", "hq.worker"])
    bystander = subprocess.Popen(["sleep", "60"])
    try:
        (run / "worker.pid").write_text(str(leftover.pid))
        (run / "api.pid").write_text(str(bystander.pid))  # a recycled pid: must not be touched
        out = subprocess.run(["bash", str(ROOT / "stop.sh")], env={**os.environ, "HQ_RUN_DIR": str(run)},
                             capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        assert f"stopping leftover worker pid {leftover.pid}" in out.stdout and "stopped" in out.stdout
        assert leftover.wait(5) == -signal.SIGTERM
        assert bystander.poll() is None
        assert not (run / "worker.pid").exists() and not (run / "api.pid").exists()
    finally:
        for proc in (leftover, bystander):
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_stop_sh_when_nothing_runs(tmp_path):
    out = subprocess.run(["bash", str(ROOT / "stop.sh")], env={**os.environ, "HQ_RUN_DIR": str(tmp_path)},
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and "not running" in out.stdout


# ── bootstrap line printed by start.sh ───────────────────────────────────────────────────────────────
def test_bootstrap_summary_is_friendly(hq_env, monkeypatch):
    from hq import settings
    from hq.util.bootstrap import summary

    monkeypatch.setattr(settings, "DB_PATH", settings.ROOT / "data" / "hq.db")
    assert summary([1, 2], 18, 10) == "database ready (data/hq.db, migrated to v2, 18 default settings added) · 10 agents"
    assert summary([], 0, 11) == "database ready (data/hq.db, up to date) · 11 agents"
    monkeypatch.setattr(settings, "DB_PATH", Path("/elsewhere/hq.db"))
    assert summary([], 0, 1).startswith("database ready (/elsewhere/hq.db, up to date)")
    assert summary([], 0, 10, 11) == "database ready (/elsewhere/hq.db, up to date) · 10 agents · 11 legacy applications imported"
