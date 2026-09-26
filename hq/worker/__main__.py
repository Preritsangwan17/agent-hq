"""`python -m hq.worker`: run the orchestrator until SIGTERM/SIGINT. Holds an exclusive lock so only one worker
ever leases tasks for a given run directory."""
from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import signal
import sys

from hq import settings
from hq.util import parentwatch
from hq.worker.orchestrator import Worker


REFUSE_EXIT = 78  # EX_CONFIG: the supervisor does not restart a worker that refused for safety


def _record_refusal(reason: str | None) -> None:
    """Show the refusal (or clear it) in the UI. Best effort: the DB may not exist yet."""
    try:
        from hq.db import repo
        from hq.db.conn import connect, tx
        from hq.db.migrate import migrate
        from hq.db.seed import get_setting, set_settings
        from hq.util.timeutil import now_iso

        conn = connect()
        try:
            migrate(conn)
            with tx(conn):
                if reason:
                    set_settings(conn, {"worker_refusal": {"reason": reason, "at": now_iso()}}, by="worker")
                    repo.emit(conn, "log", f"Worker refused to start: {reason}", level="alert")
                elif get_setting(conn, "worker_refusal"):
                    set_settings(conn, {"worker_refusal": None}, by="worker")
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logging.warning("could not record the refusal state: %s", exc)


def main() -> int:
    settings.load_env()
    settings.ensure_dirs()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from hq.gmail.auth import startup_refusal

    reason = startup_refusal()
    _record_refusal(reason)
    if reason:
        logging.error("refusing to start: %s", reason)
        return REFUSE_EXIT
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    lock_path = settings.RUN_DIR / "worker.lock"
    lock = open(lock_path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logging.error("another worker holds %s; exiting", lock_path)
        return 1

    async def run() -> None:
        # model upkeep: discovery, model servers, Claude availability (HQ_MODEL_UPKEEP=0 turns it off)
        worker = Worker(model_upkeep=os.environ.get("HQ_MODEL_UPKEEP", "1") != "0")
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, worker.stop)
        parentwatch.watch(lambda: loop.call_soon_threadsafe(worker.stop))  # supervisor died → drain and exit
        await worker.run()

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
