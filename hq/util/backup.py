"""Backups and housekeeping (CONTRACT_E §4): nightly online SQLite backup to data/backups (14 kept), weekly VACUUM,
hourly WAL checkpoint, run-record retention (90 days). `python -m hq.util.backup` makes a backup now."""
from __future__ import annotations

import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

from hq import settings as paths
from hq.db.conn import connect, tx
from hq.db.seed import get_setting, set_settings
from hq.util.timeutil import IST, now_iso, to_iso, today_ist, utcnow

KEEP = 14
BACKUP_AFTER_HOUR_IST = 3


def backup_dir() -> Path:
    d = paths.DATA / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_now(conn: sqlite3.Connection, name: str | None = None) -> Path:
    dest = backup_dir() / (name or f"hq-{today_ist().isoformat()}.db")
    tmp = dest.with_suffix(".tmp")
    target = sqlite3.connect(tmp)
    try:
        conn.backup(target)
    finally:
        target.close()
    tmp.replace(dest)
    dest.chmod(0o600)
    for old in sorted(backup_dir().glob("hq-*.db"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return dest


def housekeeping(conn: sqlite3.Connection) -> list[str]:
    """Hourly from the worker. Returns what it did."""
    did = []
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    with tx(conn):
        n = conn.execute("DELETE FROM agent_runs WHERE started_at < ?", (to_iso(utcnow() - timedelta(days=90)),)).rowcount
    if n:
        did.append(f"pruned {n} run records older than 90 days")
    now_ist = utcnow().astimezone(IST)
    today = today_ist().isoformat()
    if now_ist.hour >= BACKUP_AFTER_HOUR_IST and get_setting(conn, "last_backup_date") != today:
        path = backup_now(conn)
        did.append(f"backup {path.name}")
        if now_ist.weekday() == 6:
            conn.execute("VACUUM")
            did.append("vacuum")
        with tx(conn):
            set_settings(conn, {"last_backup_date": today, "last_backup_at": now_iso()}, by="worker")
    return did


def main() -> int:
    paths.load_env()
    conn = connect()
    path = backup_now(conn, f"hq-{today_ist().isoformat()}-manual.db")
    print(f"backup written: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
