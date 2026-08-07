"""참조 지식 조회 — 지표 이상 시 의심되는 고장 모드.

`uploads/Reference/`의 PDF에서 큐레이션한 "지표 → 고장모드 → 부품" 매핑을 제공한다.
원본은 `data/knowledge/fault_modes.json`이며, 커밋된 정적 데이터라 등록 절차가 없다.

DB에 두지 않는 이유 (2026-08-07 확정): 고장모드 9건 + 지표 매핑 17건으로 총 26행이고,
런타임 테이블(motors/telemetry)과 조인할 지점이 없다. SQLite에 넣으면 `data/app.db`가
부팅마다 재생성되는 수명주기에 끌려 들어가 시드 비용만 붙는다.

ChromaDB와의 역할 분담: 여기가 "무엇을 의심할지"를 결정적으로 정하고,
그 어휘로 `app/rag/ingest.py`가 "어떻게 조치할지"를 벡터 검색으로 묻는다.
"""

import json
from functools import lru_cache

from app.config import (
    FAULT_KNOWLEDGE_FILE,
    FAULT_LEAD_TIME_LABELS,
    KNOWLEDGE_DIR,
    RAG_FAULT_LOOKUP_LIMIT,
    RAG_FAULT_QUERY_MAX_RELEVANCE,
)

_EMPTY: dict[str, list] = {"fault_modes": [], "metric_fault_map": []}


@lru_cache(maxsize=1)
def load_fault_knowledge() -> dict[str, list]:
    """지식 JSON을 1회 읽어 캐시한다. 읽기 실패 시 빈 구조를 반환한다.

    지식이 없어도 앱은 동작해야 한다 (CLAUDE.md fallback). 파일이 없거나 깨졌을 때
    예외를 올리면 리포트 생성 전체가 죽으므로 여기서 삼킨다.
    """
    path = KNOWLEDGE_DIR / FAULT_KNOWLEDGE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _EMPTY

    if not isinstance(data, dict):
        return _EMPTY
    return {
        "fault_modes": data.get("fault_modes") or [],
        "metric_fault_map": data.get("metric_fault_map") or [],
    }


def lookup_fault_modes(metric: str, limit: int = RAG_FAULT_LOOKUP_LIMIT) -> list[dict]:
    """지표 이상 시 의심되는 고장 모드 목록. relevance(1=주지표) 오름차순.

    메모리 내 필터링이라 DB·네트워크 접근이 없다. 매핑에 없는 지표는 빈 목록을 반환한다.
    반환 항목은 fault_modes 정의에 매핑의 relevance/evidence를 합친 형태다.
    """
    knowledge = load_fault_knowledge()
    by_code = {f["fault_code"]: f for f in knowledge["fault_modes"] if "fault_code" in f}

    matched = []
    for row in knowledge["metric_fault_map"]:
        if row.get("metric_name") != metric:
            continue
        fault = by_code.get(row.get("fault_code"))
        if fault is None:
            continue  # 매핑은 있는데 정의가 없는 경우 — 조용히 건너뛴다
        matched.append(
            {
                **fault,
                "relevance": row.get("relevance", 3),
                "evidence": row.get("evidence"),
                # 리포트가 그대로 출력할 수 있도록 코드가 아닌 문구를 함께 넣는다.
                "lead_time_label": FAULT_LEAD_TIME_LABELS.get(fault.get("lead_time_band"), ""),
            }
        )

    # relevance 동률이면 JSON에 적힌 순서를 유지한다 (sorted는 안정 정렬).
    matched.sort(key=lambda f: f["relevance"])
    return matched[:limit]


def fault_names(
    metric: str,
    limit: int = RAG_FAULT_LOOKUP_LIMIT,
    max_relevance: int = RAG_FAULT_QUERY_MAX_RELEVANCE,
) -> list[str]:
    """의심 고장 모드의 한글명 목록. RAG 질의문 보강에 쓴다.

    `max_relevance`로 참고 수준(3)을 걸러낸다. 전류 조회에 relevance 3인 "축 정렬 불량"까지
    질의어로 넣으면 전기적 고장 절차 대신 정렬 불량 문단이 검색돼 순위가 뒤집힌다.
    """
    return [
        f["fault_name_ko"]
        for f in lookup_fault_modes(metric, limit)
        if f.get("fault_name_ko") and f["relevance"] <= max_relevance
    ]
