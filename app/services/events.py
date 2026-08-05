"""이벤트(상태 전이 로그) 조회. 05_ui_screens.md §3.3 / §4.4.

`motor_status_logs`에는 회사·모터명 컬럼이 없어 `motors` JOIN이 필요하다.
리포트 본문(`report_html` TEXT, `report_pdf` BLOB)은 행당 26KB를 넘으므로 목록 조회에
포함하지 않는다 — 버튼 노출 여부는 `new_status`만으로 판정한다(§3.3 확정).
"""

import sqlite3

from app.config import STATUS_SEVERITY_RANK

# 전이 방향 — 심각도가 올라갔는지 내려갔는지 (03_state_event_logic.md §4.2)
WORSE, RECOVER, FLAT = "worse", "recover", "flat"


def transition_direction(previous_status: str, new_status: str) -> str:
    """상태 전이가 악화인지 회복인지. 알 수 없는 상태값은 변화 없음으로 본다."""
    previous = STATUS_SEVERITY_RANK.get(previous_status)
    new = STATUS_SEVERITY_RANK.get(new_status)
    if previous is None or new is None or previous == new:
        return FLAT
    return WORSE if new > previous else RECOVER


_COLUMNS = (
    "l.log_id, l.motor_id, m.motor_name, l.metric_name, "
    "l.previous_status, l.new_status, l.trigger_reason, l.created_at"
)


def list_company_events(conn, company_id: str, limit: int) -> list[sqlite3.Row]:
    """회사 소속 모터의 상태 전이 이벤트를 최신순으로 조회 (§3.3)."""
    return conn.execute(
        f"SELECT {_COLUMNS} FROM motor_status_logs l "
        "JOIN motors m ON m.motor_id = l.motor_id "
        "WHERE m.company_id = ? "
        "ORDER BY l.created_at DESC LIMIT ?",
        (company_id, limit),
    ).fetchall()


def list_motor_events(conn, motor_id: str, limit: int, offset: int = 0) -> list[sqlite3.Row]:
    """특정 모터의 전체 지표 이벤트를 최신순으로 조회 (§4.4 페이징)."""
    return conn.execute(
        f"SELECT {_COLUMNS} FROM motor_status_logs l "
        "JOIN motors m ON m.motor_id = l.motor_id "
        "WHERE l.motor_id = ? "
        "ORDER BY l.created_at DESC LIMIT ? OFFSET ?",
        (motor_id, limit, offset),
    ).fetchall()


def count_motor_events(conn, motor_id: str) -> int:
    """특정 모터의 전체 이벤트 수 (§4.4 페이지 수 계산용)."""
    return conn.execute(
        "SELECT COUNT(*) FROM motor_status_logs WHERE motor_id = ?", (motor_id,)
    ).fetchone()[0]
