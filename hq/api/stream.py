"""SSE `/api/stream` (CONTRACT §4): tails the events table every 200 ms, forwards `agent_live` changes as
ephemeral `agent.live` messages (≤ ~4/s per agent), replays after Last-Event-ID (≤ 500) or asks for a resync."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from hq.api import auth
from hq.db import repo, serializers
from hq.db.conn import connect

POLL_S = 0.2
LIVE_MIN_INTERVAL_S = 0.25
REPLAY_MAX = 500
KEEPALIVE_S = 15

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_session)])


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def event_stream(conn: sqlite3.Connection, after: int | None,
                       is_disconnected: Callable[[], Awaitable[bool]], poll_s: float = POLL_S
                       ) -> AsyncIterator[dict[str, Any]]:
    latest = repo.last_event_id(conn)
    cursor = latest
    if after is not None:
        backlog = conn.execute("SELECT COUNT(*) AS n FROM events WHERE id > ?", (after,)).fetchone()["n"]
        if after > latest or backlog > REPLAY_MAX:
            yield {"event": "resync", "data": _dumps({"reason": "gap too large" if backlog > REPLAY_MAX
                                                      else "unknown event id", "last_event_id": latest})}
        else:
            cursor = after
    seqs = {aid: row["seq"] for aid, row in repo.live_rows(conn).items()}
    pending: dict[str, dict[str, Any]] = {}
    last_sent: dict[str, float] = {}
    while True:
        if await is_disconnected():
            return
        rows = conn.execute("SELECT * FROM events WHERE id > ? ORDER BY id LIMIT ?", (cursor, REPLAY_MAX)).fetchall()
        for row in rows:
            cursor = row["id"]
            yield {"event": row["type"], "id": str(row["id"]), "data": _dumps(repo.event_json(row))}
        for aid, row in repo.live_rows(conn).items():
            if seqs.get(aid) != row["seq"]:
                seqs[aid] = row["seq"]
                pending[aid] = row
        now = time.monotonic()
        for aid in list(pending):
            if now - last_sent.get(aid, 0.0) >= LIVE_MIN_INTERVAL_S:
                yield {"event": "agent.live", "data": _dumps(serializers.live_json(pending.pop(aid)))}
                last_sent[aid] = now
        await asyncio.sleep(poll_s)


@router.get("/stream")
async def stream(request: Request, after: int | None = None) -> EventSourceResponse:
    header = request.headers.get("last-event-id")
    start: int | None = after
    if header and header.strip().isdigit():
        start = int(header.strip())

    async def gen() -> AsyncIterator[dict[str, Any]]:
        conn = connect()
        try:
            async for item in event_stream(conn, start, request.is_disconnected):
                yield item
        finally:
            conn.close()

    return EventSourceResponse(gen(), ping=KEEPALIVE_S,
                               headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
