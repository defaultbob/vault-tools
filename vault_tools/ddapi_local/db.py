"""
db.py — SQLite helpers: WAL mode, _sync_meta table, row counts.

State tracked in _sync_meta:
  last_full   — stop_time of the full extract that was seeded
  last_inc    — stop_time of the last incremental extract successfully applied
                (used as start_time for the next incremental query)
"""

import sqlite3
from pathlib import Path

from .logger import get_logger

log = get_logger()

_SYNC_META_DDL = """
CREATE TABLE IF NOT EXISTS _sync_meta (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    last_full   TEXT,
    last_inc    TEXT,
    db_version  TEXT
);
INSERT OR IGNORE INTO _sync_meta (id, db_version) VALUES (1, '1.0');
"""


def open_db(db_path: Path) -> sqlite3.Connection:
    """Open the SQLite DB with WAL mode enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(_SYNC_META_DDL)
    con.commit()
    return con


def get_last_sync(db_path: Path) -> dict:
    """Return last_full and last_inc stop_times (or None if not yet set)."""
    if not db_path.exists():
        return {"last_full": None, "last_inc": None}
    con = open_db(db_path)
    try:
        row = con.execute("SELECT last_full, last_inc FROM _sync_meta WHERE id=1").fetchone()
        if row:
            return {"last_full": row[0], "last_inc": row[1]}
        return {"last_full": None, "last_inc": None}
    finally:
        con.close()


def record_full_sync(db_path: Path, stop_time: str) -> None:
    """Record a completed full seed. stop_time is the full extract's stop_time from Vault."""
    con = open_db(db_path)
    try:
        con.execute(
            "UPDATE _sync_meta SET last_full=?, last_inc=? WHERE id=1",
            (stop_time, stop_time),
        )
        con.commit()
        log.info("Recorded full sync — last position: %s", stop_time)
    finally:
        con.close()


def record_incremental_sync(db_path: Path, stop_time: str) -> None:
    """Record a completed incremental. stop_time is the incremental's stop_time from Vault."""
    con = open_db(db_path)
    try:
        con.execute("UPDATE _sync_meta SET last_inc=? WHERE id=1", (stop_time,))
        con.commit()
        log.info("Recorded incremental sync — last position: %s", stop_time)
    finally:
        con.close()


def table_counts(db_path: Path) -> dict[str, int]:
    """Return {table_name: row_count} for all non-internal tables."""
    if not db_path.exists():
        return {}
    con = sqlite3.connect(str(db_path))
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\';"
            ).fetchall()
        ]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()
