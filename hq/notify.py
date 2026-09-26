"""Notifications (CONTRACT_D §2, §6): a `notifications` row + SSE event (the header bell), and a macOS banner for
warnings and alerts. Delivery runs in the worker after the row is committed: `terminal-notifier` when installed,
otherwise `osascript` — both get the text as argv, never interpolated into a script. `mac_delivered`:
0 pending · 1 shown · 2 not applicable (not macOS / turned off / info) · -1 failed."""
from __future__ import annotations

import asyncio
import logging
import shutil
import sqlite3
import sys

from hq import settings as paths
from hq.db import repo
from hq.db.conn import tx
from hq.db.seed import get_setting
from hq.util.ids import new_id
from hq.util.timeutil import now_iso

log = logging.getLogger(__name__)
SEVERITIES = ("info", "warn", "alert")
MAC_SEVERITIES = ("warn", "alert")


def create(conn: sqlite3.Connection, severity: str, title: str, body: str | None = None, url: str | None = None,
           *, dedupe_open: bool = False) -> str | None:
    """Caller owns the transaction. `dedupe_open` skips a duplicate of an unacknowledged notification."""
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}")
    if dedupe_open and conn.execute("SELECT 1 FROM notifications WHERE title=? AND acknowledged_at IS NULL",
                                    (title,)).fetchone():
        return None
    nid = new_id()
    conn.execute("INSERT INTO notifications(id, severity, title, body, url, created_at) VALUES (?,?,?,?,?,?)",
                 (nid, severity, title, body, url, now_iso()))
    repo.emit(conn, "notification", title, level="alert" if severity == "alert" else "info",
              data={"id": nid, "severity": severity, "title": title, "body": body, "url": url})
    return nid


def mac_command(title: str, body: str | None, url: str | None) -> list[str] | None:
    if sys.platform != "darwin":
        return None
    tn = shutil.which("terminal-notifier")
    if tn:
        argv = [tn, "-title", "Agent HQ", "-subtitle", title[:120], "-message", (body or title)[:240],
                "-group", "agenthq", "-sound", "Glass"]
        if url:
            argv += ["-open", f"http://127.0.0.1:{paths.API_PORT}{url}" if url.startswith("/") else url]
        return argv
    osa = shutil.which("osascript")
    if not osa:
        return None
    script = ('on run argv\ndisplay notification (item 2 of argv) with title "Agent HQ" subtitle (item 1 of argv) '
              'sound name "Glass"\nend run')
    return [osa, "-e", script, title[:120], (body or title)[:240]]


async def deliver_pending(conn: sqlite3.Connection, limit: int = 5) -> int:
    rows = conn.execute("SELECT id, severity, title, body, url FROM notifications WHERE mac_delivered=0 "
                        "ORDER BY created_at LIMIT ?", (limit,)).fetchall()
    if not rows:
        return 0
    enabled = bool(get_setting(conn, "mac_notifications", True))
    shown = 0
    for r in rows:
        argv = mac_command(r["title"], r["body"], r["url"]) if enabled and r["severity"] in MAC_SEVERITIES else None
        state = 2
        if argv:
            try:
                proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.DEVNULL,
                                                            stdout=asyncio.subprocess.DEVNULL,
                                                            stderr=asyncio.subprocess.DEVNULL)
                state = 1 if await asyncio.wait_for(proc.wait(), timeout=10) == 0 else -1
            except (OSError, asyncio.TimeoutError) as exc:
                log.warning("macOS notification failed: %s", exc)
                state = -1
            shown += state == 1
        with tx(conn):
            conn.execute("UPDATE notifications SET mac_delivered=? WHERE id=?", (state, r["id"]))
    return shown
