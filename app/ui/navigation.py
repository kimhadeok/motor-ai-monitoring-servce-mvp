"""로그인 여부에 따라 노출 페이지를 동적으로 구성 (05_ui_screens.md §1).

클래식 pages/ 자동 사이드바 방식은 로그인 여부와 무관하게 모든 페이지가 나열되므로,
st.navigation/st.Page로 session_state.authenticated 값에 따라 페이지 목록 자체를 분기한다.
"""

from pathlib import Path

import streamlit as st

from app.auth.session import is_authenticated

_PAGES_DIR = Path(__file__).resolve().parent.parent / "pages"

# st.switch_page는 st.Page에 넘긴 것과 동일한 경로 문자열을 요구하므로 상수로 공유한다.
DASHBOARD_PAGE = str(_PAGES_DIR / "dashboard.py")
MOTOR_GRAPH_PAGE = str(_PAGES_DIR / "motor_graph.py")
MOTOR_STATUS_PAGE = str(_PAGES_DIR / "motor_status.py")
MOTOR_DETAIL_PAGE = str(_PAGES_DIR / "motor_detail.py")
ADMIN_PAGE = str(_PAGES_DIR / "admin.py")

# 상단 헤더 페이지 이동 내비에 노출할 메인 페이지 (키, 라벨, 경로).
# 모터 상세는 카드 클릭으로만 진입하는 하위 화면이라 내비에 넣지 않는다.
# 관리자는 맨 뒤에 둔다 — 매일 쓰는 감시 화면 셋과 성격이 달라 앞에 오면 동선을 흐린다.
HEADER_NAV_PAGES = (
    ("dashboard", "메인 대시보드", DASHBOARD_PAGE),
    ("graph", "모터 그래프", MOTOR_GRAPH_PAGE),
    ("status", "모터 현황", MOTOR_STATUS_PAGE),
    ("admin", "관리자", ADMIN_PAGE),
)


def run() -> None:
    if is_authenticated():
        pages = [
            st.Page(DASHBOARD_PAGE, title="메인 대시보드", default=True),
            st.Page(MOTOR_GRAPH_PAGE, title="모터 그래프"),
            st.Page(MOTOR_STATUS_PAGE, title="모터 현황"),
            st.Page(MOTOR_DETAIL_PAGE, title="모터 상세"),
            st.Page(ADMIN_PAGE, title="관리자"),
        ]
    else:
        pages = [st.Page(str(_PAGES_DIR / "login.py"), title="로그인", default=True)]

    # 사이드바를 쓰지 않는다 — 로그인 정보와 로그아웃은 상단 헤더가 담당하고,
    # 페이지 이동은 모터 카드의 [상세 보기]와 상세 페이지의 [← 대시보드]로 이뤄진다.
    navigation = st.navigation(pages, position="hidden")
    navigation.run()
