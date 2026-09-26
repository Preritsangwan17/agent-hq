"""`python -m hq.worker`: run the orchestrator until SIGTERM/SIGINT. Holds an exclusive lock so only one worker
ever leases tasks for a given run directory."""
from __future__ import annotations

import asyncio
import fcntl
import logging
import signal
import sys

from hq import settings
from hq.util import parentwatch
from hq.worker.orchestrator import Worker


def main() -> int:
    settings.load_env()
    settings.ensure_dirs()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    lock_path = settings.RUN_DIR / "worker.lock"
    lock = open(lock_path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logging.error("another worker holds %s; exiting", lock_path)
        return 1

    async def run() -> None:
        worker = Worker()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, worker.stop)
        parentwatch.watch(lambda: loop.call_soon_threadsafe(worker.stop))  # supervisor died → drain and exit
        await worker.run()

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
