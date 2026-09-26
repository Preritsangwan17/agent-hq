"""Apply numbered SQL migrations from hq/db/migrations (NNNN_name.sql), then repair schema drift. Idempotent.

Drift: a database created from an earlier draft of the schema can be marked fully migrated and still lack tables or
columns (seen in the wild as "no such table: claude_usage", which blanked the whole dashboard). So after the
numbered migrations, `repair_schema` compares the database with what the migrations build on an empty database and
adds whatever is missing: tables, columns, indexes. It only ever adds — nothing is dropped or rewritten.
The opposite drift (a migration's column or index already exists) is tolerated statement by statement.
"""
import logging
import sqlite3
import sys

from hq import settings
from hq.db.conn import connect
from hq.util.timeutil import now_iso

log = logging.getLogger(__name__)
TOLERATED = ("duplicate column name", "already exists")


def _files():
    return sorted(settings.MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def _statements(sql: str):
    """Split a migration file into single statements (comments ride along with the statement they follow)."""
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            yield buf.strip()
            buf = ""
    rest = "\n".join(x for x in buf.splitlines() if x.strip() and not x.strip().startswith("--"))
    if rest.strip():
        yield rest.strip()


def _apply(conn: sqlite3.Connection, version: int, sql: str) -> None:
    try:
        conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
        return
    except sqlite3.OperationalError as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        if not any(t in str(exc) for t in TOLERATED):
            raise
        log.warning("migration %04d partly present already (%s); applying the rest one statement at a time",
                    version, exc)
    conn.execute("BEGIN IMMEDIATE")
    try:
        for stmt in _statements(sql):
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as exc:
                if not any(t in str(exc) for t in TOLERATED):
                    raise
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection, *, repair: bool = True) -> list[int]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for path in _files():
        version = int(path.name[:4])
        if version in done:
            continue
        _apply(conn, version, path.read_text(encoding="utf-8"))
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)", (version, now_iso()))
        applied.append(version)
    if repair:
        repair_schema(conn)
    return applied


# ── drift repair ─────────────────────────────────────────────────────────────────────────────────────
def reference_schema() -> sqlite3.Connection:
    """An in-memory database holding exactly what the migrations create."""
    ref = sqlite3.connect(":memory:")
    for path in _files():
        ref.executescript(path.read_text(encoding="utf-8"))
    return ref


def _add_column(conn: sqlite3.Connection, table: str, col: str, typ: str, notnull: int, default: str | None) -> None:
    base = f'ALTER TABLE "{table}" ADD COLUMN "{col}" {typ or ""}'.rstrip()
    if default is not None:
        try:
            conn.execute(f"{base} {'NOT NULL ' if notnull else ''}DEFAULT {default}")
            return
        except sqlite3.OperationalError:  # e.g. a non-constant default: add it plain instead
            pass
    conn.execute(base)  # NOT NULL without a default can't be added to a table with rows; nullable is safe


def repair_schema(conn: sqlite3.Connection) -> list[str]:
    """Add every table, column, index, view or trigger the migrations define but this database lacks.
    Returns what was added (e.g. ["table claude_usage", "column opportunities.parse_json"])."""
    ref = reference_schema()
    added: list[str] = []
    conn.execute("BEGIN IMMEDIATE")  # API and worker may start together: one of them repairs, the other sees it done
    try:
        have = {(r[0], r[1]) for r in conn.execute("SELECT type, name FROM sqlite_master")}
        tables = ref.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                             "ORDER BY rowid").fetchall()
        for name, sql in tables:
            if ("table", name) not in have:
                try:
                    conn.execute(sql)
                    added.append(f"table {name}")
                except sqlite3.DatabaseError as exc:
                    log.error("schema repair: could not create table %s: %s", name, exc)
                continue
            present = {r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')}
            for _cid, col, typ, notnull, default, pk in ref.execute(f'PRAGMA table_info("{name}")'):
                if col in present:
                    continue
                if pk:
                    log.error("schema repair: %s has no primary-key column %s; it needs a manual rebuild", name, col)
                    continue
                try:
                    _add_column(conn, name, col, typ, notnull, default)
                    added.append(f"column {name}.{col}")
                except sqlite3.DatabaseError as exc:
                    log.error("schema repair: could not add %s.%s: %s", name, col, exc)
        for kind in ("index", "view", "trigger"):
            for name, sql in ref.execute("SELECT name, sql FROM sqlite_master WHERE type=? AND sql IS NOT NULL "
                                         "ORDER BY rowid", (kind,)):
                if (kind, name) in have:
                    continue
                try:
                    conn.execute(sql)
                    added.append(f"{kind} {name}")
                except sqlite3.DatabaseError as exc:  # e.g. a UNIQUE index the existing rows violate
                    log.error("schema repair: could not create %s %s: %s", kind, name, exc)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    ref.close()
    if added:
        log.warning("schema repair added %d missing item(s): %s", len(added), ", ".join(added))
    return added


if __name__ == "__main__":
    settings.ensure_dirs()
    c = connect(sys.argv[1] if len(sys.argv) > 1 else None)
    print("applied:", migrate(c, repair=False))
    print("repaired:", repair_schema(c) or "nothing missing")
