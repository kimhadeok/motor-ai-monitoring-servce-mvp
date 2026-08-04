"""SQLite 커넥션 헬퍼."""

import sqlite3
from contextlib import contextmanager

from app.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection_scope():
    """with connection_scope() as conn: ... 형태로 사용, 종료 시 자동 commit/close."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
