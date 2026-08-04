"""중앙화된 설정값. CLAUDE.md 요구사항: 앱 동작에 영향을 주는 값은 하드코딩하지 않고 여기 모아둔다."""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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

# --- 부트스트랩 (02_architecture.md §6.3) ---
# 데모 데이터는 앱 부팅 시 런타임 생성되므로, 동시 진입을 락/마커로 차단한다.
BOOTSTRAP_LOCK_PATH = BASE_DIR / "data" / ".ingest.lock"
BOOTSTRAP_MARKER_PATH = BASE_DIR / "data" / ".ingest_done"
BOOTSTRAP_LOCK_TIMEOUT_SECONDS = 120

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

# --- 상태 전이 확정 샘플 수 (02_architecture.md §2.3 핑퐁 방지 구현값) ---
# 측정값이 임계선 근처에서 흔들릴 때 전이가 난사되는 것을 막기 위해,
# 새 상태가 연속 N회 유지될 때만 전이로 확정한다.
TRANSITION_CONFIRM_SAMPLES = 3

# --- 상태/심각도 (03_state_event_logic.md §1~2 확정) ---
METRIC_NAMES = ("temperature", "vibration", "current", "sound")
STATUS_LEVELS = ("NORMAL", "WARNING", "DANGER", "FAULT")
STATUS_SEVERITY_RANK = {"NORMAL": 0, "WARNING": 1, "DANGER": 2, "FAULT": 3}

# 지표별 표시 라벨/단위 — 대시보드, 상세 페이지, 리포트가 공유한다.
METRIC_LABELS = {
    "temperature": "온도",
    "vibration": "진동",
    "current": "전류",
    "sound": "소음",
}
METRIC_UNITS = {
    "temperature": "°C",
    "vibration": "mm/s",
    "current": "A",
    "sound": "dB",
}

# 지표별 임계값 4구간 (normal_range, warning_range, danger_range, fault_range).
# 판정 규칙: 값 >= fault → FAULT, >= danger → DANGER, >= warning → WARNING, 그 외 NORMAL.
# 데모 데이터 시드와 런타임 상태 분류가 동일한 값을 사용한다 (04_database_schema.md §3.4 motor_thresholds).
METRIC_THRESHOLDS = {
    "temperature": (20.0, 60.0, 75.0, 90.0),
    "vibration": (0.0, 2.5, 4.0, 6.0),
    "current": (0.0, 15.0, 18.0, 22.0),
    "sound": (40.0, 75.0, 85.0, 95.0),
}

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
EMBEDDING_MODEL = "text-embedding-3-small"
# 리포트에 표시할 진단 모델 라벨 (06_report_spec.md §2.3 확정)
DIAGNOSIS_MODEL_LABEL = "GPT-4o 기반 진단 에이전트"

# --- RAG (01_tech_stack.md §2.3) ---
CHROMA_COLLECTION_NAME = "manuals_and_incidents"
RAG_TOP_K = 2
RAG_MAX_SOP_STEPS = 4
# RAG 이용 불가 시 마지막 폴백 문구 (02_architecture.md §2.2)
RAG_FALLBACK_SOP_STEP = "설비 안전 정지 후 담당자 육안 점검을 진행하십시오."

# --- 리포트 세션 ID (06_report_spec.md §2.1/§4 확정) ---
REPORT_SESSION_ID_FORMAT = "motor_{motor_id}_{date}_{time}"  # 예: motor_MTR-001_20260803_171000

# --- 표시용 포맷 (05_ui_screens.md §3.2 목업 근거) ---
DISPLAY_TIMEZONE = "Asia/Seoul"
DISPLAY_DATETIME_FORMAT = "%y/%m/%d %H:%M"
REPORT_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
REPORT_DATE_FORMAT = "%Y%m%d"
REPORT_TIME_FORMAT = "%H%M%S"

_DISPLAY_TZ = ZoneInfo(DISPLAY_TIMEZONE)


def to_display_tz(dt: datetime) -> datetime:
    """UTC(또는 tz-aware) datetime을 표시용 타임존으로 변환."""
    return dt.astimezone(_DISPLAY_TZ)


def format_display(dt: datetime, fmt: str = DISPLAY_DATETIME_FORMAT) -> str:
    """표시용 타임존 기준으로 포맷팅. 하드코딩된 UTC 오프셋 대신 이 함수를 사용한다."""
    return to_display_tz(dt).strftime(fmt)


# --- 보관 정책 배치 (04_database_schema.md §5-5) ---
# 문서 미확정 — MVP 제안값 (야간 실행 권장)
RETENTION_BATCH_CRON_HOUR = 3

# --- 데모 데이터 시드 (02_architecture.md §6) ---
# 앱 부팅 시 런타임 생성되는 시연용 데이터의 파라미터.
DEMO_ACCOUNT_PASSWORD = "demo1234!"
SEED_RNG_SEED = 20260804  # 고정 시드 — 실행마다 동일한 수치가 나오도록
SEED_TELEMETRY_HOURS = DB_RETENTION_HOURS  # 보관 범위 전체를 채운다
