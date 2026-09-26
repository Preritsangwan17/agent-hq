"""`python -m hq.models.benchmark [--quick|--full] [--model ID] [--task T]` (also `make bench`).

Discovers models, benchmarks each usable one alone, re-assigns roles and prints the leaderboard. Stop the worker
first (`./stop.sh`) so the two don't fight over memory.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from hq import settings as paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hq.models.benchmark")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--quick", action="store_true", help="subsets, ~3 min per model (default)")
    g.add_argument("--full", action="store_true", help="every case, ~15 min per model")
    ap.add_argument("--model", action="append", help="model id (repeatable); default = every usable chat model")
    ap.add_argument("--task", action="append", help="task name (repeatable)")
    args = ap.parse_args(argv)

    from hq.db.conn import connect, tx
    from hq.db.migrate import migrate
    from hq.db.seed import seed_all
    from hq.models import discovery, roles
    from hq.models.benchmark.suite import run_suite
    from hq.models.manager import ModelManager

    paths.load_env()
    paths.ensure_dirs()
    conn = connect()
    migrate(conn)
    with tx(conn):
        seed_all(conn)
    found = discovery.rescan(conn)
    print(f"models: {len(found['all'])} found")
    manager = ModelManager(conn)
    manager.adopt_or_reap()

    async def go() -> dict:
        try:
            return await run_suite(conn, manager, model_ids=args.model, task_names=args.task, quick=not args.full)
        finally:
            await manager.shutdown()

    summary = asyncio.run(go())
    for mid, res in summary.items():
        if isinstance(res, dict) and "error" in res:
            print(f"{mid}: ERROR {res['error']}")
            continue
        cols = "  ".join(f"{t}={r.get('accuracy')}" for t, r in res.items())
        print(f"{mid}: {cols}")
    for r in roles.roles_json(conn):
        top = r["ranked"][0]["model_id"] if r["ranked"] else "—"
        print(f"  {r['label']:<18} {top}{'  (needs Claude sign-off)' if r['needs_claude_signoff'] else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
