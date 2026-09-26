"""`python -m hq.api`: serve the API + SPA with uvicorn."""
from __future__ import annotations

import uvicorn

from hq import settings


def main() -> None:
    settings.load_env()
    uvicorn.run("hq.api.app:create_app", factory=True, host=settings.API_HOST, port=settings.API_PORT,
                proxy_headers=False, server_header=False, log_level="info", timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
