"""SQLite 스키마 초기화. CREATE TABLE IF NOT EXISTS 기반이라 반복 호출해도 안전(idempotent)."""

from pathlib import Path

from app.db.connection import get_connection

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# 스키마에 나중에 더해진 컬럼 — `{테이블: {컬럼: 선언}}` (2026-08-13 추가).
# `CREATE TABLE IF NOT EXISTS`는 **이미 있는 테이블을 건드리지 않는다.** 그래서 schema.sql에
# 컬럼을 더해도 기존 DB 파일에는 반영되지 않고, 그 컬럼을 읽는 쿼리가 `no such column`으로
# 죽는다. 데모 DB는 낡으면(`DEMO_DATA_MAX_AGE_HOURS`) 통째로 다시 만들어지지만
# (`services/bootstrap.py`), 그 창 안에 만들어진 DB는 살아남아 옛 스키마 그대로 조회된다.
_ADDED_COLUMNS = {
    "motors": {
        "lifespan_hours": "INTEGER",
        "operation_started_at": "TEXT",
    },
}


def _add_missing_columns(conn) -> None:
    """`_ADDED_COLUMNS`에 적힌 컬럼 중 아직 없는 것만 덧붙인다.

    값은 채우지 않는다 — 기존 행은 NULL로 남고, 시드가 다시 돌 때 채워진다. NOT NULL이나
    UNIQUE를 붙이지 않는 이유도 같다. SQLite의 `ALTER TABLE ADD COLUMN`은 기존 행에 넣을
    값을 요구하므로 제약이 붙은 컬럼은 덧붙일 수 없다.
    """
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # 테이블 자체가 없으면 schema.sql이 방금 만들었을 것이다
        for column, declaration in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def ensure_schema() -> None:
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        _add_missing_columns(conn)
        conn.commit()
    finally:
        conn.close()
