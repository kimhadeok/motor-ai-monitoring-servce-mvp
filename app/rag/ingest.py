"""RAG 인제스트 및 SOP 조회.

`data/rag_sources/*.txt`(제조사 매뉴얼, 과거 장애 이력)를 문단 단위로 청크 분할해
ChromaDB에 적재하고, 진단 시 정비 절차(SOP)를 조회한다.

RAG는 OpenAI 임베딩 API에 의존하므로 네트워크/키 문제로 실패할 수 있다.
02_architecture.md §2.2 확정에 따라 실패 시 앱을 죽이지 않고 키워드 매칭으로 폴백한다.
"""

import re

from app.config import (
    METRIC_LABELS,
    RAG_FALLBACK_SOP_STEP,
    RAG_MAX_SOP_STEPS,
    RAG_SOURCES_DIR,
    RAG_TOP_K,
)
from app.rag.chroma_client import get_collection, reset_collection


def _load_chunks() -> list[tuple[str, str, str]]:
    """(chunk_id, 원문, 출처파일명) 목록. 문단(빈 줄) 단위로 분할."""
    chunks = []
    if not RAG_SOURCES_DIR.exists():
        return chunks

    for path in sorted(RAG_SOURCES_DIR.glob("*.txt")):
        paragraphs = [c.strip() for c in path.read_text(encoding="utf-8").split("\n\n") if c.strip()]
        for i, paragraph in enumerate(paragraphs):
            chunks.append((f"{path.stem}-{i}", paragraph, path.name))
    return chunks


def ingest_rag_sources() -> int:
    """원본 텍스트를 ChromaDB에 적재하고 청크 수를 반환. 실패 시 0."""
    chunks = _load_chunks()
    if not chunks:
        return 0

    collection = reset_collection()
    if collection is None:
        return 0  # API 키 부재 등 — RAG 없이 진행

    ids, documents, metadatas = zip(*[(c[0], c[1], {"source": c[2]}) for c in chunks])
    try:
        collection.add(ids=list(ids), documents=list(documents), metadatas=list(metadatas))
    except Exception:
        return 0  # 임베딩 API 실패 — RAG 없이 진행
    return len(chunks)


def _split_steps(text: str) -> list[str]:
    """문단을 문장 단위 절차로 분해."""
    sentences = re.split(r"(?<=[.])\s+", text.replace("\n", " "))
    return [s.strip() for s in sentences if len(s.strip()) > 8]


def _keyword_fallback(metric: str) -> list[str]:
    """RAG 이용 불가 시 원본 텍스트에 대한 키워드 매칭 (02_architecture.md §2.2)."""
    keyword = METRIC_LABELS.get(metric, metric)
    steps: list[str] = []
    for _, document, _source in _load_chunks():
        if keyword in document:
            steps.extend(_split_steps(document))
    return steps


def query_sop_steps(motor_name: str, metric: str) -> list[str]:
    """정비 절차(SOP) 목록. RAG → 키워드 매칭 → 기본 문구 순으로 폴백한다."""
    steps: list[str] = []

    collection = get_collection(create=False)
    if collection is not None:
        query_text = f"{motor_name} {METRIC_LABELS.get(metric, metric)} 이상 대응 정비 절차"
        try:
            result = collection.query(query_texts=[query_text], n_results=RAG_TOP_K)
            for document in result.get("documents", [[]])[0]:
                steps.extend(_split_steps(document))
        except Exception:
            steps = []  # 임베딩/검색 실패 — 아래 폴백으로

    if not steps:
        steps = _keyword_fallback(metric)
    if not steps:
        steps = [RAG_FALLBACK_SOP_STEP]

    return steps[:RAG_MAX_SOP_STEPS]
