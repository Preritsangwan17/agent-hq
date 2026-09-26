"""`python -m hq.api`: serve the API + SPA with uvicorn."""
from __future__ import annotations

import os
import signal

import uvicorn

from hq import settings
from hq.util import parentwatch


def main() -> None:
    settings.load_env()  # HQ_PORT / HQ_LAN may live in .env rather than the process environment
    host = "0.0.0.0" if os.environ.get("HQ_LAN") == "1" else "127.0.0.1"
    port = int(os.environ.get("HQ_PORT", settings.API_PORT))
    # supervisor died → SIGTERM ourselves so uvicorn shuts down gracefully and frees the port
    parentwatch.watch(lambda: os.kill(os.getpid(), signal.SIGTERM))
    uvicorn.run("hq.api.app:create_app", factory=True, host=host, port=port,
                proxy_headers=False, server_header=False, log_level="info", timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
