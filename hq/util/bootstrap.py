"""`python -m hq.util.bootstrap`: first-run/upgrade steps used by start.sh — runtime dirs, session secret,
migrations, default settings and an initial agent-registry sync (so the UI shows the team before the worker runs)."""
from __future__ import annotations

import sys

from hq import settings


def main() -> int:
    from hq.agents.registry import Registry
    from hq.api.auth import ensure_session_secret
    from hq.db.conn import connect, tx
    from hq.db.migrate import migrate
    from hq.db.seed import seed_settings

    settings.load_env()
    settings.ensure_dirs()
    ensure_session_secret()
    conn = connect()
    try:
        applied = migrate(conn)
        with tx(conn):
            seeded = seed_settings(conn)
        changes = Registry(settings.AGENTS_DIR, conn).scan()
    finally:
        conn.close()
    errors = [agent for agent, kind in changes if kind == "error"]
    print(f"db={settings.DB_PATH} migrations={applied or 'up to date'} settings_seeded={len(seeded)} "
          f"agent_changes={len(changes)}" + (f" invalid_agent_files={errors}" if errors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
