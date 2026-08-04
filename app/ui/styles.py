"""상태별 색상 등 커스텀 CSS 삽입 헬퍼 (01_tech_stack.md §2.5 확정 방식)."""

import streamlit as st

from app.config import BRAND_PRIMARY_COLOR, STATUS_BG_COLORS, STATUS_COLORS


def inject_global_styles() -> None:
    status_css = "\n".join(
        f".status-badge.status-{status.lower()} {{ "
        f"color: {color}; background-color: {STATUS_BG_COLORS[status]}; "
        f"border: 1px solid {color}; }}"
        for status, color in STATUS_COLORS.items()
    )

    st.markdown(
        f"""
        <style>
        .status-badge {{
            display: inline-block; padding: 2px 10px; border-radius: 12px;
            font-size: 12px; font-weight: 700;
        }}
        {status_css}
        a.brand-link {{ color: {BRAND_PRIMARY_COLOR}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )
