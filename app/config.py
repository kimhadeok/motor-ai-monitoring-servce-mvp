"""중앙화된 설정값. CLAUDE.md 요구사항: 앱 동작에 영향을 주는 값은 하드코딩하지 않고 여기 모아둔다."""

import os
from datetime import datetime, timezone
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
# 최신 텔레메트리가 이 시간보다 오래되면 데모 데이터를 다시 만든다 (2026-08-07).
# 시드는 "실행 시각 기준 최근 48시간"을 채우므로 앱을 오래 켜두거나 다음 날 다시 열면
# 최근 구간이 비어 모터 그래프(6시간 창)와 카드 스파크라인이 "데이터 없음"이 된다.
# 모터 존재 여부만 보던 종전 판정으로는 이 상황을 잡지 못했다.
# 그래프 창(GRAPH_TREND_HOURS=6h)보다 넉넉히 작게 잡아 창이 비기 전에 갱신되게 한다.
DEMO_DATA_MAX_AGE_HOURS = 2

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

# --- 대시보드 상단 요약 (05_ui_screens.md §3.1) ---
# "밤사이 무슨 일이 있었나"에 답하는 창. 하루 단위로 보는 담당자 습관에 맞춘다.
DASHBOARD_RECENT_WINDOW_HOURS = 24

# --- 이벤트 리스트 (05_ui_screens.md §3.3 / §4.4 확정) ---
DASHBOARD_EVENT_LIST_LIMIT = 10  # 대시보드: 최근 최대 10개
DETAIL_EVENT_PAGE_SIZE = 20  # 상세 페이지: 페이지당 20개
# 대시보드 이벤트 목록에 실을 전이 결과 상태 (2026-08-07).
# 대시보드는 "지금 손대야 할 것"에 답하는 화면이라 NORMAL→WARNING 같은 관찰 단계 전이가
# 섞이면 조치가 필요한 건이 10칸 안에서 밀려난다. None이면 전체를 보여준다.
# 모터 상세(§4.4)는 이력 화면이므로 필터하지 않는다 — 어떻게 악화됐는지 과정이 보여야 한다.
DASHBOARD_EVENT_STATUSES = ("FAULT", "DANGER")
# 컬럼 폭 — 발생 일시 / (모터명) / 상태 변화 / 값 변화 / 발생 사유 / 리포트 버튼
# 값 변화 컬럼 추가 (2026-08-07): 상태만으로는 임계를 아슬하게 넘었는지 크게 뛰었는지 모른다.
# 폭은 실측 콘텐츠 필요량 기준 (1440 뷰포트, 전체 1270px):
#   발생일시 110 · 모터명 204 · 상태변화 161 · 값변화 107 · 발생사유 82.
# 종전에는 상태변화·발생사유에 253px씩 주고 있어 과할당이었다.
EVENT_COLUMN_WIDTHS_WITH_MOTOR = (1.4, 2.0, 1.9, 1.5, 1.9, 1.0)
EVENT_COLUMN_WIDTHS = (1.5, 2.0, 1.6, 2.0, 1.0)
# 값 변화의 소수점 자릿수. 두 값이 같게 찍히면 구분될 때까지 여기서 최대 3자리까지 늘린다
# (진동 5.97 → 6.03이 1자리에서는 "6.0 → 6.0"이 되어 임계를 넘은 사실이 사라진다).
EVENT_VALUE_DECIMALS = 2

# --- 모터 카드 그리드 (05_ui_screens.md §3.2) ---
# 문서 미확정 — MVP 제안값
MOTOR_CARD_COLUMNS = 5
# 대시보드에 그릴 모터 카드 수 (2026-08-07 임시, 개수 추후 확정 — remaining_work.md #7).
# COMP-001은 200대라 카드를 전부 그리면 렌더가 무겁다. 전체 목록은 '모터 현황' 페이지가 맡는다.
# None이면 제한 없이 전부 그린다.
DASHBOARD_MOTOR_CARD_LIMIT = 20
# 정비 완료 확인 필요 목록의 한 줄 카드 수 (05 §3.1) — 모터별 정보+버튼 카드를 나열한다.
MAINTENANCE_CONFIRM_COLUMNS = 4
# 카드 위를 덮는 투명 버튼의 key 접두사. Streamlit이 위젯 key를 DOM의
# `st-key-{key}` 클래스로 내보내므로 CSS(styles.py)가 이 클래스를 잡아 오버레이한다.
MOTOR_CARD_BUTTON_PREFIX = "motorclick-"
# 카드 행 사이 세로 간격(px). 클릭 버튼이 절대 위치라 카드 아래 여백이 사라지므로
# 카드 바깥(컬럼 블록의 margin)에 준다 — 간격이 클릭 영역에 포함되지 않게 하기 위함.
MOTOR_CARD_ROW_GAP_PX = 16
# 모터 → API → AI Agent 데이터 흐름 애니메이션 1주기 (초). 값이 작을수록 빠르게 흐른다.
DATA_FLOW_ANIMATION_SECONDS = 2.4
# 흐름 각 단계의 아이콘과 라벨
DATA_FLOW_NODES = (("⚙️", "모터"), ("🔌", "API"), ("🤖", "AI Agent"))

# 카드에 개별 게이지로 펼쳐 보여줄 상태 (나머지는 한 줄로 접는다)
CARD_HIGHLIGHT_STATUSES = ("WARNING", "DANGER", "FAULT")
# 카드 추이 스파크라인 — 장기 트렌드 창(6h)을 그대로 쓴다
TREND_WINDOW_HOURS = LONG_TERM_TREND_HOURS
TREND_BUCKETS = 24
SPARKLINE_WIDTH_PX = 132
SPARKLINE_HEIGHT_PX = 28
# 추세 판정 — 마지막 구간 평균이 첫 구간 평균 대비 이 비율 이상 변하면 상승/하락으로 본다
TREND_CHANGE_THRESHOLD = 0.03

# --- 리포트 뷰어 (05_ui_screens.md §3.3 인앱 표시) ---
REPORT_VIEWER_HEIGHT_PX = 600

# --- 모터 그래프 페이지 (05_ui_screens.md §3-graph, 재정리안 1페이지) ---
# 지표 4열(온도/진동/전류/소음)에 필터링된 모터의 추이 라인차트를 세로로 나열한다.
# 4지표를 곱하면 차트가 많아지므로, 표시 최대 수로 한 화면 렌더량을 제한한다.
GRAPH_MAX_MOTORS_OPTIONS = (10, 20)  # "표시 최대 수" 드롭다운 (→ 4×10 또는 4×20 차트)
GRAPH_DEFAULT_MAX_MOTORS = 10
# 상태 필터 드롭다운 순서 (ALL = 전체). 심각도 내림차순 (정렬·그룹 순서와 동일).
GRAPH_STATUS_FILTER_ORDER = ("ALL", "FAULT", "DANGER", "WARNING", "NORMAL")
GRAPH_TREND_HOURS = LONG_TERM_TREND_HOURS  # 라인차트가 보여줄 최근 창(6시간)
GRAPH_TREND_BUCKETS = 24  # 다운샘플 구간 수 — 포인트 마커가 촘촘하지 않게 6시간을 24구간(15분)으로

# --- 모터 현황 페이지 (05_ui_screens.md §3-status, 재정리안 2페이지) ---
# 라디오 버튼으로 그룹핑 방식을 고른다. "환경설정에 값 관리" = 이 config가 곧 환경설정이다.
GROUPING_MODE_STATUS = "status"
GROUPING_MODE_LOCATION = "location"
GROUPING_MODE_ISSUE = "issue"
# 표시 순서와 라벨. st.radio 옵션으로 그대로 쓴다. (확인 사항 정보를 맨 앞·기본으로 둔다)
GROUPING_MODES = {
    GROUPING_MODE_ISSUE: "확인 사항 정보",
    GROUPING_MODE_LOCATION: "위치별 정보",
    GROUPING_MODE_STATUS: "상태별 정보",
}
DEFAULT_GROUPING_MODE = GROUPING_MODE_ISSUE
# 상태별 그룹핑 순서 — 급한 것부터 위로 (심각도 내림차순)
STATUS_GROUP_ORDER = ("FAULT", "DANGER", "WARNING", "NORMAL")
# 확인사항 그룹핑 — 조치가 필요한 상태만 (NORMAL 제외)
ISSUE_GROUP_ORDER = ("FAULT", "DANGER", "WARNING")
# 한 줄에 카드 최대 몇 개. 실제 열 수는 화면 폭에 따라 자동으로 줄어든다.
# 10개에서 7개로 줄임 (2026-08-07): 10개면 카드 폭이 128px가 되어 지표 줄
# ("온도 82.2 °C · 진동 3.6 mm/s")이 24px 넘쳐 단위가 잘렸다. 200대 전체 400줄이 전부 잘림.
STATUS_CARDS_PER_ROW = 7
# 카드 폭(px). 이보다 좁아지지 않고, 화면이 좁아지면 대신 한 줄에 들어가는 카드 수가 준다.
# 170px = 지표 줄 필요 폭 + 좌우 패딩 22px + 테두리 2px. 내용 폭 147px 기준 실측 여유:
#   현재 데이터 최대 131px(여유 16) · 온도 3자리 "120.5" 137px(10) · 4개 지표 전부 3자리 142px(5).
# 모터명 최대 필요 폭도 147px라 말줄임 없이 전부 들어간다.
# 상한은 172px다 — 7개 행이 컨테이너(1440 뷰포트 기준 1270px)를 넘으면 6개로 떨어진다.
STATUS_CARD_MIN_WIDTH_PX = 170
STATUS_CARD_GRID_GAP_PX = 10
# 카드 위를 덮는 투명 클릭 버튼 key 접두사. st.button은 웹소켓으로 처리돼 페이지 리로드가
# 없으므로 로그인 세션이 유지된다(마크다운 앵커는 전체 리로드라 세션이 날아간다).
STATUS_CARD_BUTTON_PREFIX = "statusclick-"

# --- 수집 주기 (02_architecture.md §2.1) ---
ALLOWED_COLLECTION_INTERVALS_SECONDS = (10, 20, 30)

# --- 통신 두절 판정 (03_state_event_logic.md §4.4 확정) ---
MISSED_CYCLES_THRESHOLD = 3

# --- 상태 전이 확정 (02_architecture.md §2.3 핑퐁 방지 구현값) ---
# 새 상태가 이 시간만큼 연속으로 유지될 때만 전이로 확정한다. 샘플 "개수"가 아니라
# "시간" 기준인 이유: 수집 주기가 모터마다 10/20/30초로 달라, 개수 기준이면 확정까지
# 걸리는 시간이 모터마다 3배씩 차이 난다.
TRANSITION_CONFIRM_SECONDS = 300

# 회복 방향 이력폭(deadband). 상위 상태로 올라갈 때는 임계값을 그대로 쓰지만, 내려올 때는
# 진입 임계보다 이 비율만큼 더 낮아져야 회복으로 인정한다. 임계선 근처에서 값이 미세하게
# 흔들리는 구간(느린 램프 + 노이즈)에서 전이가 왕복 발생하는 것을 막는 표준적인 방법이다.
TRANSITION_DEADBAND_RATIO = 0.05

# --- 상태/심각도 (03_state_event_logic.md §1~2 확정) ---
METRIC_NAMES = ("temperature", "vibration", "current", "sound")
STATUS_LEVELS = ("NORMAL", "WARNING", "DANGER", "FAULT")
STATUS_SEVERITY_RANK = {"NORMAL": 0, "WARNING": 1, "DANGER": 2, "FAULT": 3}
# 대시보드 상단에서 "주의 이상"으로 집계하는 상태 (05_ui_screens.md §3.1 — NORMAL 제외)
ATTENTION_STATUSES = ("WARNING", "DANGER", "FAULT")
# 상태의 한글 표기 — 알림 문구·필터 안내 등 사용자에게 보이는 글에 쓴다.
STATUS_KOREAN_LABELS = {
    "NORMAL": "정상",
    "WARNING": "주의",
    "DANGER": "위험",
    "FAULT": "고장",
}

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

# 지표 → motor_telemetry의 상태 컬럼명 (04_database_schema.md §3.5).
# 리포트 컨텍스트와 진단 근거 계산이 함께 쓴다.
METRIC_STATUS_COLUMNS = {
    "temperature": "temp_status",
    "vibration": "vib_status",
    "current": "current_status",
    "sound": "sound_status",
}

# 추이를 "상승/하락"으로 부를 최소 변화율. 이보다 작으면 "유지"로 본다.
# 센서 노이즈를 추세로 오독해 리포트가 없는 경향을 단언하는 것을 막는다.
TREND_SIGNIFICANT_RATIO = 0.03

# 지표별 임계값 4구간 (normal_range, warning_range, danger_range, fault_range).
# 판정 규칙: 값 >= fault → FAULT, >= danger → DANGER, >= warning → WARNING, 그 외 NORMAL.
# 데모 데이터 시드와 런타임 상태 분류가 동일한 값을 사용한다 (04_database_schema.md §3.4 motor_thresholds).
METRIC_THRESHOLDS = {
    "temperature": (20.0, 60.0, 75.0, 90.0),
    "vibration": (0.0, 2.5, 4.0, 6.0),
    "current": (0.0, 15.0, 18.0, 22.0),
    "sound": (40.0, 75.0, 85.0, 95.0),
}

# --- 상태별 색상 (05_ui_screens.md §5-3, 2026-08-07 재정리) ---
# 라이트 기준값. 리포트 템플릿(HTML/PDF)은 항상 흰 배경이므로 이 값을 그대로 쓴다.
#
# 녹색 → 앰버 → 주황 → 빨강의 단조 증가 램프. 심각도가 올라갈수록 색도 세진다.
# 종전에는 FAULT가 슬레이트(#1e293b)라 가장 심각한 상태가 가장 약해 보였고, 그 탓에
# 배너는 배경을 채우고, 요약 타일은 FAULT 톤을 빼고, 지표 텍스트는 색을 따로 두는 식의
# 우회가 세 군데 생겼다. 팔레트를 바로잡아 그 우회들을 전부 없앴다.
#
# "노랑" 대신 앰버를 쓰는 이유: 순수 노랑(#eab308)은 흰 배경 대비가 1.92:1로 글자로
# 읽히지 않는다. 읽히는 노랑(#a16207)은 올리브·갈색으로 보여 노랑 구실을 못 한다.
STATUS_COLORS = {
    "NORMAL": "#16a34a",
    "WARNING": "#d97706",
    "DANGER": "#ea580c",
    "FAULT": "#dc2626",
}
STATUS_BG_COLORS = {
    "NORMAL": "#f0fdf4",
    "WARNING": "#fffbeb",
    "DANGER": "#fff7ed",
    "FAULT": "#fef2f2",
}

BRAND_PRIMARY_COLOR = "#1e3a8a"
BRAND_PRIMARY_LIGHT_COLOR = "#3b82f6"

# --- 테마 팔레트 (05_ui_screens.md §5-5) ---
# Streamlit은 테마 색을 CSS 변수로 노출하지 않고(emotion CSS-in-JS), 런타임에 테마를
# 바꾸는 API도 없다. 그래서 `st.context.theme.type`으로 현재 테마를 읽어 여기서 팔레트를
# 골라 CSS를 만든다. 사용자가 테마를 고르는 UI는 Streamlit 기본 메뉴(⋮ → Settings)다.
THEMES = {
    "light": {
        "surface": "#ffffff",  # 카드 배경
        "surface_muted": "#f1f5f9",  # 태그·칩 배경
        "border": "#e2e8f0",
        "border_soft": "#eef2f7",  # 게이지 트랙, 점선 구분
        "text_strong": "#0f172a",  # 모터명, 지표 값
        "text": "#334155",
        "text_muted": "#64748b",  # 설명, 라벨
        "text_faint": "#94a3b8",  # 보조 캡션
        "text_ghost": "#cbd5e1",  # 비활성 안내
        "brand": BRAND_PRIMARY_COLOR,
        "status": STATUS_COLORS,
        "status_bg": STATUS_BG_COLORS,
        # 모터 그래프 지표별 라인 색 — 4개 지표 열을 색으로 구분한다. 상태색(주황/빨강/짙은색)과
        # 겹치지 않는 파랑/보라/청록/자홍 계열로 골라 임계선(상태색)과 헷갈리지 않게 한다.
        "metric_chart": {
            "temperature": "#2563eb",
            "vibration": "#7c3aed",
            "current": "#0891b2",
            "sound": "#c026d3",
        },
    },
    "dark": {
        "surface": "#111a2b",
        "surface_muted": "#1c2739",
        "border": "#243347",
        "border_soft": "#1c2739",
        "text_strong": "#f1f5f9",
        "text": "#cbd5e1",
        "text_muted": "#94a3b8",
        "text_faint": "#64748b",
        "text_ghost": "#475569",
        # 남색 브랜드색은 어두운 배경에서 읽히지 않아 밝은 파랑으로 대체한다.
        "brand": "#60a5fa",
        # 상태색도 채도를 낮추고 밝기를 올려야 어두운 배경에서 대비가 확보된다.
        # 라이트와 같은 녹색 → 앰버 → 주황 → 빨강 램프. 네 색 모두 배경(#111a2b) 대비
        # 6:1 이상이라 텍스트로 써도 읽힌다(실측).
        "status": {
            "NORMAL": "#4ade80",
            "WARNING": "#fbbf24",
            "DANGER": "#fb923c",
            "FAULT": "#f87171",
        },
        "status_bg": {
            "NORMAL": "#0f2417",
            "WARNING": "#2a2010",
            "DANGER": "#2a1a0e",
            "FAULT": "#2b1414",
        },
        # 어두운 배경에서 읽히도록 밝은 파랑/보라/청록/자홍으로.
        "metric_chart": {
            "temperature": "#60a5fa",
            "vibration": "#c084fc",
            "current": "#22d3ee",
            "sound": "#e879f9",
        },
    },
}
DEFAULT_THEME = "light"
# 헤더에 현재 테마와 변경 위치를 알리는 문구. 앱에서 테마를 바꾸는 API가 없어(위 주석 참고)
# 안내만 하고, 실제 전환은 Streamlit 기본 메뉴가 처리한다.
THEME_LABELS = {"light": ("☀️", "라이트"), "dark": ("🌙", "다크")}
THEME_HINT = "⋮ 설정에서 변경"
THEME_HINT_TOOLTIP = "우측 상단 ⋮ → Settings → Choose app theme 에서 시스템/라이트/다크를 고를 수 있습니다."

# --- 서비스 소개 (05_ui_screens.md §2 로그인 화면) ---
# 고객이 서비스를 처음 마주하는 화면이라 "무엇을 해주는 서비스인지"가 드러나야 한다.
SERVICE_NAME = "모터 AI 모니터링"
SERVICE_ICON = "⚙️"
SERVICE_TAGLINE = "설비 이상을 미리 감지하고, AI가 원인과 조치를 진단합니다"
SERVICE_HIGHLIGHTS = (
    ("📡", "실시간 감시", "온도 · 진동 · 전류 · 소음"),
    ("🤖", "AI 진단", "원인 · 연쇄 영향 · 방치 시 결과"),
    ("📄", "리포트 자동 생성", "정비 절차(SOP)까지 포함"),
)

# --- 알림 채널 (04_database_schema.md §3.7 확정) ---
NOTIFICATION_CHANNELS = ("KAKAO_ALIMTALK", "SMS", "EMAIL")

# --- LLM 모델 (01_tech_stack.md §2.4 확정) ---
LLM_ROUTER_MODEL = "gpt-4o-mini"
LLM_REASONING_MODEL = "gpt-4o"
EMBEDDING_MODEL = "text-embedding-3-small"
# 리포트에 표시할 진단 모델 라벨 (06_report_spec.md §2.3 확정)
DIAGNOSIS_MODEL_LABEL = "GPT-4o 기반 진단 에이전트"
# 규칙 기반 폴백으로 생성했을 때의 라벨 (2026-08-10 확정).
# 호출하지 않은 모델명을 리포트에 적으면 담당자가 LLM 생성물로 오독한다 — 06 §2.3이 지적한
# "측정하지 않은 것을 단언하는 진단"과 같은 문제이므로 표기를 실제 생성 경로와 일치시킨다.
DIAGNOSIS_FALLBACK_MODEL_LABEL = "규칙 기반 진단 (LLM 미사용)"

# --- 진단 에이전트 (app/agents/diagnosis_agent.py, 2026-08-10) ---
# 오프라인 시연·폴백 검증용 강제 오프 스위치. 끄면 LLM을 호출하지 않고 규칙 기반으로 간다.
# 키가 없을 때도 자동으로 같은 경로를 탄다.
DIAGNOSIS_LLM_ENABLED = str(get_secret("DIAGNOSIS_LLM_ENABLED", "true")).strip().lower() not in (
    "false",
    "0",
    "no",
)
# 같은 이벤트에는 같은 진단이 나와야 담당자가 리포트를 근거로 삼을 수 있다.
DIAGNOSIS_LLM_TEMPERATURE = 0
# 실측 3.69초(gpt-4o structured output, 2026-08-10) 기준 3배 여유.
# 재시도까지 소진하면 최악 약 24초 뒤 규칙 기반으로 떨어진다 — 사용자가 스피너 앞에서
# 기다리는 시간이므로 이 두 값을 올릴 때는 첫 열람 대기 시간을 함께 따져야 한다.
DIAGNOSIS_LLM_TIMEOUT_SECONDS = 12
DIAGNOSIS_LLM_MAX_RETRIES = 1
# 연쇄 영향 항목 수 상한. 리포트 3페이지(AI 진단)의 실측 여유는 451px이므로(06 §3.1)
# 항목이 무한정 늘면 페이지가 밀린다.
DIAGNOSIS_MAX_CHAINED_EFFECTS = 3
# 리포트 1건 생성 예상 소요(초) — SOP 임베딩 0.3초 + 진단 LLM 3.7초 실측 기준.
# `scripts/seed_data.py --with-reports`가 시작 전 예상 시간을 안내하는 데만 쓴다.
REPORT_GENERATION_SECONDS_PER_ITEM = 4.0

# --- RAG (01_tech_stack.md §2.3) ---
CHROMA_COLLECTION_NAME = "manuals_and_incidents"
RAG_TOP_K = 2
RAG_MAX_SOP_STEPS = 4
# RAG 이용 불가 시 마지막 폴백 문구 (02_architecture.md §2.2)
RAG_FALLBACK_SOP_STEP = "설비 안전 정지 후 담당자 육안 점검을 진행하십시오."

# 인제스트 원본 파일별 문서 유형. 청크 메타데이터로 실려 SOP 조회 시 필터로 쓰인다.
#   manual     — 제조사 매뉴얼/정비 절차
#   incident   — 과거 장애 이력 및 실제 고장 사례
#   methodology— 신호 분석·판정 방법론 (근거 설명용, 정비 절차가 아님)
# 여기 없는 파일은 doc_type을 달지 않으며, 그 경우 SOP 조회 대상에서 제외된다.
RAG_SOURCE_DOC_TYPES = {
    "manufacturer_manual_sample.txt": "manual",
    "pdm_fault_modes.txt": "manual",
    "past_incident_sample.txt": "incident",
    "motorsense_incident_cases.txt": "incident",
    "pdm_signal_analysis.txt": "methodology",
    "maintenance_taxonomy.txt": "methodology",
}
# SOP 조회 대상 문서 유형. methodology를 빼는 이유는 "이상 대응 정비 절차" 질의에
# 방법론 설명이 걸리면 실행 가능한 조치가 아닌 문장이 SOP로 나가기 때문이다.
RAG_SOP_DOC_TYPES = ("manual", "incident")
# 질의문 보강 및 리포트 노출에 쓸 의심 고장모드 최대 개수
RAG_FAULT_LOOKUP_LIMIT = 3
# 질의문 보강에 쓸 relevance 상한 (1=주지표, 2=보조, 3=참고).
# 3까지 넣으면 전류 조회에 "축 정렬 불량"이 섞여 전기적 고장 절차를 밀어낸다.
# 리포트 노출은 이 제한을 받지 않는다 — 참고 수준도 담당자에겐 정보가 된다.
RAG_FAULT_QUERY_MAX_RELEVANCE = 2

# --- 참조 지식 (2026-08-07 확정) ---
# 지표 → 고장모드 → 부품 매핑은 시간에 무관한 정적 데이터(26행)이고 런타임 테이블과
# 조인할 지점이 없어 DB에 넣지 않는다. 커밋된 JSON을 app/rag/knowledge.py가 직접 읽는다.
KNOWLEDGE_DIR = BASE_DIR / "data" / "knowledge"
FAULT_KNOWLEDGE_FILE = "fault_modes.json"
# 징후 발생부터 실제 고장까지의 여유 시간대 표시 문구.
# MotorSense 제품소개서 p4의 진동(Months) → 소음(Weeks) → 열/연기(Days) → 고장 체인.
FAULT_LEAD_TIME_LABELS = {
    "MONTHS": "수개월 여유",
    "WEEKS": "수주 내 점검",
    "DAYS": "수일 내 조치",
}
# 정렬용 긴급도 (작을수록 급함). 리포트의 의심 고장 모드는 이 순서로 노출한다 —
# 담당자가 먼저 봐야 할 것은 관련도가 아니라 남은 대응 시간이다.
# 값이 없는 고장모드는 뒤로 보낸다.
FAULT_LEAD_TIME_URGENCY = {"DAYS": 0, "WEEKS": 1, "MONTHS": 2}
# 해당 지표와의 연관 강도 표시 문구 (metric_fault_map.relevance).
# 긴급도 순으로 정렬하면 보조 연관 고장이 주요 연관 고장보다 위에 올 수 있으므로,
# 읽는 사람이 그 차이를 알 수 있도록 리포트에 함께 노출한다.
FAULT_RELEVANCE_LABELS = {1: "주요 연관", 2: "보조 연관", 3: "참고"}

# --- 리포트 세션 ID (06_report_spec.md §2.1/§4 확정) ---
REPORT_SESSION_ID_FORMAT = "motor_{motor_id}_{date}_{time}"  # 예: motor_MTR-001_20260803_171000

# --- 표시용 포맷 (05_ui_screens.md §3.2 목업 근거) ---
DISPLAY_TIMEZONE = "Asia/Seoul"
DISPLAY_DATETIME_FORMAT = "%y/%m/%d %H:%M"
SUMMARY_DATE_FORMAT = "%Y-%m-%d"  # 대시보드 상단 요약의 날짜 표기 (05 §3.1)
REPORT_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
REPORT_DATE_FORMAT = "%Y%m%d"
REPORT_TIME_FORMAT = "%H%M%S"

# DB에 저장되는 시각 포맷 (schema.sql의 strftime('%Y-%m-%dT%H:%M:%fZ','now')와 동일)
DB_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

_DISPLAY_TZ = ZoneInfo(DISPLAY_TIMEZONE)


def parse_utc(value: str) -> datetime:
    """DB에 저장된 ISO8601 UTC 문자열을 tz-aware datetime으로 변환."""
    return datetime.strptime(value, DB_DATETIME_FORMAT).replace(tzinfo=timezone.utc)


def to_display_tz(dt: datetime) -> datetime:
    """UTC(또는 tz-aware) datetime을 표시용 타임존으로 변환."""
    return dt.astimezone(_DISPLAY_TZ)


def format_display(dt: datetime, fmt: str = DISPLAY_DATETIME_FORMAT) -> str:
    """표시용 타임존 기준으로 포맷팅. 하드코딩된 UTC 오프셋 대신 이 함수를 사용한다."""
    return to_display_tz(dt).strftime(fmt)


def format_relative(dt: datetime) -> str:
    """"5분 전"처럼 현재 기준 경과 시간. 하루가 넘으면 날짜로 표기한다.

    운영 화면에서는 절대 시각보다 "얼마나 최근인가"가 먼저 읽혀야 한다.
    """
    seconds = (datetime.now(timezone.utc) - dt).total_seconds()
    if seconds < 60:
        return "방금 전"
    if seconds < 3600:
        return f"{int(seconds // 60)}분 전"
    if seconds < 86400:
        return f"{int(seconds // 3600)}시간 전"
    if seconds < 86400 * 7:
        return f"{int(seconds // 86400)}일 전"
    return format_display(dt, SUMMARY_DATE_FORMAT)


# --- 보관 정책 배치 (04_database_schema.md §5-5) ---
# 문서 미확정 — MVP 제안값 (야간 실행 권장)
RETENTION_BATCH_CRON_HOUR = 3

# --- 데모 데이터 시드 (02_architecture.md §6) ---
# 앱 부팅 시 런타임 생성되는 시연용 데이터의 파라미터.
DEMO_ACCOUNT_PASSWORD = "demo1234!"
# 로그인 폼에 데모 계정을 미리 채워둘지 여부. 시연·개발 편의용이며 실제 서비스에서는 끈다.
PREFILL_DEMO_CREDENTIALS = True
SEED_RNG_SEED = 20260804  # 고정 시드 — 실행마다 동일한 수치가 나오도록
SEED_TELEMETRY_HOURS = DB_RETENTION_HOURS  # 보관 범위 전체를 채운다

# --- 대량 시드 (재정리안: COMP-001 200대) ---
# 큐레이션된 소수 모터로는 그래프 페이지의 세로 스크롤과 현황 페이지의 그룹핑·10열 배치를
# 시연할 수 없어, 한 회사를 실제 규모(200대)로 채운다. 기존 큐레이션 모터는 보존하고
# 부족분만 프로그램 생성한다.
SEED_BULK_COMPANY = "COMP-001"
SEED_BULK_MOTOR_TOTAL = 200  # 해당 회사의 목표 총 대수 (기존 큐레이션 10대 포함)
# 대량 모터의 수집 주기(초). 200대 × 48h를 10초 주기로 채우면 텔레메트리가 수백만 행이 되어
# 부팅/DB가 감당하기 어렵다. 라인차트는 어차피 구간 평균으로 다운샘플하므로 300초로도 충분하다.
SEED_BULK_INTERVAL_SECONDS = 300
# 생성 모터의 위치 풀 — 위치별 그룹핑에서 여러 그룹이 나오도록 다양하게 둔다.
# SEED_BULK_COMPANY(COMP-001 = 제1공장)에 속하므로 전부 제1공장 위치로 통일한다.
SEED_LOCATION_POOL = (
    "제1공장 지하 1층 기계실",
    "제1공장 1층 펌프실",
    "제1공장 1층 유틸리티실",
    "제1공장 2층 공조실",
    "제1공장 2층 기계실",
    "제1공장 3층 도장실",
    "제1공장 생산라인 A",
    "제1공장 생산라인 B",
    "제1공장 생산라인 C",
    "제1공장 생산라인 D",
    "제1공장 옥상",
    "제1공장 유틸리티동",
)
# 생성 모터의 모델 풀 (kW·극수 조합)
SEED_MODEL_POOL = (
    "HYUN-7.5KW-4P",
    "HYUN-11KW-4P",
    "HYUN-15KW-4P",
    "HYUN-15KW-6P",
    "HYUN-18KW-4P",
    "HYUN-22KW-4P",
    "HYUN-22KW-6P",
    "HYUN-30KW-4P",
    "HYUN-37KW-4P",
    "HYUN-45KW-4P",
)
# 생성 모터의 설비 종류 풀 (모터명 생성용)
SEED_EQUIPMENT_POOL = (
    "메인 송풍기",
    "냉각펌프",
    "급수펌프",
    "배기 블로워",
    "공기압축기",
    "컨베이어 구동모터",
    "원심분리기 모터",
    "냉각탑 팬모터",
    "집진기 흡입팬",
    "순환팬",
)
# 생성 190대 중 목표 상태 분포 (나머지는 NORMAL). 상태별/확인사항 그룹핑이 의미 있게 보이도록.
SEED_BULK_STATUS_TARGETS = {"FAULT": 4, "DANGER": 12, "WARNING": 30}
