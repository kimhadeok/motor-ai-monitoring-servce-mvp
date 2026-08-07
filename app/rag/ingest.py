"""RAG 인제스트 및 SOP 조회.

`data/rag_sources/*.txt`(제조사 매뉴얼, 과거 장애 이력, 방법론)를 문단 단위로 청크 분할해
ChromaDB에 적재하고, 진단 시 정비 절차(SOP)를 조회한다.

인제스트는 **부팅 경로에서 호출하지 않는다** (2026-08-07 확정). 원본이 시간에 무관한 정적
텍스트라 한 번만 임베딩하면 되고, `scripts/build_knowledge.py`로 수동 실행한 뒤 산출물
`data/chroma/`를 커밋한다. 부팅마다 임베딩 API를 호출하던 비용이 사라진다.

RAG는 OpenAI 임베딩 API에 의존하므로 네트워크/키 문제로 실패할 수 있다.
02_architecture.md §2.2 확정에 따라 실패 시 앱을 죽이지 않고 키워드 매칭으로 폴백한다.
"""

import re

from app.config import (
    METRIC_LABELS,
    RAG_FALLBACK_SOP_STEP,
    RAG_FAULT_LOOKUP_LIMIT,
    RAG_MAX_SOP_STEPS,
    RAG_SOP_DOC_TYPES,
    RAG_SOURCE_DOC_TYPES,
    RAG_SOURCES_DIR,
    RAG_TOP_K,
)
from app.rag.chroma_client import get_collection, reset_collection
from app.rag.knowledge import fault_names

# 문단 첫 줄의 고장모드 마커. 예: "#fault=BEARING_DEFECT_OUTER"
_FAULT_MARKER = re.compile(r"^#fault=([A-Z0-9_]+)\s*\n?", re.MULTILINE)

# 파일 머리말 블록. 첫 줄이 "[제조사 매뉴얼 예시 — ...]" 형태면 출처 표기이므로 청크에서 뺀다.
# 남겨두면 "각 문단이 하나의 청크가 된다" 같은 문장이 SOP 절차로 검색돼 나간다.
_HEADER_BLOCK = re.compile(r"^\[[^\]\n]*\]\s*$")


def _parse_paragraph(paragraph: str, source: str) -> tuple[str, dict]:
    """문단에서 `#fault=` 마커를 떼어내 메타데이터로 승격한다.

    마커를 본문에 남기면 임베딩 벡터에 코드 문자열이 섞여 검색 품질이 떨어지므로 제거한다.
    Chroma 메타데이터 값은 스칼라만 허용하므로 None인 키는 아예 넣지 않는다.
    """
    metadata: dict[str, str] = {"source": source}

    doc_type = RAG_SOURCE_DOC_TYPES.get(source)
    if doc_type:
        metadata["doc_type"] = doc_type

    match = _FAULT_MARKER.search(paragraph)
    if match:
        metadata["fault_code"] = match.group(1)
        paragraph = _FAULT_MARKER.sub("", paragraph, count=1)

    return paragraph.strip(), metadata


def _load_chunks() -> list[tuple[str, str, dict]]:
    """(chunk_id, 본문, 메타데이터) 목록. 문단(빈 줄) 단위로 분할."""
    chunks = []
    if not RAG_SOURCES_DIR.exists():
        return chunks

    for path in sorted(RAG_SOURCES_DIR.glob("*.txt")):
        raw = path.read_text(encoding="utf-8")
        for i, block in enumerate(c for c in raw.split("\n\n") if c.strip()):
            if _HEADER_BLOCK.match(block.strip().split("\n", 1)[0]):
                continue
            text, metadata = _parse_paragraph(block, path.name)
            if text:
                chunks.append((f"{path.stem}-{i}", text, metadata))
    return chunks


def ingest_rag_sources(force: bool = False) -> int:
    """원본 텍스트를 ChromaDB에 적재하고 청크 수를 반환. 실패 시 0.

    `scripts/build_knowledge.py`에서 수동 실행한다. 이미 같은 수의 청크가 적재돼 있으면
    생략하며, 청크 수는 그대로인데 내용만 바뀐 경우는 감지하지 못하므로 `--force`를 쓴다.
    """
    chunks = _load_chunks()
    if not chunks:
        return 0

    if not force:
        # create=False — 확인만 하고 만들지는 않는다. 여기서 만들면 아래 reset_collection()이
        # 곧바로 지우게 되어 첫 실행에 불필요한 생성/삭제가 한 번씩 더 붙는다.
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

    ids, documents, metadatas = zip(*chunks)
    try:
        collection.add(ids=list(ids), documents=list(documents), metadatas=list(metadatas))
    except Exception:
        return 0  # 임베딩 API 실패 — RAG 없이 진행
    return len(chunks)


def count_ingested_chunks() -> int:
    """적재된 청크 수. 임베딩을 요구하지 않으므로 부팅 시 호출해도 비용이 없다."""
    collection = get_collection(create=False)
    if collection is None:
        return 0
    try:
        return collection.count()
    except Exception:
        return 0


def _split_steps(text: str) -> list[str]:
    """문단을 문장 단위 절차로 분해."""
    sentences = re.split(r"(?<=[.])\s+", text.replace("\n", " "))
    return [s.strip() for s in sentences if len(s.strip()) > 8]


def _keyword_fallback(metric: str) -> list[str]:
    """RAG 이용 불가 시 원본 텍스트에 대한 키워드 매칭 (02_architecture.md §2.2).

    벡터 검색과 같은 문서 집합을 보도록 doc_type을 동일하게 제한한다. 지표 라벨뿐 아니라
    의심 고장모드 이름으로도 매칭해, 매뉴얼에 "온도"라는 단어가 없어도 절차를 찾는다.
    """
    # 지표 라벨을 최우선으로 두고 고장모드는 relevance 순서를 따른다. 문서 순서대로 모으면
    # 전류 조회에 "축 정렬 불량"이 걸린 진동 문단이 먼저 나오는 식으로 순서가 뒤집힌다.
    keywords = [METRIC_LABELS.get(metric, metric), *fault_names(metric)]

    chunks = _load_chunks()
    steps: list[str] = []
    seen: set[str] = set()

    # 바깥 루프가 doc_type이다. manual(실제 절차)을 incident(사례 서술)보다 먼저 소진해야
    # "고전류"에 '전류'가 부분 일치한 사례 문단이 절차 자리를 차지하는 일이 없다.
    for doc_type in RAG_SOP_DOC_TYPES:
        documents = [d for _, d, m in chunks if m.get("doc_type") == doc_type]
        for keyword in keywords:
            for document in documents:
                if keyword in document and document not in seen:
                    seen.add(document)
                    steps.extend(_split_steps(document))
    return steps


def query_sop_steps(motor_name: str, metric: str) -> list[str]:
    """정비 절차(SOP) 목록. RAG → 키워드 매칭 → 기본 문구 순으로 폴백한다.

    질의문에 의심 고장모드 이름을 넣어 검색을 좁힌다. 지표 라벨만으로는
    ("온도 이상 대응 정비 절차") 도메인 어휘가 없어 유사도가 느슨하게 퍼진다.
    """
    steps: list[str] = []
    label = METRIC_LABELS.get(metric, metric)

    collection = get_collection(create=False)
    if collection is not None:
        suspected = " ".join(fault_names(metric, RAG_FAULT_LOOKUP_LIMIT))
        query_text = f"{motor_name} {label} 이상 {suspected} 대응 정비 절차".replace("  ", " ")
        try:
            result = collection.query(
                query_texts=[query_text],
                n_results=RAG_TOP_K,
                # 방법론 문서가 SOP로 나가지 않도록 제한한다. doc_type이 없는 청크도 제외된다.
                where={"doc_type": {"$in": list(RAG_SOP_DOC_TYPES)}},
            )
            for document in result.get("documents", [[]])[0]:
                steps.extend(_split_steps(document))
        except Exception:
            steps = []  # 임베딩/검색 실패 — 아래 폴백으로

    if not steps:
        steps = _keyword_fallback(metric)
    if not steps:
        steps = [RAG_FALLBACK_SOP_STEP]

    return steps[:RAG_MAX_SOP_STEPS]
