"""현재 테마 판별 및 팔레트 조회. 05_ui_screens.md §5-5.

Streamlit은 테마 색을 CSS 변수로 내보내지 않고(emotion CSS-in-JS 기반), 런타임에 테마를
바꾸는 API도 제공하지 않는다. 따라서 사용자가 고른 테마는 `st.context.theme.type`으로
읽어와 우리 커스텀 CSS의 팔레트를 고르는 데만 쓴다. 선택 UI는 Streamlit 기본 메뉴가 맡는다.
"""

import streamlit as st

from app.config import DEFAULT_THEME, THEMES


def current_theme() -> str:
    """"light" 또는 "dark". 판별할 수 없으면 기본값.

    `st.context.theme`는 앱 첫 로드 직후나 테마 전환 직후에 이전 값을 줄 수 있다
    (Streamlit 이슈 #11920). 그 경우 다음 리런에서 바로잡힌다.
    """
    try:
        theme_type = st.context.theme.type
    except Exception:
        return DEFAULT_THEME
    return theme_type if theme_type in THEMES else DEFAULT_THEME


def palette() -> dict:
    """현재 테마의 색상 팔레트."""
    return THEMES[current_theme()]
