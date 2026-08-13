"""모터 조회 및 상태 판정. 05_ui_screens.md §3.2 / §4, 03_state_event_logic.md §2 / §4.3.

대표 상태 규칙(03 §2): 4개 지표 상태 중 가장 심각한 단계를 모터 대표 상태로 쓴다.
다만 FAULT는 센서 수치가 내려가도 자동으로 하위 상태가 되지 않는다(03 §4.3) — 담당자가
"정비 완료 확인"을 하기 전까지 FAULT를 유지한다.

조회 함수는 모두 `company_id`를 함께 받아 다른 회사의 모터가 노출되지 않도록 한다.
"""

import math
import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import (
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_THRESHOLDS,
    METRIC_UNITS,
    MOTOR_DAILY_OPERATING_HOURS,
    MOTOR_LIFE_DAYS_PER_MONTH,
    MOTOR_LIFE_DAYS_PER_YEAR,
    STATUS_SEVERITY_RANK,
    TREND_WINDOW_HOURS,
    parse_utc,
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


# 지표별 임계 4구간 (normal, warning, danger, fault)
ThresholdMap = dict[str, tuple[float, float, float, float]]


def default_thresholds() -> ThresholdMap:
    """`config.METRIC_THRESHOLDS` 기본값 사본. 모터별 행이 없을 때 쓴다."""
    return {metric: tuple(METRIC_THRESHOLDS[metric]) for metric in METRIC_NAMES}


def _rows_to_threshold_map(rows) -> ThresholdMap:
    """`motor_thresholds` 행 → 지표별 4구간. 빠진 지표는 기본값으로 채운다.

    한 지표라도 비어 있으면 그 지표의 판정이 성립하지 않으므로, 부분 결손은 조용히
    기본값으로 메운다 — 화면이 비는 것보다 낫다.
    """
    result = default_thresholds()
    for row in rows:
        metric = row["metric_name"]
        if metric not in result:
            continue
        values = (
            row["normal_range"],
            row["warning_range"],
            row["danger_range"],
            row["fault_range"],
        )
        if all(v is not None for v in values):
            result[metric] = values
    return result


def get_metric_thresholds(conn, motor_id: str) -> ThresholdMap:
    """모터 1대의 지표별 임계값 (04 §3.4).

    **판정·표시가 모두 이 값을 봐야 한다** (2026-08-11). 종전에는 `motor_thresholds`를
    모터 상세의 임계값 표와 리포트 참고표만 읽고, 상태 판정·게이지·차트 임계선·진단
    근거는 `config.METRIC_THRESHOLDS` 전역값을 썼다. 그래서 관리자 페이지에서 임계값을
    바꾸면 **같은 리포트 한 장 안에 "정상 기준 ≤ 60"과 "정상 구간 < 50"이 함께 찍혔다**
    (실측). 설비마다 정상 범위가 다른 것이 예지보전의 전제이므로 전역값은 기본값일 뿐이다.
    """
    rows = conn.execute(
        "SELECT * FROM motor_thresholds WHERE motor_id = ?", (motor_id,)
    ).fetchall()
    return _rows_to_threshold_map(rows)


def list_company_metric_thresholds(conn, company_id: str) -> dict[str, ThresholdMap]:
    """회사 소속 모터 전체의 임계값을 **한 번에** 조회한다.

    대시보드는 카드 200장을 그리므로 모터당 조회를 돌리면 200회가 된다.
    `motor_thresholds`는 모터당 4행짜리 작은 테이블이라 배치가 훨씬 싸다.
    """
    rows = conn.execute(
        "SELECT t.* FROM motor_thresholds t JOIN motors m ON m.motor_id = t.motor_id "
        "WHERE m.company_id = ?",
        (company_id,),
    ).fetchall()
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row["motor_id"], []).append(row)
    return {motor_id: _rows_to_threshold_map(rs) for motor_id, rs in grouped.items()}


def build_metric_readings(
    row: sqlite3.Row | None, thresholds: ThresholdMap | None = None
) -> list[dict]:
    """카드·상세용 지표 요약. 심각도가 높은 순으로 정렬해서 돌려준다 (05 §3.2).

    각 항목: metric, label, unit, value, status, ratio(고장 임계 대비 0~1),
    warning_at / danger_at (게이지 눈금 위치 0~1).

    `thresholds`는 해당 모터의 임계값이다(`get_metric_thresholds`). 생략하면 기본값을
    쓰지만, 화면 경로에서는 **반드시 모터별 값을 넘겨야** 게이지 눈금이 관리자에서 설정한
    기준과 맞는다.

    **`status`는 저장된 판정 결과를 그대로 쓴다** (2026-08-11 확정). 임계값을 바꿔도 이미
    수집된 행의 판정은 바뀌지 않고 **다음 수집부터** 새 기준이 적용된다 — 판정은 수집
    시점에 한 번이라는 원칙을 과거·현재에 똑같이 적용하기 위해서다. 반면 눈금·비율은
    "지금 기준이 무엇인가"를 보여주는 것이라 즉시 새 값을 따른다.
    """
    if row is None:
        return []

    thresholds = thresholds or default_thresholds()
    readings = []
    for metric in METRIC_NAMES:
        _, warning, danger, fault = thresholds[metric]
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


def get_metric_trend_raw(conn, motor_id: str, metric: str, hours: int) -> list[float]:
    """최근 `hours`시간의 지표 값을 **다운샘플 없이** 시간순으로 (카드 스파크라인용).

    카드도 원본으로 바꿨다 (2026-08-12 사용자 요청). 그래프 두 화면이 원본 표시로 간 뒤
    카드만 15분 구간 평균으로 남아, 같은 지표를 화면마다 다른 밀도로 그리고 있었다.

    스파크라인은 132×28px이라 점이 픽셀보다 많아지지만, `_sparkline_svg()`가 폭을 점 수로
    나눠 그리므로 길이에 무관하게 동작한다(`pathLength="1"`이라 그리기 애니메이션도 그대로).
    """
    if metric not in METRIC_NAMES:  # 컬럼명을 그대로 넣으므로 화이트리스트로 막는다
        return []

    window_start = _iso(datetime.now(timezone.utc) - timedelta(hours=hours))
    rows = conn.execute(
        f"SELECT {metric} AS v FROM motor_telemetry "
        "WHERE motor_id = ? AND time >= ? ORDER BY time",
        (motor_id, window_start),
    ).fetchall()
    return [r["v"] for r in rows if r["v"] is not None]


def get_metric_trend(conn, motor_id: str, metric: str, hours: int, buckets: int) -> list[float]:
    """최근 `hours`시간 추이를 `buckets`개 구간 평균으로 다운샘플링한다.

    **현재 호출부가 없다 (2026-08-12).** 카드 스파크라인이 원본 표시로 바뀌었다
    (`get_metric_trend_raw`). 원본이 무거우면 되돌릴 수 있게 `TREND_BUCKETS`와 함께 남겨 둔다.

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


def get_metric_status_view(conn, motor_id: str) -> tuple[dict[str, str], list[str], str]:
    """상세 화면용 (지표별 상태, 미확인 FAULT 지표, 대표 상태) (05 §4, 2026-08-11).

    상세 헤더가 "FAULT (온도, 소음) DANGER (진동)"처럼 **어느 지표가 어느 상태인지** 밝히려면
    지표별 상태가 필요하다. 대표 상태 하나만으로는 담당자가 무엇을 봐야 할지 알 수 없다.

    지표별 상태는 최신 텔레메트리 기준이되, **미확인 FAULT는 수치가 내려가도 FAULT를
    유지한다**(03 §4.3) — 담당자가 정비 완료를 확인하기 전까지는 고장으로 본다.

    세 값을 함께 돌려주는 이유는 조회를 한 번만 하기 위해서다. 종전 상세 페이지는
    `get_representative_status()`와 `find_unconfirmed_fault_metrics()`를 따로 불러
    같은 쿼리를 두 번씩 돌렸다(자동 갱신으로 10초마다 반복되는 경로다).
    """
    fault_metrics = find_unconfirmed_fault_metrics(conn, motor_id)
    statuses = get_latest_metric_statuses(conn, motor_id)
    for metric in fault_metrics:
        statuses[metric] = "FAULT"
    return statuses, fault_metrics, _worst(statuses.values())


def thresholds_differ_from_default(thresholds: ThresholdMap) -> bool:
    """이 모터의 임계값이 회사 기본값과 다른가 (05 §3-A 캡션용)."""
    return thresholds != default_thresholds()


def get_representative_status(conn, motor_id: str) -> str:
    """모터 대표 상태 (03 §2). 미확인 FAULT가 있으면 FAULT를 유지한다 (03 §4.3)."""
    if find_unconfirmed_fault_metrics(conn, motor_id):
        return "FAULT"
    return _worst(get_latest_metric_statuses(conn, motor_id).values())


def list_unconfirmed_fault_metrics(conn, company_id: str) -> dict[str, list[str]]:
    """회사 전체의 미확인 FAULT 지표를 **한 번에** 조회한다 (03 §4.3).

    `find_unconfirmed_fault_metrics()`를 모터마다 부르면 200대에 200회가 되는데,
    `motor_status_logs`는 작은 테이블이라 윈도우 함수로 묶는 편이 훨씬 싸다.
    `list_company_motor_status()`가 이미 쓰던 전략과 같다.
    """
    rows = conn.execute(
        "SELECT motor_id, metric_name FROM ("
        "  SELECT l.motor_id, l.metric_name, l.new_status, ROW_NUMBER() OVER ("
        "    PARTITION BY l.motor_id, l.metric_name ORDER BY l.created_at DESC) rn"
        "  FROM motor_status_logs l JOIN motors m ON m.motor_id = l.motor_id"
        "  WHERE m.company_id = ?"
        ") WHERE rn = 1 AND new_status = 'FAULT'",
        (company_id,),
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["motor_id"], []).append(row["metric_name"])
    return {motor_id: sorted(metrics) for motor_id, metrics in result.items()}


def list_company_motors(conn, company_id: str) -> list[dict]:
    """대시보드 카드용 목록 (05 §3.2).

    모터 정보 + 대표 상태 + 지표별 최신 수치를 담는다. 카드 순서는 등록 순(motor_id)을
    유지한다 — 설비가 늘 같은 자리에 있어야 담당자가 위치로 기억할 수 있기 때문이다.
    위험 여부는 정렬이 아니라 색으로 드러낸다.

    **추이(스파크라인)는 여기서 채우지 않는다** (2026-08-11). 전체 목록은 상단 요약·배너
    집계에 필요해 전건을 조회하지만, 카드는 심각한 순 `DASHBOARD_MOTOR_CARD_LIMIT`대만
    그린다(05 §3.2). 그리지도 않을 180대분의 GROUP BY를 돌리던 것이 종전 구조에서 가장
    비싼 부분이었다 — 선정이 끝난 뒤 `attach_card_trends()`로 표시할 카드에만 채운다.

    **`last_changed_at`도 담지 않는다** (2026-08-11). 카드 하단 줄을 없애면서 대시보드가
    이 값을 쓰지 않게 됐다(05 §3.2). 모터 현황 카드(§3-B)는 여전히 쓰므로
    `list_company_motor_status()`에는 그대로 남아 있다.

    최신 텔레메트리를 윈도우 함수로 묶지 않는 이유는 `list_company_motor_status()`의
    docstring에 적힌 실측 근거와 같다 — 인덱스 점조회가 전체 스캔보다 싸다.
    """
    motors = conn.execute(
        "SELECT * FROM motors WHERE company_id = ? ORDER BY motor_id",
        (company_id,),
    ).fetchall()
    if not motors:
        return []

    # 대표 상태 판정에 이미 쓰이는 값이라 카드에도 함께 실어 보낸다 —
    # 대시보드에서 정비 완료 확인 버튼을 띄우려면 어떤 지표가 FAULT인지 알아야 한다.
    fault_metrics_by_motor = list_unconfirmed_fault_metrics(conn, company_id)
    # 게이지 눈금은 모터별 임계값을 따른다 (2026-08-11). 배치 1회로 가져온다.
    thresholds_by_motor = list_company_metric_thresholds(conn, company_id)

    cards = []
    for motor in motors:
        motor_id = motor["motor_id"]
        readings = build_metric_readings(
            get_latest_telemetry(conn, motor_id), thresholds_by_motor.get(motor_id)
        )
        fault_metrics = fault_metrics_by_motor.get(motor_id, [])
        status = "FAULT" if fault_metrics else _worst(r["status"] for r in readings)

        cards.append(
            {
                **dict(motor),
                "status": status,
                "fault_metrics": fault_metrics,
                "readings": readings,
                # 키는 항상 둔다 — 카드 렌더가 존재를 전제하므로 채워지기 전에도 비어 있어야 한다.
                "trend": [],
            }
        )
    return cards


def attach_card_trends(conn, cards: list[dict]) -> list[dict]:
    """표시할 카드에만 스파크라인 추이를 채운다 (05 §3.2, 2026-08-11).

    `select_priority_cards()`로 그릴 카드를 고른 **뒤에** 부른다. 카드는 가장 심각한
    지표 하나만 그리므로 카드당 쿼리 1회다. 전달된 dict를 그대로 수정한다 —
    호출측의 전체 목록과 같은 객체라 집계·배너가 이미 참조하고 있다.
    """
    for card in cards:
        readings = card.get("readings") or []
        if readings:
            card["trend"] = get_metric_trend_raw(
                conn, card["motor_id"], readings[0]["metric"], TREND_WINDOW_HOURS
            )
    return cards


def select_priority_cards(cards: list[dict], limit: int | None) -> list[dict]:
    """대시보드에 그릴 카드를 심각한 순으로 `limit`개 고른다. `limit`이 None이면 전부.

    `list_company_motors()`는 등록 순(motor_id)을 유지하지만, 여기서 앞에서부터 그냥
    자르면 흩어져 있는 위험 모터가 화면에서 사라진다 — COMP-001은 200대 중 조치 필요가
    17대이고 motor_id 순으로는 앞 10개 안에 거의 들어오지 않는다. 문제를 발견하라고 있는
    화면이 문제를 가리게 되므로, 제한할 때는 심각도 순으로 고른다.

    같은 상태끼리는 등록 순을 유지한다(안정 정렬) — 설비가 늘 같은 자리에 있어야
    담당자가 위치로 기억할 수 있다는 `list_company_motors()`의 의도를 그 안에서 지킨다.
    """
    if limit is None or len(cards) <= limit:
        return cards
    ordered = sorted(cards, key=lambda c: -STATUS_SEVERITY_RANK.get(c["status"], 0))
    return ordered[:limit]


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


def get_motor_metric_raw_series(
    conn, motor_id: str, hours: int
) -> tuple[list[str], dict[str, list[float]]]:
    """모터 하나의 4개 지표 추이를 **다운샘플 없이** 수집된 그대로 (모터 상세 §4.1-A).

    반환 형식은 `get_motor_metric_series`와 같아 차트 코드가 그대로 받는다.

    **왜 상세만 원본인가 (2026-08-12).** 구간 평균은 스파이크를 지운다 — 실측: 137호기의
    한 15분 구간에서 온도 원본 최대 38.27이 평균 33.14로(−13%), 소음 108.96이 105.33으로
    깎였다. 전체 19,920개 구간 중 18개(0.1%)는 평균과 원본 최대의 **상태 구간 자체가**
    달랐다(예: 평균 74.49 경고 / 원본 75.12 위험). 상태 판정은 원본 최신값을 쓰는데
    (`get_latest_metric_statuses`) 그래프만 평균이면 두 화면의 근거가 어긋난다.

    **그래프 페이지(§3-A)도 같은 이유로 원본으로 바꿨다** (2026-08-12 사용자 요청).
    실측: 20대 표시 시 선분 52,712개(모터·지표당 최대 2,026점), 쿼리 15ms, 차트 80개 spec
    1,195ms, 전송 JSON 4.1MB, 브라우저 렌더 1,343ms. 모터마다 수집 주기가 달라(10~60초)
    대수에 정비례하지는 않는다.
    """
    window_start = _iso(datetime.now(timezone.utc) - timedelta(hours=hours))
    rows = conn.execute(
        "SELECT time, temperature, vibration, current, sound FROM motor_telemetry "
        "WHERE motor_id = ? AND time >= ? ORDER BY time",
        (motor_id, window_start),
    ).fetchall()

    times = [r["time"] for r in rows]
    series = {metric: [r[metric] for r in rows] for metric in METRIC_NAMES}
    return times, series


def get_motor_metric_series(
    conn, motor_id: str, hours: int, buckets: int
) -> tuple[list[str], dict[str, list[float]]]:
    """모터 하나의 4개 지표 추이를 한 번의 쿼리로 구간 평균 다운샘플한다.

    **현재 호출부가 없다 (2026-08-12).** 두 그래프 화면 모두 원본 표시로 바꿨다
    (`get_motor_metric_raw_series`). 원본이 무거우면 되돌릴 수 있게 남겨 둔 것이며,
    되돌릴 때는 `GRAPH_TREND_BUCKETS`와 `show_points`도 함께 되돌린다.

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


# --- 모터 수명 (05 §4.1, 2026-08-13) ---------------------------------------


def _split_duration(hours: float) -> tuple[int, int, int, int]:
    """시간 수를 (년, 개월, 일, 시간)으로 쪼갠다.

    달력이 아니라 **표기용 근사**다(`MOTOR_LIFE_DAYS_PER_YEAR` / `..._PER_MONTH`).
    남은 수명은 미래 구간이라 실제 달의 길이를 알 수 없고, 화면도 근사임을 밝힌다.
    """
    total = int(hours)
    per_day = 24
    per_month = MOTOR_LIFE_DAYS_PER_MONTH * per_day
    per_year = MOTOR_LIFE_DAYS_PER_YEAR * per_day

    years, total = divmod(total, per_year)
    months, total = divmod(total, per_month)
    days, hours_left = divmod(total, per_day)
    return years, months, days, hours_left


def format_life_duration(hours: float) -> str:
    """`3년 2개월 14일 5시간` 형태. 0인 단위는 앞에서부터 생략한다.

    앞자리 0을 그대로 적으면(`0년 0개월 3일 5시간`) 눈이 의미 없는 0을 먼저 읽는다.
    다만 중간의 0은 남긴다 — `2년 0개월 3일`을 `2년 3일`로 줄이면 자릿수가 흐려진다.
    """
    parts = list(zip(_split_duration(hours), ("년", "개월", "일", "시간")))
    while len(parts) > 1 and parts[0][0] == 0:
        parts.pop(0)
    return " ".join(f"{value}{unit}" for value, unit in parts)


def motor_lifespan_info(motor, now: datetime | None = None) -> dict | None:
    """모터 수명 계산 — **경과율·잔여 수명의 유일한 출처다** (05 §4.1).

    화면마다 따로 계산하면 같은 모터에 다른 숫자가 찍힌다. 임계값에서 이미 겪은 결함이라
    (`04 §2`) 상세·현황·리포트가 모두 이 함수를 본다.

    가동시간은 구동일자부터 지금까지를 `MOTOR_DAILY_OPERATING_HOURS`(현재 24시간 연속)로
    환산한다. 가동률을 도입하려면 그 상수만 바꾸면 이 함수의 결과가 전부 따라 바뀐다.

    두 값 중 하나라도 없으면 `None`을 반환한다 — 관리자 화면에서 입력하지 않고 등록한
    모터가 있을 수 있다(`04 §3.3`). 호출측은 `-`로 표시한다.
    """
    lifespan = motor["lifespan_hours"] if "lifespan_hours" in motor.keys() else None
    started_raw = motor["operation_started_at"] if "operation_started_at" in motor.keys() else None
    if not lifespan or lifespan <= 0 or not started_raw:
        return None

    started = parse_utc(started_raw)
    now = now or datetime.now(timezone.utc)
    elapsed_days = max((now - started).total_seconds() / 86400, 0)
    elapsed_hours = elapsed_days * MOTOR_DAILY_OPERATING_HOURS
    remaining_hours = lifespan - elapsed_hours

    used_percent = elapsed_hours / lifespan * 100
    return {
        "lifespan_hours": lifespan,
        "started_at": started,
        "elapsed_hours": elapsed_hours,
        "remaining_hours": remaining_hours,
        "used_percent": used_percent,
        "is_over": remaining_hours <= 0,
        # 초과분도 얼마나 넘겼는지 알아야 교체 우선순위를 정할 수 있다.
        "duration_text": format_life_duration(abs(remaining_hours)),
        # **소수점 2자리 + 버림이다** (2026-08-13 사용자 요청·지적으로 두 번 고침).
        #
        # 반올림하면 안 되는 이유: 99.77%를 정수로 반올림하면 100%가 되어 **남은 수명이
        # 5일인데 화면은 다 썼다고 말한다.** 담당자가 교체 시점을 판단하는 숫자라 넘지 않은
        # 것을 넘었다고 하면 안 된다. 2자리에서도 마찬가지다 — 99.999%는 99.99%로 적는다.
        #
        # 2자리인 이유: 수명이 수만 시간이라 1%가 수백 시간이다. 정수로 끊으면 며칠~몇 주가
        # 같은 숫자에 뭉개져 교체가 임박한 설비들의 순서를 가릴 수 없다.
        "used_percent_text": f"{math.floor(used_percent * 100) / 100:.2f}%",
    }
