"""재사용 UI 조각. 스캐폴딩 단계는 최소 스텁만 제공 — 이후 05_ui_screens.md 기준으로 확장."""

import streamlit as st


def status_badge(status: str) -> None:
    st.markdown(
        f'<span class="status-badge status-{status.lower()}">{status}</span>',
        unsafe_allow_html=True,
    )


def motor_card(motor: dict) -> None:
    """05_ui_screens.md §3.2 모터별 카드. 스캐폴딩 단계: 레이아웃만."""
    with st.container(border=True):
        st.write(f"**{motor.get('motor_name', '')}**")
        status_badge(motor.get("status", "NORMAL"))
