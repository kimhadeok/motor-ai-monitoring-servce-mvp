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

from app.config import CHROMA_PERSIST_DIR

_client: chromadb.ClientAPI | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    return _client
