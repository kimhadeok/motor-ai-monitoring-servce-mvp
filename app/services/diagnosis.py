"""진단 텍스트 및 알림 문구 생성.

MVP 스캐폴딩 단계에서는 규칙 기반 템플릿으로 진단 텍스트를 만든다.
이후 LangChain/LangGraph 진단 에이전트(02_architecture.md §2.4)가 이 모듈의
`build_diagnosis_text()`를 대체한다 — 호출측(app/reports/service.py)은 그대로 두고
이 함수만 교체할 수 있도록 시그니처를 데이터 중심으로 유지한다.
"""

from app.config import (
    LONG_TERM_TREND_HOURS,
    METRIC_LABELS,
    METRIC_THRESHOLDS,
    METRIC_UNITS,
    SHORT_TERM_BUFFER_HOURS,
)

_STATUS_KOREAN = {"DANGER": "위험", "FAULT": "고장/정지"}


def build_diagnosis_text(metric: str, value: float, status: str) -> str:
    """06_report_spec.md §2.3 — 주요 원인 / 연쇄 영향 / 방치 시 예상 결과 3단 구성."""
    label = METRIC_LABELS[metric]
    unit = METRIC_UNITS[metric]
    _, warning, danger, _ = METRIC_THRESHOLDS[metric]
    threshold = danger if status in ("DANGER", "FAULT") else warning

    outlook = (
        "이미 고장/정지 임계를 초과했으므로 즉시 설비를 정지하고 정비를 시행해야 합니다."
        if status == "FAULT"
        else "현재 추세가 지속될 경우 FAULT(고장/정지) 단계로 진행될 가능성이 있어 조속한 점검을 권장합니다."
    )

    return (
        f"주요 원인: {label} 수치가 {value}{unit}로 임계치({threshold}{unit})를 초과했습니다. "
        f"단기({SHORT_TERM_BUFFER_HOURS}시간) 버퍼 데이터 기준 상승 추세가 관측되며, "
        f"장기({LONG_TERM_TREND_HOURS}시간) 트렌드 분석 결과 점진적 악화 패턴으로 판단됩니다.\n"
        f"연쇄 영향 분석: 온도와 진동이 함께 상승하는 패턴은 베어링 윤활 부족의 전형적 징후로, "
        f"과거 유사 장애 이력과 일치합니다.\n"
        f"방치 시 예상 결과: {outlook}"
    )


def build_notification_message(motor_id: str, status: str, trigger_reason: str) -> str:
    label = _STATUS_KOREAN.get(status, status)
    return f"[{status}] {motor_id} 모터 {label} 감지 ({trigger_reason}). 리포트를 확인하세요."


def build_notification_title(motor_id: str, status: str) -> str:
    return f"[{status}] {motor_id} 이상 감지"
