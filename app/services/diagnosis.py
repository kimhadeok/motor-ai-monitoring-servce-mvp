"""진단 근거 계산 및 규칙 기반 진단 생성.

역할이 둘이다 (2026-08-10 기준).

1. **근거 측정** — `build_diagnosis_facts()`가 텔레메트리에서 추세·동반 이상 지표를 계산한다.
   이 dict는 LangGraph 진단 에이전트(`app/agents/diagnosis_agent.py`)의 grounding이자
   리포트 "측정 근거" 칩의 원천이다. 에이전트가 도입된 뒤에도 여기가 사실의 출처다.
2. **규칙 기반 진단** — `build_rule_based_result()`가 같은 근거로 `DiagnosisResult`를 만든다.
   에이전트의 **폴백 경로**다. 키가 없거나 LLM이 실패해도 리포트는 항상 나온다
   (CLAUDE.md fallback 요구사항).

**근거 계산과 문장 생성을 분리한 이유** (2026-08-07): 종전 구현은 추세와 연쇄 영향을
측정하지 않고 문자열에 박아 두어, 지표와 무관하게 "온도와 진동이 함께 상승하는 패턴은
베어링 윤활 부족의 전형적 징후"가 전류 이상 리포트에도 그대로 나갔다. 사실이 아닌 진단이
담당자에게 전달된다. 이제 근거는 텔레메트리에서 측정하고, 문장은 그 근거만 서술한다.
에이전트에도 같은 제약을 프롬프트로 걸고 `_verify()`로 확인한다.
"""

from datetime import timedelta

from app.agents.schema import DiagnosisResult
from app.config import (
    FAULT_LEAD_TIME_URGENCY,
    LONG_TERM_TREND_HOURS,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_STATUS_COLUMNS,
    METRIC_THRESHOLDS,
    METRIC_UNITS,
    SHORT_TERM_BUFFER_HOURS,
    STATUS_KOREAN_LABELS,
    TREND_SIGNIFICANT_RATIO,
    parse_utc,
)
from app.rag.knowledge import lookup_fault_modes, metric_characteristic


# 여유 시간대 → 방치 시 서술. MotorSense 제품소개서 p4의 징후 시간 체인을 따른다.
_OUTLOOK_BY_LEAD_TIME = {
    "DAYS": "수일 내 고장으로 진행될 수 있는 유형이므로 이번 교대 내 조치를 권장합니다.",
    "WEEKS": "수 주 내 점검이 필요한 유형입니다. 다음 계획 정비까지 미루지 마십시오.",
    "MONTHS": "진행이 비교적 느린 유형이라 계획 정비 일정에 포함해 대응할 수 있습니다.",
}


def _measure_trend(conn, motor_id: str, metric: str, event_dt, hours: int) -> dict | None:
    """이벤트 시각 기준 `hours`시간 윈도우의 시작·끝 값과 변화량.

    `motors.get_metric_trend()`는 "지금" 기준이라 과거 이벤트 리포트에는 쓸 수 없다 —
    이벤트 이후에 수집된 값이 윈도우에 섞여 들어간다. 여기서는 윈도우를 이벤트 시각에서
    끊는다. 데이터가 부족하면 None을 반환해 호출측이 해당 문장을 아예 생략하게 한다.
    """
    if metric not in METRIC_NAMES:  # 컬럼명을 그대로 넣으므로 화이트리스트로 막는다
        return None

    end = event_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    start = (event_dt - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    try:
        row = conn.execute(
            f"SELECT MIN({metric}) AS lo, MAX({metric}) AS hi, COUNT(*) AS n "
            "FROM motor_telemetry WHERE motor_id = ? AND time BETWEEN ? AND ?",
            (motor_id, start, end),
        ).fetchone()
        first = conn.execute(
            f"SELECT {metric} AS v FROM motor_telemetry "
            "WHERE motor_id = ? AND time BETWEEN ? AND ? ORDER BY time ASC LIMIT 1",
            (motor_id, start, end),
        ).fetchone()
        last = conn.execute(
            f"SELECT {metric} AS v FROM motor_telemetry "
            "WHERE motor_id = ? AND time BETWEEN ? AND ? ORDER BY time DESC LIMIT 1",
            (motor_id, start, end),
        ).fetchone()
    except Exception:
        return None

    if row is None or not row["n"] or first is None or last is None:
        return None

    start_value, end_value = first["v"], last["v"]
    delta = end_value - start_value
    scale = max(abs(start_value), 1e-6)

    if abs(delta) / scale < TREND_SIGNIFICANT_RATIO:
        direction = "유지"
    else:
        direction = "상승" if delta > 0 else "하락"

    return {
        "hours": hours,
        "start_value": round(start_value, 1),
        "end_value": round(end_value, 1),
        "delta": round(delta, 1),
        "direction": direction,
        "peak": round(row["hi"], 1),
        "samples": row["n"],
    }


def _companion_metrics(telemetry, metric: str) -> list[dict]:
    """이벤트 시점에 함께 정상 범위를 벗어난 다른 지표들."""
    companions = []
    for name in METRIC_NAMES:
        if name == metric:
            continue
        status = telemetry[METRIC_STATUS_COLUMNS[name]]
        if status == "NORMAL":
            continue
        companions.append(
            {
                "label": METRIC_LABELS[name],
                "value": telemetry[name],
                "unit": METRIC_UNITS[name],
                "status": status,
                "status_class": status.lower(),
            }
        )
    return companions


def build_diagnosis_facts(
    conn, motor_id: str, metric: str, status: str, event_time, telemetry,
    thresholds: dict | None = None,
) -> dict:
    """리포트 섹션 2가 근거로 삼는 측정값 모음.

    문장 생성과 분리해 둔다. 이 dict가 그대로 진단 에이전트의 근거(grounding)이자
    규칙 기반 폴백의 입력이다 — 두 경로가 같은 사실을 본다.
    """
    event_dt = parse_utc(event_time)
    faults = lookup_fault_modes(metric)

    lead_times = [f["lead_time_band"] for f in faults if f.get("lead_time_band")]
    most_urgent = min(lead_times, key=lambda b: FAULT_LEAD_TIME_URGENCY.get(b, 9), default=None)

    # 임계값은 모터별이다 (2026-08-11). 진단 근거가 화면·리포트와 다른 기준을 인용하면
    # 담당자가 어느 숫자를 믿어야 할지 알 수 없다.
    _, warning, danger, fault_level = (thresholds or METRIC_THRESHOLDS)[metric]
    return {
        "metric": metric,
        "label": METRIC_LABELS[metric],
        "unit": METRIC_UNITS[metric],
        "value": telemetry[metric],
        "threshold": danger if status in ("DANGER", "FAULT") else warning,
        "fault_threshold": fault_level,
        "short_term": _measure_trend(conn, motor_id, metric, event_dt, SHORT_TERM_BUFFER_HOURS),
        "long_term": _measure_trend(conn, motor_id, metric, event_dt, LONG_TERM_TREND_HOURS),
        "companions": _companion_metrics(telemetry, metric),
        "characteristic": metric_characteristic(metric),
        "lead_time_band": most_urgent,
    }


def build_rule_based_result(status: str, facts: dict) -> DiagnosisResult:
    """06_report_spec.md §2.3의 네 섹션을 규칙 기반으로 채운다.

    **진단 에이전트의 폴백 경로다** (2026-08-10). `OPENAI_API_KEY` 부재·LLM 오류·타임아웃·
    검증 실패 시 `agents/diagnosis_agent.run_diagnosis()`가 이 결과를 대신 반환한다.
    키가 없는 시연 환경에서도 리포트는 항상 나온다.

    측정하지 못한 항목은 서술하지 않는다. 데이터 없이 추세를 단언하면 담당자가 리포트를
    근거로 삼을 수 없게 된다.
    """
    label, unit = facts["label"], facts["unit"]
    status_label = STATUS_KOREAN_LABELS.get(status, status)

    summary = (
        f"{label} 수치가 {facts['value']}{unit}로 임계치({facts['threshold']}{unit})를 "
        f"초과해 {status_label} 상태입니다."
    )

    cause = f"{label} 수치가 {facts['value']}{unit}로 임계치({facts['threshold']}{unit})를 초과했습니다."
    for window, name in ((facts["short_term"], "단기"), (facts["long_term"], "장기")):
        if window is None:
            continue
        if window["direction"] == "유지":
            cause += f" {name}({window['hours']}시간) 구간은 {window['start_value']}{unit} 부근에서 큰 변동 없이 유지됐습니다."
        else:
            sign = "+" if window["delta"] > 0 else ""
            cause += (
                f" {name}({window['hours']}시간) 구간에서 {window['start_value']}{unit} → "
                f"{window['end_value']}{unit}({sign}{window['delta']}{unit}) {window['direction']}했습니다."
            )

    companions = facts["companions"]
    if companions:
        detail = ", ".join(f"{c['label']} {c['value']}{c['unit']}({c['status']})" for c in companions)
        chained_effects = [
            f"같은 시점에 {detail}도 정상 범위를 벗어났습니다.",
            "단일 지표 이상이 아니므로 공통 원인을 함께 점검해야 합니다.",
        ]
    else:
        chained_effects = [
            f"같은 시점의 다른 세 지표는 정상 범위였습니다. {label} 계통에 국한된 이상일 가능성이 높습니다."
        ]

    if status == "FAULT":
        if_ignored = "이미 고장/정지 임계를 초과했으므로 즉시 설비를 정지하고 정비를 시행해야 합니다."
    else:
        if_ignored = (
            f"현재 값이 고장 임계({facts['fault_threshold']}{unit})에 도달하면 FAULT 단계로 전이됩니다."
        )
        lead = _OUTLOOK_BY_LEAD_TIME.get(facts["lead_time_band"])
        if lead:
            if_ignored += f" {lead}"

    return DiagnosisResult(
        summary=summary,
        cause=cause,
        chained_effects=chained_effects,
        if_ignored=if_ignored,
        source="rule",
    )


def build_notification_message(motor_id: str, status: str, trigger_reason: str) -> str:
    label = STATUS_KOREAN_LABELS.get(status, status)
    return f"[{status}] {motor_id} 모터 {label} 감지 ({trigger_reason}). 리포트를 확인하세요."


def build_notification_title(motor_id: str, status: str) -> str:
    return f"[{status}] {motor_id} 이상 감지"
