"""`python -m hq.supervisor`: keeps `hq.api` and `hq.worker` running.

Restarts a child that exits with exponential backoff (1 s → 60 s, reset after 60 s of healthy uptime), writes
`data/run/supervisor.pid`, holds `caffeinate -i -w <pid>` while the `keep_awake` setting is on, and on
SIGTERM/SIGINT stops the children gracefully (SIGTERM, then SIGKILL after 15 s)."""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from hq import settings

log = logging.getLogger("hq.supervisor")
BACKOFF_MIN_S, BACKOFF_MAX_S, HEALTHY_AFTER_S = 1.0, 60.0, 60.0
STOP_GRACE_S = 15.0


@dataclass
class Child:
    name: str
    argv: list[str]
    proc: subprocess.Popen | None = None
    started_at: float = 0.0
    backoff: float = BACKOFF_MIN_S
    next_start: float = 0.0
    restarts: int = 0
    log_file: IO | None = field(default=None, repr=False)


class Supervisor:
    def __init__(self) -> None:
        self.children = [
            Child("api", [sys.executable, "-m", "hq.api"]),
            Child("worker", [sys.executable, "-m", "hq.worker"]),
        ]
        self.stopping = False
        self.caffeinate: subprocess.Popen | None = None
        self.pidfile = settings.RUN_DIR / "supervisor.pid"
        self._last_settings_check = 0.0

    # ── pidfile ─────────────────────────────────────────────────────────────────────────────────────
    def claim_pidfile(self) -> bool:
        if self.pidfile.exists():
            try:
                pid = int(self.pidfile.read_text().strip())
                os.kill(pid, 0)
            except (ValueError, ProcessLookupError):
                pass
            except PermissionError:
                return False
            else:
                if pid != os.getpid():
                    return False
        self.pidfile.write_text(str(os.getpid()))
        return True

    def release_pidfile(self) -> None:
        try:
            if self.pidfile.read_text().strip() == str(os.getpid()):
                self.pidfile.unlink()
        except OSError:
            pass

    # ── children ────────────────────────────────────────────────────────────────────────────────────
    def spawn(self, child: Child) -> None:
        if child.log_file is None:
            child.log_file = open(settings.LOG_DIR / f"{child.name}.log", "a", buffering=1)
        child.log_file.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} starting {child.name} ---\n")
        child.proc = subprocess.Popen(child.argv, cwd=settings.ROOT, stdout=child.log_file, stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL, env=os.environ.copy())
        child.started_at = time.monotonic()
        log.info("started %s pid=%s", child.name, child.proc.pid)

    def record_exit(self, child: Child, code: int) -> None:
        uptime = time.monotonic() - child.started_at
        if uptime > HEALTHY_AFTER_S:
            child.backoff = BACKOFF_MIN_S
        delay = child.backoff
        child.next_start = time.monotonic() + delay
        child.backoff = min(child.backoff * 2, BACKOFF_MAX_S)
        child.restarts += 1
        log.warning("%s exited with %s after %.1fs; restarting in %.0fs", child.name, code, uptime, delay)
        self._event(f"Supervisor: {child.name} exited ({_describe(code)}); restarting in {delay:.0f}s",
                    {"child": child.name, "exit_code": code, "restart_in_s": delay, "restarts": child.restarts})
        child.proc = None

    def _event(self, message: str, data: dict) -> None:
        try:
            from hq.db import repo
            from hq.db.conn import connect, tx

            conn = connect()
            try:
                with tx(conn):
                    repo.emit(conn, "log", message, level="warn", data=data)
            finally:
                conn.close()
        except Exception as exc:  # the DB may be unavailable; logging is best effort
            log.warning("could not record event: %s", exc)

    # ── keep awake ──────────────────────────────────────────────────────────────────────────────────
    def _keep_awake_wanted(self) -> bool:
        try:
            from hq.db.conn import connect
            from hq.db.seed import get_setting

            conn = connect()
            try:
                return bool(get_setting(conn, "keep_awake", True))
            finally:
                conn.close()
        except Exception:
            return True

    def sync_caffeinate(self) -> None:
        want = self._keep_awake_wanted() and shutil.which("caffeinate") is not None
        alive = self.caffeinate is not None and self.caffeinate.poll() is None
        if want and not alive:
            self.caffeinate = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())],
                                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL)
            log.info("caffeinate -i -w %s (pid %s)", os.getpid(), self.caffeinate.pid)
        elif not want and alive:
            self.caffeinate.terminate()
            self.caffeinate = None
            log.info("keep_awake off: stopped caffeinate")

    # ── main loop ───────────────────────────────────────────────────────────────────────────────────
    def request_stop(self, signum: int, _frame: object) -> None:
        log.info("signal %s: stopping", signum)
        self.stopping = True

    def run(self) -> int:
        settings.load_env()
        settings.ensure_dirs()
        if not self.claim_pidfile():
            log.error("another supervisor is running (%s)", self.pidfile)
            return 1
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        log.info("supervisor pid=%s port=%s", os.getpid(), settings.API_PORT)
        try:
            for child in self.children:
                self.spawn(child)
            self.sync_caffeinate()
            while not self.stopping:
                now = time.monotonic()
                for child in self.children:
                    if child.proc is not None:
                        code = child.proc.poll()
                        if code is not None:
                            self.record_exit(child, code)
                    elif now >= child.next_start and not self.stopping:
                        self.spawn(child)
                if now - self._last_settings_check > 10:
                    self._last_settings_check = now
                    self.sync_caffeinate()
                time.sleep(0.25)
        finally:
            self.shutdown()
        return 0

    def shutdown(self) -> None:
        for child in self.children:
            if child.proc and child.proc.poll() is None:
                child.proc.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + STOP_GRACE_S
        for child in self.children:
            if child.proc is None:
                continue
            try:
                child.proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                log.warning("%s did not stop in time; killing", child.name)
                child.proc.kill()
                child.proc.wait()
            if child.log_file:
                child.log_file.close()
        if self.caffeinate and self.caffeinate.poll() is None:
            self.caffeinate.terminate()
        self.release_pidfile()
        log.info("supervisor stopped")


def _describe(code: int) -> str:
    if code < 0:
        try:
            return f"signal {signal.Signals(-code).name}"
        except ValueError:
            return f"signal {-code}"
    return f"code {code}"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return Supervisor().run()


if __name__ == "__main__":
    sys.exit(main())
