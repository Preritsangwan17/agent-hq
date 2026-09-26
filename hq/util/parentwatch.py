"""Children of `hq.supervisor` exit when the supervisor itself dies (kill -9, crash), so an orphaned API or worker
can never keep holding the port or the worker lock and block the next `./start.sh`.

The supervisor passes its pid in HQ_SUPERVISOR_PID. A process started any other way (tests, `python -m hq.api` by
hand) has no such variable and is not watched."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

ENV_KEY = "HQ_SUPERVISOR_PID"
log = logging.getLogger("hq.parentwatch")


def supervisor_pid() -> int | None:
    value = os.environ.get(ENV_KEY, "").strip()
    return int(value) if value.isdigit() else None


def orphaned(expected: int) -> bool:
    """True once this process has been re-parented away from the supervisor that started it (i.e. it died)."""
    return os.getppid() != expected


def watch(on_orphan: Callable[[], None], interval_s: float = 1.0) -> threading.Thread | None:
    """Poll in a daemon thread and call on_orphan() once when the supervisor is gone. No-op when unsupervised.
    The variable is removed from os.environ so grandchildren (model servers, CLIs) never inherit the watch."""
    expected = supervisor_pid()
    os.environ.pop(ENV_KEY, None)
    if expected is None:
        return None

    def loop() -> None:
        while not orphaned(expected):
            time.sleep(interval_s)
        log.warning("supervisor pid %s is gone; shutting down", expected)
        try:
            on_orphan()
        except Exception as exc:  # e.g. the event loop already closed: the process is exiting anyway
            log.warning("orphan shutdown hook failed: %s", exc)

    thread = threading.Thread(target=loop, name="parent-watch", daemon=True)
    thread.start()
    return thread
