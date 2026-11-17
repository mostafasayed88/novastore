"""SQLite connection management.

Design notes for learners:
* We open a fresh connection per operation via :func:`connect` - simple and
  correct for a demo-scale app; no long-lived connection object to share
  across threads.
* WAL journal mode lets the Streamlit UIs read while the FastAPI backend
  writes, which is exactly our deployment shape (two processes, one file).
* Foreign keys are ON: the DB enforces that orders belong to real customers.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from novastore.db.schema import ALL_TABLES
from novastore.logging_setup import get_logger

logger = get_logger(__name__)


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a configured connection. Caller is responsible for closing it
    (or use :func:`connect_ctx`)."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def connect_ctx(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """``with connect_ctx(...) as conn:`` - commits on success, rolls back
    on error, always closes."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str) -> None:
    """Create all tables if they do not exist yet. Idempotent."""
    with connect_ctx(db_path) as conn:
        for ddl in ALL_TABLES:
            conn.execute(ddl)
    logger.info("Database ready at %s", db_path)


def is_seeded(db_path: Path | str) -> bool:
    """True when the customers table has at least one row."""
    try:
        with connect(db_path) as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM customers").fetchone()
            return bool(row and row["n"] > 0)
    except sqlite3.Error:
        return False
