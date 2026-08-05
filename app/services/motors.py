"""모터 조회 및 상태 판정. 05_ui_screens.md §3.2 / §4, 03_state_event_logic.md §2 / §4.3.

대표 상태 규칙(03 §2): 4개 지표 상태 중 가장 심각한 단계를 모터 대표 상태로 쓴다.
다만 FAULT는 센서 수치가 내려가도 자동으로 하위 상태가 되지 않는다(03 §4.3) — 담당자가
"정비 완료 확인"을 하기 전까지 FAULT를 유지한다.

조회 함수는 모두 `company_id`를 함께 받아 다른 회사의 모터가 노출되지 않도록 한다.
"""

import sqlite3

from app.config import METRIC_NAMES, STATUS_SEVERITY_RANK

# 지표명 → motor_telemetry의 상태 컬럼
_TELEMETRY_STATUS_COLUMN = {
    "temperature": "temp_status",
    "vibration": "vib_status",
    "current": "current_status",
    "sound": "sound_status",
}

# 정비 완료 확인 시 남기는 로그의 사유 (05 §4.3 확정 문구)
MAINTENANCE_CONFIRM_REASON = "관리자 정비완료 확인"


def _worst(statuses) -> str:
    """심각도가 가장 높은 상태. 값이 없으면 NORMAL."""
    return max(statuses, key=lambda s: STATUS_SEVERITY_RANK.get(s, 0), default="NORMAL")


def get_motor(conn, motor_id: str, company_id: str) -> sqlite3.Row | None:
    """모터 단건. 다른 회사 모터면 None을 반환한다."""
    return conn.execute(
        "SELECT * FROM motors WHERE motor_id = ? AND company_id = ?",
        (motor_id, company_id),
    ).fetchone()


def get_latest_metric_statuses(conn, motor_id: str) -> dict[str, str]:
    """최신 텔레메트리 1행 기준 지표별 상태. 데이터가 없으면 빈 dict."""
    row = conn.execute(
        "SELECT * FROM motor_telemetry WHERE motor_id = ? ORDER BY time DESC LIMIT 1",
        (motor_id,),
    ).fetchone()
    if row is None:
        return {}
    return {metric: row[_TELEMETRY_STATUS_COLUMN[metric]] for metric in METRIC_NAMES}


def find_unconfirmed_fault_metrics(conn, motor_id: str) -> list[str]:
    """최신 로그가 FAULT이면서 아직 정비 완료 확인이 안 된 지표 목록 (03 §4.3, 05 §4.3).

    지표별 최신 로그를 보고 `new_status`가 FAULT이면 미확인으로 본다. 정비 완료 확인은
    같은 지표에 새 로그를 남기므로, 확인이 끝난 지표는 최신 로그가 FAULT가 아니게 된다.
    """
    rows = conn.execute(
        "SELECT metric_name, new_status FROM motor_status_logs l WHERE motor_id = ? "
        "AND created_at = (SELECT MAX(created_at) FROM motor_status_logs "
        "                  WHERE motor_id = l.motor_id AND metric_name = l.metric_name)",
        (motor_id,),
    ).fetchall()
    return sorted(r["metric_name"] for r in rows if r["new_status"] == "FAULT")


def get_representative_status(conn, motor_id: str) -> str:
    """모터 대표 상태 (03 §2). 미확인 FAULT가 있으면 FAULT를 유지한다 (03 §4.3)."""
    if find_unconfirmed_fault_metrics(conn, motor_id):
        return "FAULT"
    return _worst(get_latest_metric_statuses(conn, motor_id).values())


def list_company_motors(conn, company_id: str) -> list[dict]:
    """대시보드 카드용 목록 (05 §3.2) — 모터 정보 + 대표 상태 + 최근 상태 변경 일시."""
    motors = conn.execute(
        "SELECT * FROM motors WHERE company_id = ? ORDER BY motor_id",
        (company_id,),
    ).fetchall()

    cards = []
    for motor in motors:
        last_changed = conn.execute(
            "SELECT MAX(created_at) FROM motor_status_logs WHERE motor_id = ?",
            (motor["motor_id"],),
        ).fetchone()[0]
        cards.append(
            {
                **dict(motor),
                "status": get_representative_status(conn, motor["motor_id"]),
                "last_changed_at": last_changed,
            }
        )
    return cards


def count_status(cards: list[dict], statuses: tuple[str, ...]) -> int:
    """대표 상태가 주어진 목록에 속하는 모터 수 (05 §3.1 '주의 이상 모터 수')."""
    return sum(1 for c in cards if c["status"] in statuses)


def get_thresholds(conn, motor_id: str) -> list[sqlite3.Row]:
    """지표별 임계값 4행 (05 §4.2). METRIC_NAMES 순서로 정렬한다."""
    rows = conn.execute(
        "SELECT * FROM motor_thresholds WHERE motor_id = ?", (motor_id,)
    ).fetchall()
    order = {metric: i for i, metric in enumerate(METRIC_NAMES)}
    return sorted(rows, key=lambda r: order.get(r["metric_name"], len(order)))


def confirm_maintenance(conn, motor_id: str, metric_name: str, contact_id: int) -> None:
    """정비 완료 확인 (05 §4.3).

    담당자를 남긴 신규 로그를 적재해 해당 (모터, 지표)의 자동 상태 판정을 재개시킨다.
    `new_status`를 NORMAL로 두는 것은 "정비가 끝나 정상 판정부터 다시 시작한다"는 뜻이며,
    이후 수집값이 임계를 넘으면 평소대로 전이가 감지된다.
    """
    conn.execute(
        "INSERT INTO motor_status_logs "
        "(motor_id, metric_name, previous_status, new_status, trigger_reason, contact_id) "
        "VALUES (?, ?, 'FAULT', 'NORMAL', ?, ?)",
        (motor_id, metric_name, MAINTENANCE_CONFIRM_REASON, contact_id),
    )
