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
    card_status_css = "\n".join(
        f".motor-card.status-{status.lower()} {{ "
        f"--card-color: {color}; --card-bg: {STATUS_BG_COLORS[status]}; }}"
        for status, color in STATUS_COLORS.items()
    )
    gauge_status_css = "\n".join(
        f".metric-gauge.status-{status.lower()} .fill {{ background: {color}; }}"
        for status, color in STATUS_COLORS.items()
    )
    metric_status_css = "\n".join(
        f".metric-block.status-{status.lower()} {{ --metric-color: {color}; }}"
        for status, color in STATUS_COLORS.items()
    )
    chip_status_css = "\n".join(
        f".event-change .chip.status-{status.lower()} {{ "
        f"color: {color}; background: {STATUS_BG_COLORS[status]}; }}"
        for status, color in STATUS_COLORS.items()
    )

    # st.html을 쓰는 이유: 이 컴포넌트만 DOMPurify 허용 목록에 <style>을 명시적으로 추가한다.
    # st.markdown 경로는 <style> 처리가 보장되지 않는다.
    st.html(
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

        /* --- 모터 카드 (05 §3.2) --- */
        .motor-card {{
            --card-color: {STATUS_COLORS["NORMAL"]};
            --card-bg: {STATUS_BG_COLORS["NORMAL"]};
            position: relative; padding: 14px 16px 12px; border-radius: 10px;
            border: 1px solid #e2e8f0; border-top: 3px solid var(--card-color);
            background: #ffffff;
        }}
        {card_status_css}
        /* 이상 상태 카드는 배경까지 옅게 물들여 멀리서도 구분되게 한다 */
        .motor-card.status-warning, .motor-card.status-danger, .motor-card.status-fault {{
            background: var(--card-bg);
            box-shadow: 0 1px 6px color-mix(in srgb, var(--card-color) 22%, transparent);
        }}
        .motor-head {{
            display: flex; align-items: center; justify-content: space-between;
            gap: 8px; margin-top: 2px;
        }}
        .motor-name {{ font-size: 15px; font-weight: 700; color: #0f172a; }}
        .motor-meta {{ font-size: 11px; color: #64748b; margin-top: 3px; }}
        .motor-foot {{
            font-size: 11px; color: #94a3b8; margin-top: 12px;
        }}

        /* 지표 블록 — 모든 카드가 4개를 같은 순서로 담아 높이가 일정하다 */
        .metric-block {{ margin-top: 9px; }}
        .metric-row {{
            display: flex; align-items: baseline; justify-content: space-between;
            margin-bottom: 3px;
        }}
        .metric-name {{ font-size: 12px; color: #64748b; }}
        .metric-value {{ font-size: 14px; font-weight: 600; color: #475569; }}
        .metric-unit {{ font-size: 10px; font-weight: 500; color: #94a3b8; margin-left: 2px; }}
        /* 이상 지표만 색과 굵기로 끌어올린다 — 위치는 바꾸지 않는다 */
        .metric-block.abnormal .metric-name {{ font-weight: 700; color: var(--metric-color); }}
        .metric-block.abnormal .metric-value {{
            font-size: 18px; font-weight: 800; color: var(--metric-color);
        }}
        .metric-block.abnormal .metric-unit {{ color: var(--metric-color); }}
        {metric_status_css}

        /* 고장 임계를 100%로 둔 게이지. 눈금은 주의·위험 임계 위치 */
        .metric-gauge {{
            position: relative; height: 7px; border-radius: 4px;
            background: #eef2f7; overflow: hidden;
        }}
        .metric-gauge .fill {{
            position: absolute; inset-block: 0; left: 0; border-radius: 4px;
            background: var(--gauge-color, {STATUS_COLORS["NORMAL"]});
        }}
        .metric-gauge .tick {{
            position: absolute; inset-block: 0; width: 1px;
            background: rgba(255, 255, 255, 0.85);
        }}
        {gauge_status_css}
        /* 정상 게이지는 옅게 — 이상 지표가 먼저 눈에 들어와야 한다 */
        .metric-block:not(.abnormal) .metric-gauge .fill {{
            background: color-mix(in srgb, {STATUS_COLORS["NORMAL"]} 45%, #cbd5e1);
        }}

        /* 카드 하단 추이 — 정상 카드에도 넣어 높이를 맞춘다 */
        .metric-trend {{
            display: flex; align-items: center; gap: 6px;
            margin-top: 12px; padding-top: 10px; border-top: 1px dashed #e2e8f0;
        }}
        .metric-trend .trend-label {{
            font-size: 11px; font-weight: 600; color: #475569; white-space: nowrap;
        }}
        .metric-trend .sparkline {{ flex: 1 1 auto; min-width: 0; }}
        .metric-trend .trend-note {{ font-size: 11px; color: #64748b; white-space: nowrap; }}

        /* --- 이벤트 리스트 (05 §3.3 / §4.4) --- */
        .event-when {{ display: flex; flex-direction: column; line-height: 1.35; }}
        .event-when .rel {{ font-size: 13px; font-weight: 600; color: #334155; }}
        .event-when .abs {{ font-size: 10.5px; color: #94a3b8; }}

        .event-change {{ display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }}
        .event-change .metric-tag {{
            font-size: 11px; font-weight: 700; color: #475569;
            background: #f1f5f9; border-radius: 5px; padding: 1px 6px;
        }}
        /* 배지보다 작은 칩 — 한 줄에 이전/이후 두 개가 들어가야 한다 */
        .event-change .chip {{
            font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 9px;
            border: 1px solid currentColor;
        }}
        {chip_status_css}
        .event-change .arrow {{ font-size: 10px; font-weight: 700; }}
        .event-change .arrow.worse {{ color: {STATUS_COLORS["DANGER"]}; }}
        .event-change .arrow.recover {{ color: {STATUS_COLORS["NORMAL"]}; }}
        .event-change .arrow.flat {{ color: #94a3b8; }}

        .event-reason {{ font-size: 12px; color: #475569; line-height: 1.4; }}
        .event-reason.worse {{ color: {STATUS_COLORS["DANGER"]}; font-weight: 600; }}
        .event-reason.recover {{ color: {STATUS_COLORS["NORMAL"]}; }}

        /* --- 상단 헤더 (05 §5-4) — 사이드바 대신 일반 웹 서비스 형태 --- */
        .app-brand {{ display: flex; align-items: center; gap: 8px; }}
        .app-brand .icon {{ font-size: 22px; line-height: 1; }}
        .app-brand .name {{
            font-size: 19px; font-weight: 800; color: {BRAND_PRIMARY_COLOR};
            letter-spacing: -0.3px;
        }}
        .app-user {{
            display: flex; flex-direction: column; align-items: flex-end;
            line-height: 1.3; text-align: right;
        }}
        .app-user .company {{ font-size: 13px; font-weight: 700; color: #334155; }}
        .app-user .contact {{ font-size: 11px; color: #94a3b8; }}
        .app-header-rule {{
            height: 1px; margin: 10px 0 18px;
            background: linear-gradient(
                90deg,
                {BRAND_PRIMARY_COLOR} 0%,
                color-mix(in srgb, {BRAND_PRIMARY_COLOR} 15%, transparent) 45%,
                #e2e8f0 100%
            );
        }}

        /* --- 로그인 화면 (05 §2) --- */
        .login-hero {{ text-align: center; margin: 24px 0 22px; }}
        .login-hero .icon {{ font-size: 44px; line-height: 1; }}
        .login-hero h1 {{
            margin: 10px 0 6px; font-size: 30px; font-weight: 800;
            color: {BRAND_PRIMARY_COLOR}; letter-spacing: -0.5px;
        }}
        .login-hero .tagline {{ margin: 0; font-size: 14px; color: #64748b; }}

        .login-highlights {{
            display: flex; gap: 10px; margin-top: 26px;
            padding-top: 20px; border-top: 1px solid #e2e8f0;
        }}
        .login-highlights .item {{
            flex: 1 1 0; display: flex; flex-direction: column; align-items: center;
            gap: 3px; text-align: center;
        }}
        .login-highlights .icon {{ font-size: 20px; line-height: 1.2; }}
        .login-highlights .title {{ font-size: 12.5px; font-weight: 700; color: #334155; }}
        .login-highlights .desc {{ font-size: 10.5px; color: #94a3b8; line-height: 1.4; }}
        /* 설명 줄은 모든 지표에 있다(높이 균일). 정상은 회색, 이상만 상태색으로 강조 */
        .metric-note {{ font-size: 10.5px; color: #94a3b8; margin-top: 3px; }}
        .metric-block.abnormal .metric-note {{ color: var(--metric-color); font-weight: 600; }}
        </style>
        """
    )
