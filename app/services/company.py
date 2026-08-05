"""회사 정보 및 대시보드 상단 요약. 05_ui_screens.md §3.1."""

import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import ATTENTION_STATUSES, DASHBOARD_RECENT_WINDOW_HOURS, parse_utc
from app.services.events import WORSE, transition_direction


def get_company(conn, company_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM companies WHERE company_id = ?", (company_id,)
    ).fetchone()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def build_summary(conn, company_id: str, motors: list[dict]) -> dict | None:
    """상단 요약 (§3.1). 대표 상태 집계는 이미 조회한 모터 목록을 재사용한다.

    `motors`는 `app.services.motors.list_company_motors()`의 반환값을 그대로 받는다 —
    대표 상태 판정에 지표별 최신 로그 조회가 필요해 여기서 다시 계산하면 중복 비용이 든다.

    담당자가 화면을 열자마자 답을 얻어야 하는 질문에 맞춰 값을 모은다.
    "지금 조치할 게 있나 / 지켜볼 게 있나 / 밤사이 무슨 일이 있었나 / 데이터는 들어오나".
    """
    company = get_company(conn, company_id)
    if company is None:
        return None

    started_at = parse_utc(company["created_at"])
    counts = {status: 0 for status in ATTENTION_STATUSES}
    for motor in motors:
        if motor["status"] in counts:
            counts[motor["status"]] += 1

    window_start = _iso(datetime.now(timezone.utc) - timedelta(hours=DASHBOARD_RECENT_WINDOW_HOURS))
    recent = conn.execute(
        "SELECT l.previous_status, l.new_status FROM motor_status_logs l "
        "JOIN motors m ON m.motor_id = l.motor_id "
        "WHERE m.company_id = ? AND l.created_at >= ?",
        (company_id, window_start),
    ).fetchall()
    worsened = sum(
        1 for r in recent if transition_direction(r["previous_status"], r["new_status"]) == WORSE
    )

    last_collected = conn.execute(
        "SELECT MAX(time) FROM motor_telemetry WHERE company_id = ?", (company_id,)
    ).fetchone()[0]

    return {
        "company_name": company["company_name"],
        "motor_count": len(motors),
        "started_at": started_at,
        # 서비스 시작일 당일을 1일째로 세지 않고 경과 일수로 표기한다 (§3.1 "오늘 - created_at").
        "operating_days": (datetime.now(timezone.utc) - started_at).days,
        "status_counts": counts,
        # 조치가 필요한 설비(위험·고장)와 지켜볼 설비(주의)를 나눈다 — 대응 시급성이 다르다.
        "action_required": counts["DANGER"] + counts["FAULT"],
        "watch_count": counts["WARNING"],
        "normal_count": len(motors) - sum(counts.values()),
        "recent_event_count": len(recent),
        "recent_worsened": worsened,
        "recent_recovered": len(recent) - worsened,
        "last_collected_at": parse_utc(last_collected) if last_collected else None,
    }
