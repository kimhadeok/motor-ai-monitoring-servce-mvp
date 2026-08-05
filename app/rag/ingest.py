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


def ingest_rag_sources(force: bool = False) -> int:
    """원본 텍스트를 ChromaDB에 적재하고 청크 수를 반환. 실패 시 0.

    이미 같은 수의 청크가 적재돼 있으면 생략한다. 부팅마다 전량 재임베딩하면
    OpenAI 임베딩 API를 반복 호출해 콜드 스타트가 그만큼 길어지기 때문이다.
    `collection.count()`는 임베딩을 요구하지 않으므로 판정 자체에는 비용이 없다.

    청크 수는 그대로인데 원본 내용만 바뀐 경우는 감지하지 못한다 —
    이때는 `scripts/seed_data.py --force`로 재인제스트한다.
    """
    chunks = _load_chunks()
    if not chunks:
        return 0

    if not force:
        # create=False — 확인만 하고 만들지는 않는다. 여기서 만들면 아래 reset_collection()이
        # 곧바로 지우게 되어 첫 부팅에 불필요한 생성/삭제가 한 번씩 더 붙는다.
        existing = get_collection(create=False)
        if existing is not None:
            try:
                if existing.count() == len(chunks):
                    return len(chunks)  # 이미 최신 — 재임베딩 생략
            except Exception:
                pass  # 컬렉션 상태 확인 실패 — 아래에서 새로 적재

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
