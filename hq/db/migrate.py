"""Apply numbered SQL migrations from hq/db/migrations (NNNN_name.sql). Idempotent."""
import sqlite3
import sys

from hq import settings
from hq.db.conn import connect
from hq.util.timeutil import now_iso


def migrate(conn: sqlite3.Connection) -> list[int]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for path in sorted(settings.MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        version = int(path.name[:4])
        if version in done:
            continue
        conn.executescript("BEGIN;\n" + path.read_text() + "\nCOMMIT;")
        conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (version, now_iso()))
        applied.append(version)
    return applied


if __name__ == "__main__":
    settings.ensure_dirs()
    print("applied:", migrate(connect(sys.argv[1] if len(sys.argv) > 1 else None)))
