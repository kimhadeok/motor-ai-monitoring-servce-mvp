"""상태별 색상 등 커스텀 CSS 삽입 헬퍼 (01_tech_stack.md §2.5 확정 방식)."""

import streamlit as st

from app.config import (
    BRAND_PRIMARY_COLOR,
    DATA_FLOW_ANIMATION_SECONDS,
    STATUS_BG_COLORS,
    STATUS_COLORS,
)


def inject_global_styles() -> None:
    status_css = "\n".join(
        f".status-badge.status-{status.lower()} {{ "
        f"color: {color}; background-color: {STATUS_BG_COLORS[status]}; "
        f"border: 1px solid {color}; }}"
        for status, color in STATUS_COLORS.items()
    )

    # 모터 카드의 흐름 색상은 대표 상태에 따라 달라지므로 CSS 변수로 받는다.
    flow_status_css = "\n".join(
        f".data-flow.status-{status.lower()} {{ --flow-color: {color}; }}"
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

        /* --- 05_ui_screens.md §3.2 모터 → API → AI Agent 데이터 흐름 --- */
        .data-flow {{
            --flow-color: {BRAND_PRIMARY_COLOR};
            display: flex; align-items: center; justify-content: space-between;
            gap: 4px; margin: 4px 0 10px;
        }}
        {flow_status_css}
        .data-flow .node {{
            display: flex; flex-direction: column; align-items: center;
            gap: 2px; flex: 0 0 auto; min-width: 46px;
        }}
        .data-flow .node .icon {{
            font-size: 20px; line-height: 1;
            filter: drop-shadow(0 0 3px color-mix(in srgb, var(--flow-color) 45%, transparent));
        }}
        .data-flow .node .label {{
            font-size: 10px; color: #64748b; white-space: nowrap;
        }}
        /* 연결선 — 배경 그라데이션을 흘려보내 데이터가 이동하는 것처럼 보이게 한다 */
        .data-flow .link {{
            flex: 1 1 auto; height: 3px; border-radius: 2px; margin-bottom: 12px;
            background-image: linear-gradient(
                90deg,
                color-mix(in srgb, var(--flow-color) 18%, transparent) 0%,
                color-mix(in srgb, var(--flow-color) 18%, transparent) 45%,
                var(--flow-color) 50%,
                color-mix(in srgb, var(--flow-color) 18%, transparent) 55%,
                color-mix(in srgb, var(--flow-color) 18%, transparent) 100%
            );
            background-size: 250% 100%;
            animation: data-flow-move {DATA_FLOW_ANIMATION_SECONDS}s linear infinite;
        }}
        /* 두 번째 구간은 절반 늦게 출발해 모터 → API → Agent 순서로 흐르게 한다 */
        .data-flow .link.delayed {{
            animation-delay: {DATA_FLOW_ANIMATION_SECONDS / 2}s;
        }}
        @keyframes data-flow-move {{
            from {{ background-position: 150% 0; }}
            to {{ background-position: -150% 0; }}
        }}
        /* 애니메이션을 원치 않는 사용자 설정(OS 접근성)에서는 정지시킨다 */
        @media (prefers-reduced-motion: reduce) {{
            .data-flow .link {{ animation: none; background-position: 50% 0; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
