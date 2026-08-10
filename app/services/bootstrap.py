"""데모 데이터 런타임 부트스트랩 (02_architecture.md §6 확정).

Streamlit Community Cloud는 재배포/재시작 시 로컬 파일시스템이 초기화된다. 시드 산출물을
git에 커밋하는 대신 앱 부팅 시 실행 환경에서 직접 생성해, 배포본이 항상 "지금 기준 최근
48시간" 데이터를 갖도록 한다.

**여기서 하는 일은 시간에 의존하는 데이터뿐이다 (2026-08-07 확정).** 정적 자산은 부팅에서
빠졌다 — RAG 벡터는 `scripts/build_knowledge.py`로 한 번 만들어 `data/chroma/`를 커밋하고,
고장모드 지식은 커밋된 JSON을 그때그때 읽는다. 리포트 HTML도 최초 열람 시 생성된다.
그 결과 부팅 경로에 OpenAI API 호출이 하나도 남지 않아, 키가 없어도 앱이 정상 기동한다.

동시 진입 차단이 중요하다. 시드는 기존 DB를 지우고 새로 만들 수 있으므로, 한 세션이
삭제하는 동안 다른 세션이 읽으면 깨진 상태를 보게 된다. 파일 락 + 완료 마커로 막는다.
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version

from app.config import (
    BOOTSTRAP_LOCK_PATH,
    BOOTSTRAP_LOCK_TIMEOUT_SECONDS,
    BOOTSTRAP_MARKER_PATH,
    DB_PATH,
    DEMO_DATA_MAX_AGE_HOURS,
    DIAGNOSIS_LLM_ENABLED,
    OPENAI_API_KEY,
    parse_utc,
)
from app.db.connection import connection_scope
from app.db.init_db import ensure_schema
from app.rag.ingest import count_ingested_chunks
from app.services.seeding import seed_demo_data

logger = logging.getLogger(__name__)


def _demo_data_is_fresh(conn) -> bool:
    """쓸 만한 데모 데이터가 이미 있는지. 존재 여부와 **신선도**를 함께 본다.

    모터 존재만 확인하면, 시드한 지 며칠 지나 최근 구간이 텅 빈 DB도 "있음"으로 판정된다.
    시드는 실행 시각 기준 최근 48시간을 채우므로(`services/seeding.py`), 앱을 오래 켜두거나
    다음 날 다시 열면 모터 그래프(6시간 창)와 카드 스파크라인이 "데이터 없음"이 된다.
    실제로 시드 6.6시간 뒤 그래프가 전부 비는 것을 확인했다.
    """
    if conn.execute("SELECT 1 FROM motors LIMIT 1").fetchone() is None:
        return False

    latest = conn.execute("SELECT MAX(time) FROM motor_telemetry").fetchone()[0]
    if latest is None:
        return False

    age = datetime.now(timezone.utc) - parse_utc(latest)
    return age <= timedelta(hours=DEMO_DATA_MAX_AGE_HOURS)


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "미설치"


def _log_environment() -> None:
    """배포본에서 무엇이 깔려 돌고 있는지 한 줄로 남긴다.

    배포 검증 항목(`remaining_work #5`)을 로그 한 줄로 판정하기 위한 것이다 —
    Python 버전이 선택한 값과 같은지, `chromadb`가 커밋된 persist 포맷과 같은 버전인지,
    키가 Secrets에 들어갔는지. **키 값 자체는 절대 남기지 않는다.** 설정 여부만 찍는다.
    """
    logger.info(
        "환경 | python=%s streamlit=%s chromadb=%s langgraph=%s | openai_key=%s diagnosis_llm=%s",
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        _package_version("streamlit"),
        _package_version("chromadb"),
        _package_version("langgraph"),
        "설정됨" if OPENAI_API_KEY else "없음",
        "on" if DIAGNOSIS_LLM_ENABLED else "off",
    )


def _log_summary(summary: dict) -> None:
    """부팅 결과 한 줄. Manage app 로그에서 grep 할 수 있게 형식을 고정한다."""
    if summary.get("error"):
        logger.error("부트스트랩 실패 | %s", summary["error"])
        return

    if summary.get("skipped_concurrent"):
        logger.info("부트스트랩 생략 | 다른 세션이 이미 완료함")
        return

    timings = summary.get("timings", {})
    detail = " ".join(f"{k}={v:.2f}s" for k, v in timings.items() if k != "total")

    if summary.get("seeded"):
        scale = (
            f"모터 {summary.get('motors', 0)}대 "
            f"텔레메트리 {summary.get('telemetry', 0):,}행 "
            f"상태로그 {summary.get('status_logs', 0)}건"
        )
    else:
        scale = "기존 데이터 재사용 (시드 생략)"

    logger.info(
        "부트스트랩 완료 | %s | reseeded_stale=%s | rag_ready=%s rag_chunks=%s | %.2fs (%s)",
        scale,
        summary.get("reseeded_stale", False),
        summary.get("rag_ready"),
        summary.get("rag_chunks"),
        timings.get("total", 0.0),
        detail,
    )

    # RAG 미적재는 화면에 아무 신호가 없다 — SOP가 키워드 폴백으로 조용히 떨어진다.
    # 배포본에서 이걸 알아챌 수 있는 유일한 지점이므로 WARNING으로 올린다.
    if not summary.get("rag_ready"):
        logger.warning(
            "RAG 벡터가 비어 있음 | SOP 조회가 키워드 폴백으로 동작합니다. "
            "커밋된 data/chroma/ 가 배포본에 들어왔는지, chromadb 버전이 빌드 시점과 같은지 확인하십시오."
        )


class _FileLock:
    """O_EXCL 기반 프로세스 간 락. 락을 못 얻으면 마커가 생길 때까지 대기한다."""

    def __init__(self, path, timeout: float):
        self.path = path
        self.timeout = timeout
        self.acquired = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self.acquired = True
                return self
            except FileExistsError:
                if BOOTSTRAP_MARKER_PATH.exists() or time.monotonic() > deadline:
                    # 다른 세션이 끝냈거나(마커 존재) 오래된 락이 남은 경우
                    if time.monotonic() > deadline:
                        self.path.unlink(missing_ok=True)
                        continue
                    return self
                time.sleep(0.2)

    def __exit__(self, *exc_info):
        if self.acquired:
            self.path.unlink(missing_ok=True)
        return False


def bootstrap_demo_data(force: bool = False) -> dict:
    """스키마 보장 → (필요 시) 데모 데이터 시드.

    이미 데이터가 있으면 시드를 건너뛴다(재실행 안전). `force=True`면 DB를 지우고 새로 만든다.
    각 단계 소요 시간을 함께 반환해 부팅 지연을 관측할 수 있게 한다.

    RAG 벡터는 여기서 만들지 않고 적재 여부만 확인한다. 비어 있으면 `rag_ready=False`로
    알려 SOP 조회가 키워드 폴백으로 동작 중임을 드러낸다.
    """
    summary: dict = {"seeded": False, "rag_chunks": 0, "rag_ready": False, "timings": {}}
    _log_environment()

    with _FileLock(BOOTSTRAP_LOCK_PATH, BOOTSTRAP_LOCK_TIMEOUT_SECONDS) as lock:
        if not lock.acquired:
            # 다른 세션이 부트스트랩 중이었고 그 사이 완료됨 — 스키마만 확인하고 반환
            ensure_schema()
            summary["skipped_concurrent"] = True
            _log_summary(summary)
            return summary

        try:
            # 데이터가 낡았으면 DB째로 지우고 다시 만든다. 남겨두고 덧붙이면 옛 텔레메트리와
            # 상태 로그가 섞여 "최근 48시간"이 두 구간으로 갈라진다.
            stale = False
            if not force and DB_PATH.exists():
                ensure_schema()
                with connection_scope() as conn:
                    stale = not _demo_data_is_fresh(conn)

            if force or stale:
                DB_PATH.unlink(missing_ok=True)
                BOOTSTRAP_MARKER_PATH.unlink(missing_ok=True)
                summary["reseeded_stale"] = stale

            started = time.monotonic()
            ensure_schema()
            summary["timings"]["schema"] = time.monotonic() - started

            with connection_scope() as conn:
                if not _demo_data_is_fresh(conn):
                    started = time.monotonic()
                    summary.update(seed_demo_data(conn))
                    summary["seeded"] = True
                    summary["timings"]["seed"] = time.monotonic() - started

            # 인제스트가 아니라 적재 확인이다. count()는 임베딩을 요구하지 않아 비용이 없다.
            started = time.monotonic()
            summary["rag_chunks"] = count_ingested_chunks()
            summary["rag_ready"] = summary["rag_chunks"] > 0
            summary["timings"]["rag_check"] = time.monotonic() - started

            BOOTSTRAP_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
            BOOTSTRAP_MARKER_PATH.touch()
        except Exception as exc:
            # 데이터 준비 실패로 앱 전체가 죽지 않도록 한다 (CLAUDE.md fallback 요구사항).
            # 마커를 만들지 않으므로 다음 기동에서 다시 시도한다.
            summary["error"] = f"{type(exc).__name__}: {exc}"

    summary["timings"]["total"] = sum(summary["timings"].values())
    _log_summary(summary)
    return summary


_cached_bootstrap = None


def ensure_demo_data() -> dict:
    """Streamlit 진입점용 래퍼 — 프로세스당 1회만 실행한다."""
    global _cached_bootstrap

    import streamlit as st  # CLI에서 streamlit 없이 쓰기 위한 지연 import

    if _cached_bootstrap is None:
        # 모듈 레벨 함수를 1회만 래핑한다. 호출마다 지역 함수를 새로 정의해 데코레이터를
        # 적용하면 캐시 키가 매번 달라질 수 있어 "프로세스당 1회" 보장이 깨진다.
        _cached_bootstrap = st.cache_resource(
            show_spinner="시연용 데이터를 준비하는 중입니다…"
        )(bootstrap_demo_data)

    return _cached_bootstrap()
