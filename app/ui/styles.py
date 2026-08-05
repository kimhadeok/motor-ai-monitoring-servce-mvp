"""상태별 색상 등 커스텀 CSS 삽입 헬퍼 (01_tech_stack.md §2.5 확정 방식)."""

import streamlit as st

from app.config import (
    DATA_FLOW_ANIMATION_SECONDS,
    MOTOR_CARD_BUTTON_PREFIX,
    MOTOR_CARD_ROW_GAP_PX,
    SPARKLINE_HEIGHT_PX,
)
from app.ui.theme import palette


def inject_global_styles() -> None:
    """전역 CSS 주입.

    모터 카드 클릭 영역(05 §3.2)이 기대하는 Streamlit DOM 구조는 다음과 같다.

        div[data-testid="stColumn"]
         └ div[data-testid="stVerticalBlock"]
            ├ div.stElementContainer               → div.motor-card        (카드 마크다운)
            └ div.stElementContainer.st-key-motorclick-{motor_id}          (투명 버튼)
               └ div.stButton > button

    카드와 버튼은 반드시 **형제**여야 한다. 사이에 `st.container`를 끼우면 래퍼가 한 겹
    더 생겨(`stLayoutWrapper`) 절대 위치의 기준점이 어긋난다.

    오버레이 규칙은 전부 `:has(.motor-card)`로 묶어 모터 카드 컬럼에만 적용한다. 범위를
    좁히지 않으면 상단 요약 타일과 이벤트 리스트의 컬럼까지 영향을 받아 화면이 깨진다.

    색상은 현재 테마(라이트/다크) 팔레트에서 가져온다 (§5-5).
    """
    p = palette()
    status_colors = p["status"]
    status_bg = p["status_bg"]
    brand = p["brand"]

    status_css = "\n".join(
        f".status-badge.status-{status.lower()} {{ "
        f"color: {color}; background-color: {status_bg[status]}; "
        f"border: 1px solid {color}; }}"
        for status, color in status_colors.items()
    )

    # 모터 카드의 흐름 색상은 대표 상태에 따라 달라지므로 CSS 변수로 받는다.
    flow_status_css = "\n".join(
        f".data-flow.status-{status.lower()} {{ --flow-color: {color}; }}"
        for status, color in status_colors.items()
    )
    card_status_css = "\n".join(
        f".motor-card.status-{status.lower()} {{ "
        f"--card-color: {color}; --card-bg: {status_bg[status]}; }}"
        for status, color in status_colors.items()
    )
    gauge_status_css = "\n".join(
        f".metric-gauge.status-{status.lower()} .fill {{ background: {color}; }}"
        for status, color in status_colors.items()
    )
    metric_status_css = "\n".join(
        f".metric-block.status-{status.lower()} {{ --metric-color: {color}; }}"
        for status, color in status_colors.items()
    )
    chip_status_css = "\n".join(
        f".event-change .chip.status-{status.lower()} {{ "
        f"color: {color}; background: {status_bg[status]}; }}"
        for status, color in status_colors.items()
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
        a.brand-link {{ color: {brand}; }}

        /* --- 05_ui_screens.md §3.2 모터 → API → AI Agent 데이터 흐름 --- */
        .data-flow {{
            --flow-color: {brand};
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
            font-size: 10px; color: {p["text_muted"]}; white-space: nowrap;
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

        /* --- 모터 카드 클릭 영역 (05 §3.2) — 구조 설명은 이 함수의 파이썬 주석 참고 --- */
        div[data-testid="stColumn"]:has(.motor-card) > div[data-testid="stVerticalBlock"] {{
            position: relative;
            /* 간격은 카드 바깥에 준다. margin은 요소 박스 밖이라 inset:0인 투명 버튼이
               덮지 않으므로, 카드 사이 빈 공간을 눌러도 상세로 넘어가지 않는다. */
            margin-bottom: {MOTOR_CARD_ROW_GAP_PX}px;
        }}
        div[data-testid="stColumn"]:has(.motor-card)
        .stElementContainer[class*="st-key-{MOTOR_CARD_BUTTON_PREFIX}"] {{
            position: absolute; inset: 0; z-index: 3; margin: 0;
        }}
        div[data-testid="stColumn"]:has(.motor-card)
        .stElementContainer[class*="st-key-{MOTOR_CARD_BUTTON_PREFIX}"] .stButton,
        div[data-testid="stColumn"]:has(.motor-card)
        .stElementContainer[class*="st-key-{MOTOR_CARD_BUTTON_PREFIX}"] button {{
            width: 100%; height: 100%; opacity: 0; cursor: pointer;
            border: none; background: transparent; padding: 0; min-height: 0;
        }}
        /* 클릭 가능하다는 신호 — 살짝 떠오르고 테두리가 상태색으로 바뀐다 */
        div[data-testid="stColumn"]:has(.motor-card) .motor-card {{
            transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.12s ease;
        }}
        div[data-testid="stColumn"]:has(.motor-card):hover .motor-card {{
            transform: translateY(-2px);
            border-color: var(--card-color);
            box-shadow: 0 4px 12px color-mix(in srgb, var(--card-color) 26%, transparent);
        }}
        div[data-testid="stColumn"]:has(.motor-card):hover .motor-foot .go {{
            color: var(--card-color);
        }}
        .motor-foot .go {{ float: right; font-weight: 700; color: {p["text_ghost"]}; }}
        @media (prefers-reduced-motion: reduce) {{
            div[data-testid="stColumn"]:has(.motor-card) .motor-card {{ transition: none; }}
            div[data-testid="stColumn"]:has(.motor-card):hover .motor-card {{ transform: none; }}
        }}

        /* --- 모터 카드 (05 §3.2) --- */
        .motor-card {{
            --card-color: {status_colors["NORMAL"]};
            --card-bg: {status_bg["NORMAL"]};
            position: relative; padding: 14px 16px 12px; border-radius: 10px;
            border: 1px solid {p["border"]}; border-top: 3px solid var(--card-color);
            background: {p["surface"]};
        }}
        {card_status_css}
        /* 이상 상태 카드는 배경만 옅게 물들여 구분한다.
           그림자를 주면 카드가 실제보다 커 보여 정상 카드와 크기가 달라 보인다. */
        .motor-card.status-warning, .motor-card.status-danger, .motor-card.status-fault {{
            background: var(--card-bg);
        }}
        /* 아래 높이들은 모두 고정이다. 카드가 5열로 좁아 모터명·설치위치가 모터마다 다른
           줄 수로 접히고, 이상 지표는 글꼴이 커져 행 높이가 달라진다. 그대로 두면 카드마다
           세로 길이가 어긋나 그리드가 들쭉날쭉해진다. */
        .motor-head {{
            display: flex; align-items: center; justify-content: space-between;
            gap: 8px; margin-top: 2px; height: 22px;
        }}
        .motor-name {{
            font-size: 15px; font-weight: 700; color: {p["text_strong"]}; line-height: 22px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .motor-head .status-badge {{ flex: 0 0 auto; }}
        /* 모델명 · 설치 위치 — 최대 두 줄로 잘라 높이를 고정한다 */
        .motor-meta {{
            font-size: 11px; color: {p["text_muted"]}; margin-top: 3px;
            height: 30px; line-height: 15px; overflow: hidden;
            display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
        }}
        .motor-foot {{
            font-size: 11px; color: {p["text_faint"]}; margin-top: 12px;
            height: 16px; line-height: 16px; white-space: nowrap; overflow: hidden;
        }}

        /* 지표 블록 — 모든 카드가 4개를 같은 순서로 담는다.
           행 높이를 고정해 이상 지표의 큰 글꼴이 아래를 밀어내지 않게 한다. */
        .metric-block {{ margin-top: 9px; }}
        .metric-row {{
            display: flex; align-items: baseline; justify-content: space-between;
            gap: 6px; margin-bottom: 3px; height: 21px;
        }}
        .metric-name {{
            font-size: 12px; color: {p["text_muted"]}; line-height: 21px;
            white-space: nowrap; flex: 0 0 auto;
        }}
        .metric-value {{
            font-size: 14px; font-weight: 600; color: {p["text"]}; line-height: 21px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .metric-unit {{ font-size: 10px; font-weight: 500; color: {p["text_faint"]}; margin-left: 2px; }}
        /* 이상 지표만 색과 굵기로 끌어올린다 — 위치는 바꾸지 않는다 */
        .metric-block.abnormal .metric-name {{ font-weight: 700; color: var(--metric-color); }}
        /* 글꼴은 키우되 line-height는 고정 행 높이를 그대로 써서 아래를 밀지 않는다 */
        .metric-block.abnormal .metric-value {{
            font-size: 18px; font-weight: 800; color: var(--metric-color); line-height: 21px;
        }}
        .metric-block.abnormal .metric-unit {{ color: var(--metric-color); }}
        {metric_status_css}

        /* 고장 임계를 100%로 둔 게이지. 눈금은 주의·위험 임계 위치 */
        .metric-gauge {{
            position: relative; height: 7px; border-radius: 4px;
            background: {p["border_soft"]}; overflow: hidden;
        }}
        .metric-gauge .fill {{
            position: absolute; inset-block: 0; left: 0; border-radius: 4px;
            background: var(--gauge-color, {status_colors["NORMAL"]});
        }}
        .metric-gauge .tick {{
            position: absolute; inset-block: 0; width: 1px;
            background: rgba(255, 255, 255, 0.85);
        }}
        {gauge_status_css}
        /* 정상 게이지는 옅게 — 이상 지표가 먼저 눈에 들어와야 한다 */
        .metric-block:not(.abnormal) .metric-gauge .fill {{
            background: color-mix(in srgb, {status_colors["NORMAL"]} 45%, {p["text_ghost"]});
        }}

        /* 카드 하단 추이 — 정상 카드에도 넣어 높이를 맞춘다 */
        .metric-trend {{
            display: flex; align-items: center; gap: 6px;
            margin-top: 12px; padding-top: 10px; border-top: 1px dashed {p["border"]};
            height: {SPARKLINE_HEIGHT_PX + 10}px;
        }}
        .metric-trend .trend-label {{
            font-size: 11px; font-weight: 600; color: {p["text"]}; white-space: nowrap;
        }}
        .metric-trend .sparkline {{ flex: 1 1 auto; min-width: 0; }}
        .metric-trend .trend-note {{ font-size: 11px; color: {p["text_muted"]}; white-space: nowrap; }}

        /* --- 이벤트 리스트 (05 §3.3 / §4.4) --- */
        .event-when {{ display: flex; flex-direction: column; line-height: 1.35; }}
        .event-when .rel {{ font-size: 13px; font-weight: 600; color: {p["text"]}; }}
        .event-when .abs {{ font-size: 10.5px; color: {p["text_faint"]}; }}

        .event-change {{ display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }}
        .event-change .metric-tag {{
            font-size: 11px; font-weight: 700; color: {p["text"]};
            background: {p["surface_muted"]}; border-radius: 5px; padding: 1px 6px;
        }}
        /* 배지보다 작은 칩 — 한 줄에 이전/이후 두 개가 들어가야 한다 */
        .event-change .chip {{
            font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 9px;
            border: 1px solid currentColor;
        }}
        {chip_status_css}
        .event-change .arrow {{ font-size: 10px; font-weight: 700; }}
        .event-change .arrow.worse {{ color: {status_colors["DANGER"]}; }}
        .event-change .arrow.recover {{ color: {status_colors["NORMAL"]}; }}
        .event-change .arrow.flat {{ color: {p["text_faint"]}; }}

        .event-reason {{ font-size: 12px; color: {p["text"]}; line-height: 1.4; }}
        .event-reason.worse {{ color: {status_colors["DANGER"]}; font-weight: 600; }}
        .event-reason.recover {{ color: {status_colors["NORMAL"]}; }}

        /* --- 상단 헤더 (05 §5-4) — 사이드바 대신 일반 웹 서비스 형태 --- */
        .app-brand {{ display: flex; align-items: center; gap: 8px; }}
        .app-brand .icon {{ font-size: 22px; line-height: 1; }}
        .app-brand .name {{
            font-size: 19px; font-weight: 800; color: {brand};
            letter-spacing: -0.3px;
        }}
        /* 로그인 정보 + 테마 안내를 오른쪽 정렬로 나란히 둔다 */
        .app-side {{
            display: flex; align-items: center; justify-content: flex-end;
            gap: 18px; flex-wrap: nowrap; min-width: 0;
        }}
        .app-user {{
            display: flex; flex-direction: column; align-items: flex-end;
            line-height: 1.3; text-align: right; min-width: 0;
        }}
        .app-user .company, .app-user .contact {{
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%;
        }}
        .app-user .company {{ font-size: 13px; font-weight: 700; color: {p["text"]}; }}
        .app-user .contact {{ font-size: 11px; color: {p["text_faint"]}; }}
        /* 현재 테마 안내 — 전환은 Streamlit 기본 메뉴가 맡는다 (05 §5-5) */
        .app-theme {{
            display: flex; flex-direction: column; align-items: flex-end;
            line-height: 1.3; text-align: right; cursor: help;
            flex: 0 0 auto; padding-left: 18px;
            border-left: 1px solid {p["border"]};
        }}
        .app-theme .now {{ font-size: 12px; font-weight: 600; color: {p["text_muted"]}; }}
        .app-theme .hint {{ font-size: 10px; color: {p["text_ghost"]}; white-space: nowrap; }}
        .app-header-rule {{
            height: 1px; margin: 10px 0 18px;
            background: linear-gradient(
                90deg,
                {brand} 0%,
                color-mix(in srgb, {brand} 15%, transparent) 45%,
                {p["border"]} 100%
            );
        }}

        /* --- 로그인 화면 (05 §2) --- */
        .login-hero {{ text-align: center; margin: 24px 0 22px; }}
        .login-hero .icon {{ font-size: 44px; line-height: 1; }}
        .login-hero h1 {{
            margin: 10px 0 6px; font-size: 30px; font-weight: 800;
            color: {brand}; letter-spacing: -0.5px;
        }}
        .login-hero .tagline {{ margin: 0; font-size: 14px; color: {p["text_muted"]}; }}

        .login-highlights {{
            display: flex; gap: 10px; margin-top: 26px;
            padding-top: 20px; border-top: 1px solid {p["border"]};
        }}
        .login-highlights .item {{
            flex: 1 1 0; display: flex; flex-direction: column; align-items: center;
            gap: 3px; text-align: center;
        }}
        .login-highlights .icon {{ font-size: 20px; line-height: 1.2; }}
        .login-highlights .title {{ font-size: 12.5px; font-weight: 700; color: {p["text"]}; }}
        .login-highlights .desc {{ font-size: 10.5px; color: {p["text_faint"]}; line-height: 1.4; }}
        /* 설명 줄은 모든 지표에 있다(높이 균일). 정상은 회색, 이상만 상태색으로 강조 */
        .metric-note {{
            font-size: 10.5px; color: {p["text_faint"]}; margin-top: 3px;
            height: 14px; line-height: 14px; white-space: nowrap; overflow: hidden;
        }}
        .metric-block.abnormal .metric-note {{ color: var(--metric-color); font-weight: 600; }}
        </style>
        """
    )
