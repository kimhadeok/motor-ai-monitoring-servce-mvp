"""진단 에이전트의 입출력 구조체.

템플릿과 분리해 둔다 (2026-08-06 계획 확정). 리포트는 이 구조체를 소비하는 여러 화면 중
하나일 뿐이고, 이후 별도 진단 화면이 생기면 같은 구조체를 그대로 쓴다.

`DiagnosisPayload`와 `DiagnosisResult`를 나눈 이유: LLM에는 payload 4개 필드만 요구해야
한다. `source`까지 스키마에 넣으면 모델이 "이 진단을 누가 만들었는지"를 스스로 채우게 되고,
폴백으로 만든 결과에 `source="llm"`이 실릴 수 있다. 그 값으로 리포트의 진단 모델 라벨을
고르므로(06 §2.3), 생성 주체는 코드가 정한다.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.config import (
    FAULT_LEAD_TIME_LABELS,
    METRIC_LABELS,
    STATUS_KOREAN_LABELS,
)


class DiagnosisPayload(BaseModel):
    """LLM structured output 스키마 — 모델이 채우는 필드만 담는다.

    각 필드의 description은 그대로 모델에 전달되는 지시문이다. 프롬프트가 길어져 후반부
    지시가 묻히더라도 스키마 설명은 필드 바로 옆에 붙으므로, 형식 제약은 여기에 둔다.
    """

    summary: str = Field(
        description=(
            "한 줄 요약. 어느 지표가 어떤 상태인지 측정값과 함께 한 문장으로 적습니다. "
            "예: '베어링 온도가 92.4°C로 위험 임계(85°C)를 초과했습니다.'"
        )
    )
    cause: str = Field(
        description=(
            "주요 원인. 제공된 측정 근거(현재값·임계값·추세 구간)를 인용해 1~3문장으로 "
            "설명합니다. 측정 근거에 없는 원인을 단정하지 마십시오."
        )
    )
    chained_effects: list[str] = Field(
        description=(
            "연쇄 영향. 항목마다 한 문장. 동반 이상 지표가 있으면 그 측정값을 인용하고, "
            "없으면 다른 지표가 정상이라는 사실에 근거해 서술합니다."
        )
    )
    if_ignored: str = Field(
        description=(
            "방치 시 예상 결과. 고장 임계까지의 거리와 의심 고장 모드의 여유 시간대에 "
            "근거해 1~2문장으로 적습니다."
        )
    )


class DiagnosisResult(DiagnosisPayload):
    """리포트/화면이 소비하는 최종 결과. `source`로 생성 경로를 구분한다."""

    source: Literal["llm", "rule"] = "rule"


class DiagnosisContext(BaseModel):
    """에이전트 입력. `build_diagnosis_facts()`가 이미 측정한 값을 그대로 물려받는다.

    여기서 DB나 지식 파일을 다시 조회하지 않는다 — 호출측(`reports/service.py`)이 리포트
    렌더에 쓰려고 이미 가져온 값을 넘겨받는다. 같은 이벤트에 대해 리포트 본문과 진단
    프롬프트가 서로 다른 근거를 보는 상황을 만들지 않기 위한 것이다.
    """

    motor_id: str
    motor_name: str
    model_name: str
    installation_location: str
    status: str
    trigger_reason: str | None = None
    # services/diagnosis.py::build_diagnosis_facts()의 반환 dict
    facts: dict
    # rag/knowledge.py::lookup_fault_modes()의 반환 목록
    suspected_faults: list[dict] = Field(default_factory=list)

    # --- 프롬프트에 넣을 텍스트 블록 -------------------------------------------------
    # 문자열 "틀"은 app/prompts.py에 있고, 여기서는 측정값을 사람이 읽을 수 있는 줄로
    # 바꾸기만 한다. 측정하지 못한 항목은 줄 자체를 만들지 않는다 — 빈 값을 "없음"으로
    # 채워 보내면 모델이 그것을 사실로 서술한다.

    def metric_lines(self) -> str:
        f = self.facts
        unit = f["unit"]
        lines = [
            f"- 트리거 지표: {f['label']} {f['value']}{unit}",
            f"- 현재 상태: {STATUS_KOREAN_LABELS.get(self.status, self.status)}"
            f" (초과한 임계값 {f['threshold']}{unit}, 고장 임계값 {f['fault_threshold']}{unit})",
        ]
        if self.trigger_reason:
            lines.append(f"- 감지 사유: {self.trigger_reason}")
        return "\n".join(lines)

    def trend_lines(self) -> str:
        unit = self.facts["unit"]
        lines = []
        for window, name in ((self.facts["short_term"], "단기"), (self.facts["long_term"], "장기")):
            if window is None:
                continue  # 표본이 없는 구간은 아예 언급하지 않는다
            lines.append(
                f"- {name} {window['hours']}시간: {window['start_value']}{unit} → "
                f"{window['end_value']}{unit} ({window['delta']:+}{unit}, {window['direction']}, "
                f"표본 {window['samples']}건, 최고 {window['peak']}{unit})"
            )
        return "\n".join(lines) or "- 추세를 계산할 표본이 없습니다. 추세를 서술하지 마십시오."

    def companion_lines(self) -> str:
        companions = self.facts["companions"]
        if not companions:
            return "- 같은 시점의 다른 세 지표는 모두 정상 범위였습니다."
        return "\n".join(
            f"- {c['label']} {c['value']}{c['unit']} ({c['status']})" for c in companions
        )

    def characteristic_line(self) -> str:
        char = self.facts.get("characteristic")
        if not char:
            return ""
        label = METRIC_LABELS.get(self.facts["metric"], self.facts["metric"])
        return f"- {label}는 {char.get('role', '')}입니다. {char.get('note', '')}".strip()

    def fault_lines(self) -> str:
        if not self.suspected_faults:
            return "- 이 지표에 매핑된 고장 모드 정보가 없습니다."
        lines = []
        for fault in self.suspected_faults:
            lead = FAULT_LEAD_TIME_LABELS.get(fault.get("lead_time_band"), "여유 시간대 미상")
            parts = [f"- {fault.get('fault_name_ko', '')} ({lead}, {fault.get('relevance_label', '')})"]
            if fault.get("evidence"):
                parts.append(f"근거: {fault['evidence']}")
            if fault.get("typical_part"):
                parts.append(f"교체 대상: {fault['typical_part']}")
            lines.append(" / ".join(parts))
        return "\n".join(lines)
