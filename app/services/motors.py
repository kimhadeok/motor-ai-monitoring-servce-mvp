"""모터 조회 및 상태 판정. 05_ui_screens.md §3.2 / §4, 03_state_event_logic.md §2 / §4.3.

대표 상태 규칙(03 §2): 4개 지표 상태 중 가장 심각한 단계를 모터 대표 상태로 쓴다.
다만 FAULT는 센서 수치가 내려가도 자동으로 하위 상태가 되지 않는다(03 §4.3) — 담당자가
"정비 완료 확인"을 하기 전까지 FAULT를 유지한다.

조회 함수는 모두 `company_id`를 함께 받아 다른 회사의 모터가 노출되지 않도록 한다.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import (
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_THRESHOLDS,
    METRIC_UNITS,
    STATUS_SEVERITY_RANK,
    TREND_BUCKETS,
    TREND_WINDOW_HOURS,
)


def _iso(dt: datetime) -> str:
    """DB 저장 포맷과 동일한 ISO8601 문자열 (schema.sql의 strftime 포맷)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

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


def get_latest_telemetry(conn, motor_id: str) -> sqlite3.Row | None:
    """최신 텔레메트리 1행. (motor_id, time DESC) 인덱스를 탄다."""
    return conn.execute(
        "SELECT * FROM motor_telemetry WHERE motor_id = ? ORDER BY time DESC LIMIT 1",
        (motor_id,),
    ).fetchone()


def get_latest_metric_statuses(conn, motor_id: str) -> dict[str, str]:
    """최신 텔레메트리 1행 기준 지표별 상태. 데이터가 없으면 빈 dict."""
    row = get_latest_telemetry(conn, motor_id)
    if row is None:
        return {}
    return {metric: row[_TELEMETRY_STATUS_COLUMN[metric]] for metric in METRIC_NAMES}


def build_metric_readings(row: sqlite3.Row | None) -> list[dict]:
    """카드·상세용 지표 요약. 심각도가 높은 순으로 정렬해서 돌려준다 (05 §3.2).

    각 항목: metric, label, unit, value, status, ratio(고장 임계 대비 0~1),
    warning_at / danger_at (게이지 눈금 위치 0~1).
    """
    if row is None:
        return []

    readings = []
    for metric in METRIC_NAMES:
        _, warning, danger, fault = METRIC_THRESHOLDS[metric]
        value = row[metric]
        readings.append(
            {
                "metric": metric,
                "label": METRIC_LABELS[metric],
                "unit": METRIC_UNITS[metric],
                "value": value,
                "status": row[_TELEMETRY_STATUS_COLUMN[metric]],
                # 고장 임계를 100%로 본 위치. 임계를 넘어선 값은 100%에서 멈춘다.
                "ratio": min(value / fault, 1.0) if fault else 0.0,
                "warning_at": warning / fault if fault else 0.0,
                "danger_at": danger / fault if fault else 0.0,
                "remaining": fault - value,
            }
        )

    readings.sort(key=lambda r: (STATUS_SEVERITY_RANK.get(r["status"], 0), r["ratio"]), reverse=True)
    return readings


def get_metric_trend(conn, motor_id: str, metric: str, hours: int, buckets: int) -> list[float]:
    """최근 `hours`시간 추이를 `buckets`개 구간 평균으로 다운샘플링한다 (카드 스파크라인용).

    원 데이터는 모터당 수천 행이라 그대로 그리면 낭비다. 구간 평균은 노이즈도 눌러준다.
    """
    if metric not in METRIC_NAMES:  # 컬럼명을 그대로 넣으므로 화이트리스트로 막는다
        return []

    window_start = _iso(datetime.now(timezone.utc) - timedelta(hours=hours))
    bucket_span_days = (hours / 24) / buckets

    rows = conn.execute(
        f"SELECT AVG({metric}) AS v FROM motor_telemetry "
        "WHERE motor_id = ? AND time >= ? "
        "GROUP BY CAST((julianday(time) - julianday(?)) / ? AS INT) "
        "ORDER BY MIN(time)",
        (motor_id, window_start, window_start, bucket_span_days),
    ).fetchall()
    return [r["v"] for r in rows if r["v"] is not None]


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
    """대시보드 카드용 목록 (05 §3.2).

    모터 정보 + 대표 상태 + 최근 상태 변경 일시 + 지표별 최신 수치, 그리고 가장 심각한
    지표의 추이를 담는다. 추이는 카드마다 한 지표만 그리므로 모터당 쿼리 1회로 끝난다.
    카드 순서는 등록 순(motor_id)을 유지한다 — 설비가 늘 같은 자리에 있어야 담당자가
    위치로 기억할 수 있기 때문이다. 위험 여부는 정렬이 아니라 색으로 드러낸다.
    """
    motors = conn.execute(
        "SELECT * FROM motors WHERE company_id = ? ORDER BY motor_id",
        (company_id,),
    ).fetchall()

    cards = []
    for motor in motors:
        motor_id = motor["motor_id"]
        last_changed = conn.execute(
            "SELECT MAX(created_at) FROM motor_status_logs WHERE motor_id = ?",
            (motor_id,),
        ).fetchone()[0]

        readings = build_metric_readings(get_latest_telemetry(conn, motor_id))
        trend: list[float] = []
        if readings:
            trend = get_metric_trend(
                conn, motor_id, readings[0]["metric"], TREND_WINDOW_HOURS, TREND_BUCKETS
            )

        # 대표 상태 판정에 이미 쓰이는 값이라 카드에도 함께 실어 보낸다 —
        # 대시보드에서 정비 완료 확인 버튼을 띄우려면 어떤 지표가 FAULT인지 알아야 한다.
        fault_metrics = find_unconfirmed_fault_metrics(conn, motor_id)
        status = "FAULT" if fault_metrics else _worst(
            r["status"] for r in readings
        )

        cards.append(
            {
                **dict(motor),
                "status": status,
                "fault_metrics": fault_metrics,
                "last_changed_at": last_changed,
                "readings": readings,
                "trend": trend,
            }
        )
    return cards


def count_status(cards: list[dict], statuses: tuple[str, ...]) -> int:
    """대표 상태가 주어진 목록에 속하는 모터 수 (05 §3.1 '주의 이상 모터 수')."""
    return sum(1 for c in cards if c["status"] in statuses)


def list_company_motor_status(conn, company_id: str) -> list[dict]:
    """모터 현황·그래프 페이지용 경량 목록 (재정리안 2페이지).

    `list_company_motors`보다 가볍다 — 카드 스파크라인용 추이(GROUP BY)와 게이지용
    readings 가공을 생략하고, 카드에 필요한 최신값·대표상태·마지막 상태변경만 담는다.

    조회 전략(실측 근거): 최신 텔레메트리를 윈도우 함수로 한 번에 뽑으면 회사 텔레메트리
    전체(수십만 행)를 스캔해 오히려 느리다(200대 기준 ~294ms). `idx_motor_telemetry_motor_time`를
    타는 모터별 `ORDER BY time DESC LIMIT 1` 점조회 200회가 훨씬 싸다(~30ms). 반면
    motor_status_logs는 작은 테이블이라 미확인 FAULT·마지막 상태변경은 배치 쿼리로 묶는다.

    각 dict: motor_id, motor_name, installation_location, model_name, status(대표),
    values(metric→최신값), statuses(metric→상태), fault_metrics, last_changed_at.
    """
    motors = conn.execute(
        "SELECT motor_id, motor_name, installation_location, model_name "
        "FROM motors WHERE company_id = ? ORDER BY motor_id",
        (company_id,),
    ).fetchall()
    if not motors:
        return []

    # 마지막 상태변경 (motor_status_logs는 작아 배치 GROUP BY가 저렴하다)
    changed_rows = conn.execute(
        "SELECT motor_id, MAX(created_at) AS mc FROM motor_status_logs "
        "WHERE motor_id IN (SELECT motor_id FROM motors WHERE company_id = ?) "
        "GROUP BY motor_id",
        (company_id,),
    ).fetchall()
    last_changed = {r["motor_id"]: r["mc"] for r in changed_rows}

    # 지표별 최신 로그가 FAULT인 (모터, 지표) — 미확인 FAULT (03 §4.3).
    # 로그 테이블이 작아 윈도우 함수로 한 번에 뽑아도 싸다.
    fault_rows = conn.execute(
        "SELECT motor_id, metric_name FROM ("
        "  SELECT l.motor_id, l.metric_name, l.new_status, ROW_NUMBER() OVER ("
        "    PARTITION BY l.motor_id, l.metric_name ORDER BY l.created_at DESC) rn"
        "  FROM motor_status_logs l JOIN motors m ON m.motor_id = l.motor_id"
        "  WHERE m.company_id = ?"
        ") WHERE rn = 1 AND new_status = 'FAULT'",
        (company_id,),
    ).fetchall()
    fault_metrics: dict[str, list[str]] = {}
    for r in fault_rows:
        fault_metrics.setdefault(r["motor_id"], []).append(r["metric_name"])

    result = []
    for motor in motors:
        motor_id = motor["motor_id"]
        # 최신 텔레메트리는 인덱스를 타는 모터별 점조회로 (윈도우 함수 전체 스캔 회피)
        row = get_latest_telemetry(conn, motor_id)
        values: dict[str, float] = {}
        statuses: dict[str, str] = {}
        if row is not None:
            for metric in METRIC_NAMES:
                values[metric] = row[metric]
                statuses[metric] = row[_TELEMETRY_STATUS_COLUMN[metric]]

        motor_faults = sorted(fault_metrics.get(motor_id, []))
        status = "FAULT" if motor_faults else _worst(statuses.values())

        result.append(
            {
                **dict(motor),
                "status": status,
                "values": values,
                "statuses": statuses,
                "fault_metrics": motor_faults,
                "last_changed_at": last_changed.get(motor_id),
            }
        )
    return result


def get_motor_metric_series(
    conn, motor_id: str, hours: int, buckets: int
) -> tuple[list[str], dict[str, list[float]]]:
    """모터 하나의 4개 지표 추이를 한 번의 쿼리로 구간 평균 다운샘플한다 (그래프 페이지용).

    `get_metric_trend`를 지표마다 부르면 페이지당 쿼리 수가 4배가 된다. 여기서는 4개
    지표 평균을 한 쿼리로 모아 페이지당 쿼리를 모터 수만큼으로 줄인다.

    반환: (버킷 시각 목록, {지표: 값 목록}). 시각은 각 버킷의 MIN(time)(ISO8601 UTC 문자열)로,
    그래프 X축을 실제 시간으로 그리는 데 쓴다. 한 버킷에는 4개 지표가 모두 있으므로 시각과
    값 목록의 길이·순서가 일치한다.
    """
    window_start = _iso(datetime.now(timezone.utc) - timedelta(hours=hours))
    bucket_span_days = (hours / 24) / buckets

    rows = conn.execute(
        "SELECT MIN(time) AS bucket_time, AVG(temperature) AS temperature, "
        "AVG(vibration) AS vibration, AVG(current) AS current, AVG(sound) AS sound "
        "FROM motor_telemetry WHERE motor_id = ? AND time >= ? "
        "GROUP BY CAST((julianday(time) - julianday(?)) / ? AS INT) "
        "ORDER BY MIN(time)",
        (motor_id, window_start, window_start, bucket_span_days),
    ).fetchall()

    times = [r["bucket_time"] for r in rows]
    series = {metric: [r[metric] for r in rows] for metric in METRIC_NAMES}
    return times, series


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
