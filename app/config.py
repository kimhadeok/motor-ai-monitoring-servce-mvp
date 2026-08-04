"""중앙화된 설정값. CLAUDE.md 요구사항: 앱 동작에 영향을 주는 값은 하드코딩하지 않고 여기 모아둔다."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

try:
    import streamlit as st

    _SECRETS = st.secrets
except Exception:
    _SECRETS = {}


def get_secret(key: str, default: str | None = None) -> str | None:
    """st.secrets 우선, 없으면 환경변수(.env 포함)에서 조회.

    로컬 개발 환경처럼 .streamlit/secrets.toml 자체가 없는 경우 st.secrets 접근이
    예외를 던지므로(파일 부재와 키 부재를 구분하지 않음), 조용히 환경변수로 폴백한다.
    """
    try:
        if key in _SECRETS:
            return _SECRETS[key]
    except Exception:
        pass
    return os.getenv(key, default)


BASE_DIR = Path(__file__).resolve().parent.parent

# --- 경로 ---
DB_PATH = BASE_DIR / "data" / "app.db"
CHROMA_PERSIST_DIR = BASE_DIR / "data" / "chroma"
RAG_SOURCES_DIR = BASE_DIR / "data" / "rag_sources"
REPORT_TEMPLATE_DIR = BASE_DIR / "app" / "reports" / "templates"
REPORT_TEMPLATE_FILENAME = "report_template.html"

# --- API 키 ---
OPENAI_API_KEY = get_secret("OPENAI_API_KEY")

# --- 시간 윈도우 (02_architecture.md §4~5 확정값) ---
DB_RETENTION_HOURS = 48
SHORT_TERM_BUFFER_HOURS = 2
LONG_TERM_TREND_HOURS = 6
COOLDOWN_HOURS = 1

# --- 자동 갱신 (01_tech_stack.md §2.5 / 05_ui_screens.md §5-2, st.fragment run_every) ---
# 문서 미확정 — MVP 제안값
DASHBOARD_REFRESH_INTERVAL_SECONDS = 10

# --- 수집 주기 (02_architecture.md §2.1) ---
ALLOWED_COLLECTION_INTERVALS_SECONDS = (10, 20, 30)

# --- 통신 두절 판정 (03_state_event_logic.md §4.4 확정) ---
MISSED_CYCLES_THRESHOLD = 3

# --- 상태/심각도 (03_state_event_logic.md §1~2 확정) ---
METRIC_NAMES = ("temperature", "vibration", "current", "sound")
STATUS_LEVELS = ("NORMAL", "WARNING", "DANGER", "FAULT")
STATUS_SEVERITY_RANK = {"NORMAL": 0, "WARNING": 1, "DANGER": 2, "FAULT": 3}

# --- 상태별 색상 (05_ui_screens.md §5-3 확정, report_template.html과 통일) ---
STATUS_COLORS = {
    "NORMAL": "#16a34a",
    "WARNING": "#d97706",
    "DANGER": "#dc2626",
    "FAULT": "#1e293b",
}
STATUS_BG_COLORS = {
    "NORMAL": "#f0fdf4",
    "WARNING": "#fffbeb",
    "DANGER": "#fef2f2",
    "FAULT": "#f1f5f9",
}
BRAND_PRIMARY_COLOR = "#1e3a8a"
BRAND_PRIMARY_LIGHT_COLOR = "#3b82f6"

# --- 알림 채널 (04_database_schema.md §3.7 확정) ---
NOTIFICATION_CHANNELS = ("KAKAO_ALIMTALK", "SMS", "EMAIL")

# --- LLM 모델 (01_tech_stack.md §2.4 확정) ---
LLM_ROUTER_MODEL = "gpt-4o-mini"
LLM_REASONING_MODEL = "gpt-4o"
# 문서 미확정 — MVP 제안값 (RAG 인제스트/검색용, OpenAI 단일 프로바이더 유지 목적)
EMBEDDING_MODEL = "text-embedding-3-small"

# --- 리포트 세션 ID (06_report_spec.md §2.1/§4 확정) ---
REPORT_SESSION_ID_FORMAT = "motor_{motor_id}_{date}_{time}"  # 예: motor_MTR-001_20260803_171000

# --- 표시용 포맷 (05_ui_screens.md §3.2 목업 근거) ---
DISPLAY_TIMEZONE = "Asia/Seoul"
DISPLAY_DATETIME_FORMAT = "%y/%m/%d %H:%M"

# --- 보관 정책 배치 (04_database_schema.md §5-5) ---
# 문서 미확정 — MVP 제안값 (야간 실행 권장)
RETENTION_BATCH_CRON_HOUR = 3
