"""이벤트(상태 전이 로그) 조회. 05_ui_screens.md §3.3 / §4.4.

`motor_status_logs`에는 회사·모터명 컬럼이 없어 `motors` JOIN이 필요하다.
리포트 본문(`report_html` TEXT, `report_pdf` BLOB)은 행당 26KB를 넘으므로 목록 조회에
포함하지 않는다 — 버튼 노출 여부는 `new_status`만으로 판정한다(§3.3 확정).
"""

import sqlite3

from app.config import METRIC_NAMES, STATUS_SEVERITY_RANK

# 전이 방향 — 심각도가 올라갔는지 내려갔는지 (03_state_event_logic.md §4.2)
WORSE, RECOVER, FLAT = "worse", "recover", "flat"


def transition_direction(previous_status: str, new_status: str) -> str:
    """상태 전이가 악화인지 회복인지. 알 수 없는 상태값은 변화 없음으로 본다."""
    previous = STATUS_SEVERITY_RANK.get(previous_status)
    new = STATUS_SEVERITY_RANK.get(new_status)
    if previous is None or new is None or previous == new:
        return FLAT
    return WORSE if new > previous else RECOVER


# 지표별 텔레메트리 컬럼을 행마다 골라 쓴다. metric_name이 행마다 다르므로 CASE로 편다.
# connectivity 이벤트(03 §4.4)는 대응하는 계측 컬럼이 없어 NULL이 되며, 화면에서 "-"로 나온다.
def _metric_value(alias: str) -> str:
    branches = " ".join(
        f"WHEN '{metric}' THEN {alias}.{metric}" for metric in METRIC_NAMES
    )
    return f"CASE l.metric_name {branches} END"


# 상태 전이는 "어느 상태에서 어디로"만 말하고 "얼마였다가 얼마가 됐는지"는 말하지 않는다.
# 담당자가 심각도를 가늠하려면 수치가 필요하므로(임계를 아슬하게 넘었는지, 크게 뛰었는지)
# 이벤트 시점 값과 직전 수집 값을 함께 싣는다.
_COLUMNS = (
    "l.log_id, l.motor_id, m.motor_name, l.metric_name, "
    "l.previous_status, l.new_status, l.trigger_reason, l.created_at, "
    f"({_metric_value('t')}) AS metric_value, "
    f"(SELECT {_metric_value('p')} FROM motor_telemetry p "
    " WHERE p.motor_id = l.motor_id AND p.time < l.created_at "
    " ORDER BY p.time DESC LIMIT 1) AS previous_value"
)

# 이벤트 시점 계측 행. 상태 로그와 같은 시각의 행이 있으면 붙고, 없으면 값이 NULL이 된다.
_TELEMETRY_JOIN = (
    "LEFT JOIN motor_telemetry t ON t.motor_id = l.motor_id AND t.time = l.created_at"
)


def list_company_events(
    conn, company_id: str, limit: int, statuses: tuple[str, ...] | None = None
) -> list[sqlite3.Row]:
    """회사 소속 모터의 상태 전이 이벤트를 최신순으로 조회 (§3.3).

    `statuses`를 주면 전이 결과(`new_status`)가 그 목록에 든 건만 남긴다. 화면에서 자르지
    않고 여기서 거르는 이유: `LIMIT`이 필터보다 먼저 걸리면 최근 10건이 전부 관찰 단계
    전이일 때 조치가 필요한 건이 한 건도 안 보인다.
    """
    where = ["m.company_id = ?"]
    params: list = [company_id]
    if statuses:
        where.append(f"l.new_status IN ({','.join('?' for _ in statuses)})")
        params.extend(statuses)
    params.append(limit)

    return conn.execute(
        f"SELECT {_COLUMNS} FROM motor_status_logs l "
        "JOIN motors m ON m.motor_id = l.motor_id "
        f"{_TELEMETRY_JOIN} "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY l.created_at DESC LIMIT ?",
        params,
    ).fetchall()


def _motor_event_filter(motor_id: str, statuses: tuple[str, ...] | None) -> tuple[str, list]:
    """`list_motor_events` / `count_motor_events`가 공유하는 WHERE 절.

    두 함수가 같은 조건을 봐야 페이지 수와 실제 행 수가 어긋나지 않는다.
    """
    where = ["l.motor_id = ?"]
    params: list = [motor_id]
    if statuses:
        where.append(f"l.new_status IN ({','.join('?' for _ in statuses)})")
        params.extend(statuses)
    return " AND ".join(where), params


def list_motor_events(
    conn,
    motor_id: str,
    limit: int,
    offset: int = 0,
    statuses: tuple[str, ...] | None = None,
) -> list[sqlite3.Row]:
    """특정 모터의 지표 이벤트를 최신순으로 조회 (§4.4 페이징).

    `statuses`는 `list_company_events`와 같은 의미다 — 전이 결과(`new_status`)가 그 목록에
    든 건만 남긴다. 상세 페이지도 대시보드와 같은 목록 규칙을 쓰기 위해 붙였다(05 §4.4).
    """
    clause, params = _motor_event_filter(motor_id, statuses)
    return conn.execute(
        f"SELECT {_COLUMNS} FROM motor_status_logs l "
        "JOIN motors m ON m.motor_id = l.motor_id "
        f"{_TELEMETRY_JOIN} "
        f"WHERE {clause} "
        "ORDER BY l.created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()


def count_motor_events(
    conn, motor_id: str, statuses: tuple[str, ...] | None = None
) -> int:
    """특정 모터의 이벤트 수 (§4.4 페이지 수 계산용). 필터는 목록 조회와 같아야 한다."""
    clause, params = _motor_event_filter(motor_id, statuses)
    return conn.execute(
        f"SELECT COUNT(*) FROM motor_status_logs l WHERE {clause}", params
    ).fetchone()[0]
