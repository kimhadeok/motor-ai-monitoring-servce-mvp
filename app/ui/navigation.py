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
MOTOR_DETAIL_PAGE = str(_PAGES_DIR / "motor_detail.py")


def run() -> None:
    if is_authenticated():
        pages = [
            st.Page(DASHBOARD_PAGE, title="메인 대시보드", default=True),
            st.Page(MOTOR_DETAIL_PAGE, title="모터 상세"),
        ]
    else:
        pages = [st.Page(str(_PAGES_DIR / "login.py"), title="로그인", default=True)]

    navigation = st.navigation(pages, position="hidden" if not is_authenticated() else "sidebar")
    navigation.run()
