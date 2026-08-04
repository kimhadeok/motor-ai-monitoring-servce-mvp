"""ChromaDB persistent client 팩토리.

Streamlit Community Cloud(Debian 기반 컨테이너)의 시스템 sqlite3가 ChromaDB 요구 버전(3.35+)보다
낮을 수 있어, pysqlite3-binary로 표준 sqlite3 모듈을 교체하는 우회가 필요하다.
pysqlite3-binary는 Linux 전용 패키지(pyproject.toml에 sys_platform 마커)라 로컬 Windows
개발환경에는 설치되지 않으므로, import 실패 시 조용히 시스템 sqlite3를 그대로 사용한다.
"""

import sys

try:
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import chromadb  # noqa: E402  (sqlite3 패치 이후에 import 되어야 함)
from chromadb.utils import embedding_functions  # noqa: E402

from app.config import (  # noqa: E402
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    EMBEDDING_MODEL,
    OPENAI_API_KEY,
)

_client: chromadb.ClientAPI | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    return _client


def get_embedding_function():
    """OpenAI 임베딩 함수 (01_tech_stack.md §2.3 확정).

    ChromaDB 기본 내장 함수(all-MiniLM-L6-v2, ONNX, 384차원)를 쓰지 않는 이유는
    첫 사용 시 모델 83MB를 내려받아 캐시하기 때문이다. Community Cloud는 재시작 시
    파일시스템이 초기화되어 이 다운로드가 매번 반복되고, cold start가 20~60초 발생한다.

    API 키가 없으면 None을 반환한다 — 호출측에서 RAG 없이 진행하도록 폴백한다.
    """
    if not OPENAI_API_KEY:
        return None
    return embedding_functions.OpenAIEmbeddingFunction(
        api_key=OPENAI_API_KEY, model_name=EMBEDDING_MODEL
    )


def get_collection(create: bool = True):
    """RAG 컬렉션 핸들. 인제스트와 검색이 반드시 동일한 임베딩 함수를 쓰도록 여기로 모은다.

    임베딩 함수를 만들 수 없거나(키 부재) 컬렉션 접근에 실패하면 None을 반환한다.
    """
    embedding_fn = get_embedding_function()
    if embedding_fn is None:
        return None

    client = get_chroma_client()
    try:
        if create:
            return client.get_or_create_collection(
                name=CHROMA_COLLECTION_NAME, embedding_function=embedding_fn
            )
        return client.get_collection(name=CHROMA_COLLECTION_NAME, embedding_function=embedding_fn)
    except Exception:
        return None


def reset_collection():
    """컬렉션을 비우고 새로 만든다. 인제스트 재실행 시 이전 벡터가 남지 않도록 한다."""
    embedding_fn = get_embedding_function()
    if embedding_fn is None:
        return None

    client = get_chroma_client()
    try:
        client.delete_collection(CHROMA_COLLECTION_NAME)
    except Exception:
        pass  # 컬렉션이 없으면 그대로 진행
    return client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME, embedding_function=embedding_fn
    )
