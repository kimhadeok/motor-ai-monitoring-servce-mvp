"""회사 정보 및 대시보드 상단 요약. 05_ui_screens.md §3.1."""

import sqlite3
from datetime import datetime, timezone

from app.config import ATTENTION_STATUSES, parse_utc


def get_company(conn, company_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM companies WHERE company_id = ?", (company_id,)
    ).fetchone()


def build_summary(conn, company_id: str, motors: list[dict]) -> dict | None:
    """상단 요약 (§3.1). 대표 상태 집계는 이미 조회한 모터 목록을 재사용한다.

    `motors`는 `app.services.motors.list_company_motors()`의 반환값을 그대로 받는다 —
    대표 상태 판정에 지표별 최신 로그 조회가 필요해 여기서 다시 계산하면 중복 비용이 든다.
    """
    company = get_company(conn, company_id)
    if company is None:
        return None

    started_at = parse_utc(company["created_at"])
    counts = {status: 0 for status in ATTENTION_STATUSES}
    for motor in motors:
        if motor["status"] in counts:
            counts[motor["status"]] += 1

    return {
        "company_name": company["company_name"],
        "motor_count": len(motors),
        "started_at": started_at,
        # 서비스 시작일 당일을 1일째로 세지 않고 경과 일수로 표기한다 (§3.1 "오늘 - created_at").
        "operating_days": (datetime.now(timezone.utc) - started_at).days,
        "status_counts": counts,
        "attention_count": sum(counts.values()),
    }
