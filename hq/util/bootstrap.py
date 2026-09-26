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
    from hq.db.seed import seed_all

    settings.load_env()
    settings.ensure_dirs()
    ensure_session_secret()
    conn = connect()
    try:
        applied = migrate(conn)
        with tx(conn):
            seeded = seed_all(conn)["settings"]
        registry = Registry(settings.AGENTS_DIR, conn)
        changes = registry.scan()
    finally:
        conn.close()
    print(summary(applied, seeded, len(registry.configs)))
    errors = [agent for agent, kind in changes if kind == "error"]
    if errors:
        print(f"! invalid agent file(s): {', '.join(f'{e}.yaml' for e in errors)} — the last good config is kept; "
              "details in the Activity feed", file=sys.stderr)
    return 0


def summary(applied: list[int], seeded: int, agents: int) -> str:
    """One friendly line for start.sh, e.g. `database ready (data/hq.db, up to date) · 10 agents`."""
    try:
        where = settings.DB_PATH.relative_to(settings.ROOT)
    except ValueError:
        where = settings.DB_PATH
    schema = f"migrated to v{max(applied)}" if applied else "up to date"
    extra = f", {seeded} default settings added" if seeded else ""
    return f"database ready ({where}, {schema}{extra}) · {agents} agents"


if __name__ == "__main__":
    sys.exit(main())
