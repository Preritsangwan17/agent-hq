"""`python -m hq.util.bootstrap`: first-run/upgrade steps used by start.sh — runtime dirs, session secret,
migrations, default settings, an initial agent-registry sync (so the UI shows the team before the worker runs) and a
one-time import of the legacy shortlist."""
from __future__ import annotations

import sys
from pathlib import Path

from hq import settings


def main() -> int:
    from hq.agents.registry import Registry
    from hq.api.auth import ensure_session_secret
    from hq.db.conn import connect, tx
    from hq.db.migrate import migrate, repair_schema
    from hq.db.seed import seed_all

    settings.load_env()
    settings.ensure_dirs()
    ensure_session_secret()
    conn = connect()
    try:
        applied = migrate(conn, repair=False)
        repaired = repair_schema(conn)
        with tx(conn):
            seeded = seed_all(conn)["settings"]
        registry = Registry(settings.AGENTS_DIR, conn)
        changes = registry.scan()
        legacy = import_legacy_once(conn)
    finally:
        conn.close()
    print(summary(applied, seeded, len(registry.configs), legacy, len(repaired)))
    errors = [agent for agent, kind in changes if kind == "error"]
    if errors:
        print(f"! invalid agent file(s): {', '.join(f'{e}.yaml' for e in errors)} — the last good config is kept; "
              "details in the Activity feed", file=sys.stderr)
    return 0


def import_legacy_once(conn, src: Path | None = None) -> int:
    """First run: bring the pre-HQ shortlist (legacy/applications) in as frozen items, with FX from the committed
    seed so start-up never waits on the network. Skipped once any legacy item exists, so later edits (e.g. marking
    which ones were sent) are never overwritten. Returns the number of items imported (0 when skipped)."""
    src = src or settings.ROOT / "legacy" / "applications"
    if not (src / "jobs.json").exists():
        return 0
    if conn.execute("SELECT 1 FROM opportunities WHERE canonical_key LIKE 'legacy:%' LIMIT 1").fetchone():
        return 0
    from hq.importer.legacy import _db_dir, import_legacy
    from hq.pipeline.verify.fx import FxRates

    fx = FxRates(offline=True, cache_path=_db_dir(conn) / "fx" / "rates.json")
    try:
        report = import_legacy(conn, src, fx=fx)
    except Exception as exc:  # never block start-up on the history import
        print(f"! legacy shortlist not imported: {exc}", file=sys.stderr)
        return 0
    return len(report.items)


def summary(applied: list[int], seeded: int, agents: int, legacy: int = 0, repaired: int = 0) -> str:
    """One friendly line for start.sh, e.g. `database ready (data/hq.db, up to date) · 10 agents`."""
    try:
        where = settings.DB_PATH.relative_to(settings.ROOT)
    except ValueError:
        where = settings.DB_PATH
    schema = f"migrated to v{max(applied)}" if applied else "up to date"
    extra = f", {seeded} default settings added" if seeded else ""
    imported = f" · {legacy} legacy applications imported" if legacy else ""
    fixed = f", repaired {repaired} missing table/column/index item(s)" if repaired else ""
    return f"database ready ({where}, {schema}{extra}{fixed}) · {agents} agents{imported}"


if __name__ == "__main__":
    sys.exit(main())
