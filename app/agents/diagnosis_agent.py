"""LangGraph 진단 에이전트 (01_tech_stack.md §2.4, 02_architecture.md §2.4).

`prepare` → `diagnose` → `finalize` 3노드의 최소 그래프다. 지금은 선형이지만 노드 경계를
그래프로 잡아 두면 이후 RAG 검색 노드·자기검증 노드를 붙일 때 호출측을 바꾸지 않아도 된다.

**모듈 최상단에서 langgraph/langchain을 import 하지 않는다.** 실측(2026-08-10) 콜드 import가
`langgraph` 3.17초 + `langchain_openai` 0.96초다. 이 비용이 Streamlit 부팅 경로에 붙으면
4.43초로 줄여 놓은 콜드 스타트(02 §6.1.1)가 그대로 무너진다. `app/reports/generator.py`가
WeasyPrint에 쓰는 것과 같은 함수 내부 지연 import를 쓴다 — 리포트를 처음 여는 사용자만
이 비용을 치르고, 그마저 프로세스당 1회다.

**이 모듈은 예외를 밖으로 던지지 않는다.** 키 부재·타임아웃·API 오류·검증 실패는 모두
규칙 기반 진단(`services/diagnosis.build_rule_based_result`)으로 떨어진다. 리포트 생성이
LLM 가용성에 걸리면 안 된다 (CLAUDE.md fallback 요구사항).
"""

import logging
import re
from typing import TypedDict

from app.agents.schema import DiagnosisContext, DiagnosisPayload, DiagnosisResult
from app.config import (
    DIAGNOSIS_LLM_ENABLED,
    DIAGNOSIS_LLM_MAX_RETRIES,
    DIAGNOSIS_LLM_TEMPERATURE,
    DIAGNOSIS_LLM_TIMEOUT_SECONDS,
    DIAGNOSIS_MAX_CHAINED_EFFECTS,
    LLM_REASONING_MODEL,
    OPENAI_API_KEY,
)
from app.prompts import DIAGNOSIS_SYSTEM_PROMPT, DIAGNOSIS_USER_TEMPLATE
from app.services.diagnosis import build_rule_based_result

logger = logging.getLogger(__name__)


class _DiagnosisState(TypedDict, total=False):
    context: DiagnosisContext
    messages: list[tuple[str, str]]
    payload: DiagnosisPayload | None
    result: DiagnosisResult | None
    # 폴백으로 떨어진 이유. 로그로만 쓰고 리포트에는 싣지 않는다 —
    # 담당자에게 필요한 것은 진단이지 파이프라인 사정이 아니다.
    fallback_reason: str | None


# --- 노드 ---------------------------------------------------------------------------


def _prepare(state: _DiagnosisState) -> dict:
    """측정 근거를 프롬프트 메시지로 조립한다. DB·지식 조회는 하지 않는다."""
    context = state["context"]
    system = DIAGNOSIS_SYSTEM_PROMPT.format(max_effects=DIAGNOSIS_MAX_CHAINED_EFFECTS)
    user = DIAGNOSIS_USER_TEMPLATE.format(
        motor_name=context.motor_name,
        motor_id=context.motor_id,
        model_name=context.model_name,
        installation_location=context.installation_location,
        metric_lines=context.metric_lines(),
        trend_lines=context.trend_lines(),
        companion_lines=context.companion_lines(),
        characteristic_line=context.characteristic_line() or "- 특성 정보 없음",
        fault_lines=context.fault_lines(),
    )
    return {"messages": [("system", system), ("user", user)]}


def _diagnose(state: _DiagnosisState) -> dict:
    """LLM 구조화 출력 호출. 실패는 예외가 아니라 `fallback_reason`으로 표현한다."""
    if not DIAGNOSIS_LLM_ENABLED:
        return {"payload": None, "fallback_reason": "DIAGNOSIS_LLM_ENABLED=false"}
    if not OPENAI_API_KEY:
        return {"payload": None, "fallback_reason": "OPENAI_API_KEY 없음"}

    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=LLM_REASONING_MODEL,
            api_key=OPENAI_API_KEY,
            temperature=DIAGNOSIS_LLM_TEMPERATURE,
            timeout=DIAGNOSIS_LLM_TIMEOUT_SECONDS,
            max_retries=DIAGNOSIS_LLM_MAX_RETRIES,
        ).with_structured_output(DiagnosisPayload)
        return {"payload": llm.invoke(state["messages"])}
    except Exception as exc:
        return {"payload": None, "fallback_reason": f"{type(exc).__name__}: {exc}"}


def _finalize(state: _DiagnosisState) -> dict:
    """검증·폴백 게이트. 여기를 통과한 것만 `source="llm"`이 된다."""
    context = state["context"]
    payload = state.get("payload")

    if payload is None:
        return {"result": build_rule_based_result(context.status, context.facts)}

    reason = _verify(payload, context)
    if reason is not None:
        logger.warning("진단 LLM 출력 검증 실패 (%s) — 규칙 기반으로 대체: %s", context.motor_id, reason)
        return {
            "result": build_rule_based_result(context.status, context.facts),
            "fallback_reason": reason,
        }

    return {
        "result": DiagnosisResult(
            summary=payload.summary.strip(),
            cause=payload.cause.strip(),
            # 개수 초과는 폴백 사유로 삼지 않는다. 내용이 정확한 진단을 통째로 버리는 것보다
            # 상한까지 싣는 편이 담당자에게 낫다 (상한 근거는 config 주석 참조).
            chained_effects=[e.strip() for e in payload.chained_effects if e.strip()][
                :DIAGNOSIS_MAX_CHAINED_EFFECTS
            ],
            if_ignored=payload.if_ignored.strip(),
            source="llm",
        )
    }


# --- 검증 ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _measured_values(facts: dict) -> set[float]:
    """진단이 인용했어야 할 측정값 후보."""
    values = {facts.get("value"), facts.get("threshold"), facts.get("fault_threshold")}
    for window in (facts.get("short_term"), facts.get("long_term")):
        if window:
            values.update((window["start_value"], window["end_value"], window["peak"]))
    for companion in facts.get("companions") or []:
        values.add(companion["value"])
    return {float(v) for v in values if isinstance(v, (int, float))}


def _verify(payload: DiagnosisPayload, context: DiagnosisContext) -> str | None:
    """통과하면 None, 실패하면 사유 문자열.

    수치 인용을 검사하는 이유 (2026-08-10 실측): 측정 근거를 프롬프트로 넣어줘도 모델이
    "온도가 급격히 상승하여 냉각 문제로 보입니다" 같은 일반론을 반환했다. 어느 모터에나
    들어맞는 문장은 담당자가 근거로 삼을 수 없고, 06 §2.3이 규칙 기반 템플릿에서 걷어낸
    문제를 그대로 되살린다. 형식만 맞고 내용이 빈 응답은 규칙 기반보다 나쁘다.
    """
    if not payload.summary.strip():
        return "summary 비어 있음"
    if not payload.cause.strip():
        return "cause 비어 있음"
    if not payload.if_ignored.strip():
        return "if_ignored 비어 있음"
    if not [e for e in payload.chained_effects if e.strip()]:
        return "chained_effects 비어 있음"

    expected = _measured_values(context.facts)
    if expected:
        cited = {float(n) for n in _NUMBER_RE.findall(f"{payload.summary} {payload.cause}")}
        # 반올림 표기(92.4 vs 92.43)를 허용한다. 값 자체를 안 쓴 경우만 걸러내는 것이 목적이다.
        if not any(abs(c - e) < 0.05 for c in cited for e in expected):
            return "원인 서술에 측정값 인용 없음"

    return None


# --- 그래프 -------------------------------------------------------------------------

_compiled_graph = None


def _get_graph():
    """컴파일된 그래프를 프로세스당 1회만 만든다.

    `st.cache_resource`를 쓰지 않는 이유: 이 경로는 `scripts/seed_data.py`처럼 Streamlit
    런타임 밖에서도 호출된다 (`services/bootstrap.py`의 캐시 래핑과 같은 판단).
    """
    global _compiled_graph

    if _compiled_graph is None:
        from langgraph.graph import END, START, StateGraph

        builder = StateGraph(_DiagnosisState)
        builder.add_node("prepare", _prepare)
        builder.add_node("diagnose", _diagnose)
        builder.add_node("finalize", _finalize)
        builder.add_edge(START, "prepare")
        builder.add_edge("prepare", "diagnose")
        builder.add_edge("diagnose", "finalize")
        builder.add_edge("finalize", END)
        _compiled_graph = builder.compile()

    return _compiled_graph


def run_diagnosis(context: DiagnosisContext) -> DiagnosisResult:
    """진단 1건을 생성한다. **어떤 경우에도 예외를 던지지 않는다.**

    반환값의 `source`가 `"llm"`이면 에이전트 생성물, `"rule"`이면 규칙 기반 폴백이다.
    리포트는 이 값으로 진단 모델 라벨을 고른다 (06 §2.3, 2026-08-10 확정).
    """
    try:
        state = _get_graph().invoke({"context": context})
    except Exception as exc:
        # 그래프 자체가 실패한 경우 (langgraph import 실패 등)
        logger.warning("진단 그래프 실행 실패 (%s): %s", context.motor_id, exc)
        return build_rule_based_result(context.status, context.facts)

    if reason := state.get("fallback_reason"):
        logger.info("진단 폴백 (%s): %s", context.motor_id, reason)

    result = state.get("result")
    if isinstance(result, DiagnosisResult):
        return result
    return build_rule_based_result(context.status, context.facts)
