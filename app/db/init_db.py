"""SQLite 스키마 초기화. CREATE TABLE IF NOT EXISTS 기반이라 반복 호출해도 안전(idempotent)."""

from pathlib import Path

from app.db.connection import get_connection

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def ensure_schema() -> None:
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
