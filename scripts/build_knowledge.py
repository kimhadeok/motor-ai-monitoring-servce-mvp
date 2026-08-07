"""RAG 벡터 스토어 수동 구축 CLI.

`data/rag_sources/*.txt`를 임베딩해 `data/chroma/`에 적재한다. **한 번만 실행하면 된다.**
원본이 시간에 무관한 정적 텍스트이므로 앱 부팅 시 반복할 이유가 없고, 산출물을 커밋하면
Streamlit Community Cloud 배포본도 체크아웃으로 그대로 받는다 (2026-08-07 확정).

원본 텍스트를 수정했을 때만 다시 실행한다. 청크 수가 그대로인 채 내용만 바뀐 경우는
자동 감지되지 않으므로 `--force`를 쓴다.

**앱을 내린 상태에서 실행할 것.** Chroma의 persist 디렉터리는 다중 프로세스 동시 쓰기를
가정하지 않는다. 앱이 클라이언트를 연 채로 이 스크립트가 스토어를 갱신하면, 앱 쪽 검색이
조용히 실패해 SOP가 키워드 폴백으로 떨어진다(검증 중 실제로 재현). 재빌드 후에는 앱을
재기동해야 새 벡터가 반영된다.

실행:
    uv run python scripts/build_knowledge.py --dry-run   # 임베딩 없이 청크 구성만 확인
    uv run python scripts/build_knowledge.py             # 실제 적재
    uv run python scripts/build_knowledge.py --force     # 내용만 바뀐 경우 강제 재적재
"""

import argparse
import collections
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import (  # noqa: E402
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    EMBEDDING_MODEL,
    OPENAI_API_KEY,
    RAG_SOP_DOC_TYPES,
)
from app.rag.ingest import _load_chunks, ingest_rag_sources  # noqa: E402
from app.rag.knowledge import load_fault_knowledge  # noqa: E402


def _dir_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _print_composition(chunks) -> None:
    by_source: dict[str, int] = collections.Counter(m["source"] for _, _, m in chunks)
    by_type: dict[str, int] = collections.Counter(m.get("doc_type", "(없음)") for _, _, m in chunks)
    sop_eligible = sum(1 for _, _, m in chunks if m.get("doc_type") in RAG_SOP_DOC_TYPES)
    tagged = sum(1 for _, _, m in chunks if "fault_code" in m)
    chars = sum(len(t) for _, t, _ in chunks)

    print(f"  총 청크         {len(chunks)}개 ({chars:,}자)")
    print(f"  SOP 조회 대상   {sop_eligible}개  (doc_type ∈ {RAG_SOP_DOC_TYPES})")
    print(f"  고장모드 태그   {tagged}개")

    print("\n  파일별")
    for source, count in sorted(by_source.items()):
        print(f"    {count:3d}  {source}")

    print("\n  문서 유형별")
    for doc_type, count in sorted(by_type.items()):
        print(f"    {count:3d}  {doc_type}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 벡터 스토어를 구축한다 (수동 1회).")
    parser.add_argument(
        "--force",
        action="store_true",
        help="청크 수가 같아도 강제로 재임베딩한다 (원본 내용만 수정한 경우)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="임베딩 없이 청크 구성만 출력한다 (API 키 불필요)",
    )
    args = parser.parse_args()

    chunks = _load_chunks()
    if not chunks:
        print("!! 인제스트할 원본이 없습니다. data/rag_sources/*.txt 를 확인하세요.", file=sys.stderr)
        sys.exit(1)

    print("=== 청크 구성 ===")
    _print_composition(chunks)

    knowledge = load_fault_knowledge()
    print(
        f"\n  참조 지식      고장모드 {len(knowledge['fault_modes'])}종 / "
        f"지표 매핑 {len(knowledge['metric_fault_map'])}건 (JSON 직접 조회, 적재 불필요)"
    )

    if args.dry_run:
        print("\n--dry-run 이므로 임베딩하지 않고 종료합니다.")
        return

    if not OPENAI_API_KEY:
        print(
            "\n!! OPENAI_API_KEY가 없어 임베딩할 수 없습니다.\n"
            "   .env 또는 .streamlit/secrets.toml에 키를 넣고 다시 실행하세요.\n"
            "   (키 없이 구성만 확인하려면 --dry-run)",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\n=== 임베딩 적재 ({EMBEDDING_MODEL} → {CHROMA_COLLECTION_NAME}) ===")

    if args.force and CHROMA_PERSIST_DIR.exists():
        # Chroma의 delete_collection()은 세그먼트 디렉터리를 디스크에 남긴다. 재빌드마다
        # data_level0.bin(약 0.6MB)이 하나씩 쌓이는데, 산출물을 커밋하므로 git 히스토리에
        # 영구히 누적된다. --force는 처음부터 다시 만드는 것이므로 통째로 비운다.
        # 지연 생성이라 아직 Chroma 클라이언트가 열리기 전이어야 한다 (여기가 그 지점).
        stale = _dir_size_bytes(CHROMA_PERSIST_DIR)
        shutil.rmtree(CHROMA_PERSIST_DIR)
        print(f"  기존 스토어 제거 ({_format_size(stale)})")

    started = time.monotonic()
    ingested = ingest_rag_sources(force=args.force)
    elapsed = time.monotonic() - started

    if ingested == 0:
        print("!! 적재에 실패했습니다. API 키와 네트워크 상태를 확인하세요.", file=sys.stderr)
        sys.exit(1)

    size = _dir_size_bytes(CHROMA_PERSIST_DIR) if CHROMA_PERSIST_DIR.exists() else 0
    skipped = ingested == len(chunks) and elapsed < 0.2 and not args.force

    print(f"  적재 청크       {ingested}개{' (기존과 동일해 재임베딩 생략)' if skipped else ''}")
    print(f"  소요            {elapsed:.2f}초")
    print(f"  저장 위치       {CHROMA_PERSIST_DIR}  ({_format_size(size)})")

    print(
        "\n다음 단계\n"
        "  1) 앱이 떠 있었다면 재기동하세요 — 실행 중인 프로세스는 이전 스토어를 붙들고 있습니다.\n"
        "  2) 배포본에 반영하려면 산출물을 커밋하세요.\n"
        "       git add data/chroma data/rag_sources\n"
        "       git commit -m \"rebuild RAG vector store\""
    )


if __name__ == "__main__":
    main()
