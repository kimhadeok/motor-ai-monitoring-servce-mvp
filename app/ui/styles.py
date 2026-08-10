"""상태별 색상 등 커스텀 CSS 삽입 헬퍼 (01_tech_stack.md §2.5 확정 방식)."""

import streamlit as st

from app.config import (
    DATA_FLOW_ANIMATION_SECONDS,
    MOTOR_CARD_BUTTON_PREFIX,
    MOTOR_CARD_ROW_GAP_PX,
    SPARKLINE_HEIGHT_PX,
    STATUS_CARD_BUTTON_PREFIX,
    STATUS_CARD_GRID_GAP_PX,
    STATUS_CARD_MIN_WIDTH_PX,
    STATUS_CARDS_PER_ROW,
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
    alert_status_css = "\n".join(
        f".alert-banner.status-{status.lower()} {{ "
        f"--alert-color: {color}; --alert-bg: {status_bg[status]}; }}"
        for status, color in status_colors.items()
    )
    # 요약 타일의 톤 — 상태색을 그대로 쓴다. 같은 상태를 화면마다 다른 색으로 말하면
    # 담당자가 심각도를 잘못 읽는다(alert-banner와 같은 이유).
    summary_tone_css = "\n".join(
        f".summary-tile.tone-{status.lower()} {{ --tone: {color}; }}"
        for status, color in status_colors.items()
    )
    chip_status_css = "\n".join(
        f".event-change .chip.status-{status.lower()} {{ "
        f"color: {color}; background: {status_bg[status]}; }}"
        for status, color in status_colors.items()
    )
    status_card_status_css = "\n".join(
        f".status-card.status-{status.lower()} {{ "
        f"--card-color: {color}; --card-bg: {status_bg[status]}; }}"
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

        /* --- 상단 요약 타일 (05 §3.1) --- */
        /* 4열 → (좁으면) 2×2. auto-fit + minmax를 쓰면 중간 폭에서 3열이 되어 4개 타일이
           3+1로 접히고 마지막 타일만 홀로 남는다. 절반씩 접히도록 열 수를 명시한다. */
        .summary-grid {{
            display: grid; grid-template-columns: repeat(4, 1fr);
            gap: 12px; margin: 8px 0 16px;
        }}
        @media (max-width: 820px) {{
            .summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
        }}
        .summary-tile {{
            --tone: {p["brand"]};
            position: relative; padding: 14px 16px 13px; border-radius: 10px;
            background: {p["surface"]}; border: 1px solid {p["border"]};
            border-top: 3px solid var(--tone);
        }}
        .summary-tile.tone-brand {{ --tone: {p["brand"]}; }}
        {summary_tone_css}
        .sum-label {{
            display: flex; align-items: center; gap: 6px;
            font-size: 12px; font-weight: 600; color: {p["text_muted"]};
        }}
        .sum-dot {{
            width: 7px; height: 7px; border-radius: 50%; background: var(--tone); flex: 0 0 auto;
        }}
        /* 값은 이 화면에서 가장 먼저 읽혀야 하는 정보라 크기 차이를 확실히 준다. */
        .sum-value {{
            font-size: 30px; font-weight: 800; color: {p["text_strong"]};
            line-height: 1.15; margin: 7px 0 3px;
        }}
        .sum-unit {{
            font-size: 15px; font-weight: 700; color: {p["text_muted"]}; margin-left: 3px;
        }}
        .sum-sub {{ font-size: 11.5px; color: {p["text_muted"]}; }}

        /* --- 조치 배너 (05 §3.1) --- */
        .metric-sub {{
            font-size: 11.5px; color: {p["text_muted"]}; margin-top: -10px;
        }}
        .alert-banner {{
            --alert-color: {status_colors["DANGER"]};
            --alert-bg: {status_bg["DANGER"]};
            margin: 4px 0 6px; padding: 11px 14px; border-radius: 8px;
            border-left: 4px solid var(--alert-color);
            background: var(--alert-bg); color: {p["text"]}; font-size: 13.5px;
        }}
        .alert-banner b {{ color: var(--alert-color); }}
        {alert_status_css}
        /* FAULT는 상태색(빨강)이 DANGER(주황)보다 이미 강해 배너를 따로 채우지 않는다.
           2026-08-07 팔레트 재정리 전에는 FAULT가 슬레이트라 테두리만으로는 아래 DANGER
           배너보다 약해 보여 배경을 채우는 우회가 있었다. 램프가 단조 증가로 바뀌어
           그 우회를 걷어냈다 — 모든 배너가 같은 형태를 쓰고 심각도는 색이 말한다. */

        /* --- 정비 완료 확인 필요 (05 §3.1) — 아이콘·강조 링으로 '확인 필요' 부각 --- */
        .maint-alert {{
            display: flex; align-items: center; gap: 10px;
            background: {status_colors["FAULT"]}; color: {p["surface"]};
            border-radius: 8px; padding: 12px 16px; margin: 6px 0 12px;
        }}
        .maint-alert-icon {{ font-size: 20px; line-height: 1; flex: 0 0 auto; }}
        .maint-alert-text {{ font-size: 14px; font-weight: 500; }}
        .maint-alert-text b {{ font-weight: 800; }}
        /* 모터별 확인 카드 — 테두리 박스(컨테이너)가 카드가 되고 정보+버튼을 함께 담는다.
           박스에 FAULT 좌측 강조선과 옅은 배경을 준다(정보 div의 .maint-name으로 판별). */
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.maint-name) {{
            border-left: 3px solid {status_colors["FAULT"]};
            border-radius: 8px; background: {status_bg["FAULT"]};
        }}
        .maint-info {{ margin-bottom: 8px; }}
        .maint-info .maint-name {{
            font-size: 13px; font-weight: 700; color: {p["text_strong"]};
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .maint-info .maint-meta {{
            font-size: 10.5px; color: {p["text_muted"]}; margin-top: 2px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .maint-info .maint-loc {{
            font-size: 10.5px; color: {p["text_faint"]};
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        /* 정비 완료 확인 버튼 — 크기를 줄여 카드 안, 정보 아래 작게 둔다 */
        .stElementContainer[class*="st-key-banner-maint-"] button {{
            min-height: 0; padding: 3px 10px; font-size: 12px; font-weight: 600;
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

        /* --- 모터 현황 페이지 (재정리안 2페이지) --- */
        /* 그룹핑 라디오 — 다른 컨트롤과 구분되게 라운드 테두리 박스로 감싼다 */
        .st-key-status_grouping_mode {{
            border: 1px solid {p["border"]}; border-radius: 10px;
            padding: 8px 14px; background: {p["surface"]};
            display: inline-block; margin-bottom: 8px;
        }}

        /* 반응형 카드 배치 — 한 그룹의 컬럼을 flex-wrap으로 감싼다. 화면이 좁아지면 한 줄
           카드 수가 자동으로 준다(7→6→5…). 카드 폭은 STATUS_CARD_MIN_WIDTH_PX 밑으로는
           내려가지 않고, max-width로 최대 열 수(STATUS_CARDS_PER_ROW)를 제한한다. */
        div[data-testid="stHorizontalBlock"]:has(.status-card) {{
            flex-wrap: wrap;
            column-gap: {STATUS_CARD_GRID_GAP_PX}px;
            /* row-gap을 16px 더 준다: Streamlit 마크다운 래퍼가 컬럼(플렉스 라인) 높이를
               카드보다 16px 낮게 보고해, 기본 gap만으로는 아래 행이 위 행 카드와 겹친다.
               이 보정으로 실제 행 간격이 STATUS_CARD_GRID_GAP_PX가 된다. */
            row-gap: {STATUS_CARD_GRID_GAP_PX + 16}px;
            max-width: {STATUS_CARDS_PER_ROW * STATUS_CARD_MIN_WIDTH_PX
                        + (STATUS_CARDS_PER_ROW - 1) * STATUS_CARD_GRID_GAP_PX}px;
            margin-bottom: 6px;
        }}
        /* 카드는 늘어나지 않는 고정 폭 — 모든 카드(부분 행 포함)가 정확히 같은 크기가 되게
           한다. 남는 가로 공간은 채우지 않고, 열 수만 화면 폭에 따라 줄어든다. */
        div[data-testid="stHorizontalBlock"]:has(.status-card) > div[data-testid="stColumn"] {{
            flex: 0 0 {STATUS_CARD_MIN_WIDTH_PX}px;
            width: {STATUS_CARD_MIN_WIDTH_PX}px;
            min-width: {STATUS_CARD_MIN_WIDTH_PX}px;
            max-width: {STATUS_CARD_MIN_WIDTH_PX}px;
        }}
        /* 카드 클릭 영역 — 카드 마크다운과 투명 버튼을 컬럼 안 형제로 두고 버튼을 덮는다.
           st.button은 웹소켓 처리라 리로드가 없어 로그인 세션이 유지된다. */
        div[data-testid="stColumn"]:has(.status-card) > div[data-testid="stVerticalBlock"] {{
            position: relative;
        }}
        div[data-testid="stColumn"]:has(.status-card)
        .stElementContainer[class*="st-key-{STATUS_CARD_BUTTON_PREFIX}"] {{
            /* 카드가 컬럼보다 16px 크므로(위 row-gap 주석 참고) 오버레이도 16px 아래로
               늘려 카드 전체(푸터 포함)가 클릭되게 한다. */
            position: absolute; top: 0; left: 0; right: 0; bottom: -16px;
            z-index: 3; margin: 0;
        }}
        div[data-testid="stColumn"]:has(.status-card)
        .stElementContainer[class*="st-key-{STATUS_CARD_BUTTON_PREFIX}"] .stButton,
        div[data-testid="stColumn"]:has(.status-card)
        .stElementContainer[class*="st-key-{STATUS_CARD_BUTTON_PREFIX}"] button {{
            width: 100%; height: 100%; opacity: 0; cursor: pointer;
            border: none; background: transparent; padding: 0; min-height: 0;
        }}
        /* 높이는 내용에 맡긴다 — 모든 카드가 같은 구조(배지·이름·위치·모델·지표 2줄·푸터)라
           높이가 균일하다. 고정 height는 Streamlit 컬럼 내부 블록 높이와 어긋나 카드가
           넘쳐(overflow) 아래 행과 겹치는 문제가 있었다. */
        .status-card {{
            --card-color: {status_colors["NORMAL"]};
            --card-bg: {status_bg["NORMAL"]};
            position: relative; padding: 9px 11px; border-radius: 8px;
            border: 1px solid {p["border"]}; border-top: 3px solid var(--card-color);
            background: {p["surface"]};
            transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.12s ease;
        }}
        {status_card_status_css}
        .status-card.status-warning, .status-card.status-danger, .status-card.status-fault {{
            background: var(--card-bg);
        }}
        div[data-testid="stColumn"]:has(.status-card):hover .status-card {{
            transform: translateY(-2px); border-color: var(--card-color);
            box-shadow: 0 4px 12px color-mix(in srgb, var(--card-color) 26%, transparent);
        }}
        @media (prefers-reduced-motion: reduce) {{
            .status-card {{ transition: none; }}
            div[data-testid="stColumn"]:has(.status-card):hover .status-card {{ transform: none; }}
        }}
        /* 상태 라벨을 좌상단에 먼저, 그 아래 모터명 — 긴 모터명과 배지가 겹치지 않게 한다 */
        .status-card .sc-badge-row {{ height: 18px; margin-bottom: 9px; }}
        .status-card .sc-badge-row .status-badge {{
            padding: 1px 7px; font-size: 9px; border-radius: 9px;
        }}
        .status-card .sc-name {{
            font-size: 12.5px; font-weight: 700; color: {p["text_strong"]}; margin-top: 0;
            line-height: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .status-card .sc-loc {{
            font-size: 10px; color: {p["text_muted"]}; margin-top: 2px;
            height: 14px; line-height: 14px; white-space: nowrap;
            overflow: hidden; text-overflow: ellipsis;
        }}
        /* 모델명 아래 지표를 바로 붙인다 (모델명↔온도 사이 공간 제거) */
        .status-card .sc-model {{
            font-size: 10px; color: {p["text_faint"]};
            height: 14px; line-height: 14px; white-space: nowrap;
            overflow: hidden; text-overflow: ellipsis;
        }}
        .status-card .sc-metrics {{ margin-top: 2px; }}
        .status-card .sc-metric-line {{
            display: flex; align-items: baseline; gap: 3px; line-height: 17px;
            /* 안전망 — 예상 밖으로 긴 값이 와도 레이아웃을 밀지 않고 말줄임된다 */
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        /* 지표 색을 라벨·값·단위로 나눈다 (메인 대시보드 색 체계 공유).
           여백은 균일한 gap이 아니라 자리마다 다르게 준다 (2026-08-07) — 라벨과 값이
           붙으면 "온도82.2"처럼 한 단어로 읽히므로 한 칸이 필요하고, 값과 단위 사이는
           붙어도 수치와 단위로 구분되어 읽힌다. */
        .status-card .scm {{ display: inline-flex; align-items: baseline; gap: 0; }}
        /* 라벨 뒤 한 칸 — 10px 글꼴의 공백 한 칸에 해당한다 */
        .status-card .scm-l {{ font-size: 10px; color: {p["text_muted"]}; margin-right: 4px; }}
        .status-card .scm-v {{ font-size: 11.5px; font-weight: 600; color: {p["text"]}; }}
        .status-card .scm-u {{ font-size: 9px; color: {p["text_faint"]}; margin-left: 2px; }}
        .status-card .scm-sep {{ color: {p["text_ghost"]}; margin: 0 3px; }}
        /* 이상 지표(WARNING/DANGER/FAULT)는 라벨·값·단위를 상태색으로 강조 — 어느 지표가
           문제인지 정상 지표와 확실히 구분되게 한다 (메인 대시보드 강조 방식과 동일). */
        .status-card .scm.scm-abn .scm-l,
        .status-card .scm.scm-abn .scm-v,
        .status-card .scm.scm-abn .scm-u {{ color: var(--scm-color); font-weight: 700; }}
        .status-card .scm.status-warning {{ --scm-color: {status_colors["WARNING"]}; }}
        .status-card .scm.status-danger {{ --scm-color: {status_colors["DANGER"]}; }}
        .status-card .scm.status-fault {{ --scm-color: {status_colors["FAULT"]}; }}
        /* 상태 변경 시각 — 지표 바로 아래 붙이고(소음↔상태변경 공간 제거), 이상 상태는 상태색 강조 */
        .status-card .sc-foot {{
            font-size: 9.5px; color: {p["text_faint"]}; margin-top: 3px;
            white-space: nowrap; overflow: hidden;
        }}
        .status-card .sc-foot.status-warning {{ color: {status_colors["WARNING"]}; font-weight: 600; }}
        .status-card .sc-foot.status-danger {{ color: {status_colors["DANGER"]}; font-weight: 600; }}
        .status-card .sc-foot.status-fault {{ color: {status_colors["FAULT"]}; font-weight: 700; }}

        /* --- 모터 그래프 페이지 (재정리안 1페이지) — 지표 열 헤더/범례/모터명 행 --- */
        /* 헤더(지표명·단위) + 임계값을 라운드 테두리 박스로 묶어 아래 차트들의 '대표 정보'로 구분 */
        .mg-headbox {{
            border: 1px solid {p["border"]};
            border-left: 3px solid var(--mg-color, {brand});
            border-radius: 8px; padding: 6px 10px 7px; margin-bottom: 9px;
            background: {p["surface_muted"]};
        }}
        .mg-head {{
            display: flex; align-items: baseline; gap: 6px;
            border-bottom: 1px dashed {p["border"]}; padding-bottom: 4px; margin-bottom: 5px;
        }}
        .mg-metric {{ font-size: 14px; font-weight: 800; color: var(--mg-color, {brand}); }}
        .mg-unit {{ font-size: 10px; color: {p["text_muted"]}; }}
        /* 임계값 범례 — 색은 상태색과 일치시킨다. */
        .mg-legend {{
            display: flex; flex-wrap: wrap; gap: 4px 8px; font-size: 9.5px; font-weight: 600;
            line-height: 1.3;
        }}
        .mg-row {{
            display: flex; align-items: center; justify-content: space-between;
            gap: 4px; margin-top: 8px; height: 18px;
        }}
        .mg-name {{
            font-size: 11px; font-weight: 600; color: {p["text_strong"]};
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .mg-row .status-badge {{ flex: 0 0 auto; padding: 0 6px; font-size: 8.5px; border-radius: 8px; }}
        /* 표시 범위 셀렉트박스를 읽기전용처럼 — 캐럿을 숨겨 편집 느낌을 없앤다.
           실제 타이핑 차단은 입력을 readOnly로 만드는 JS(모터 그래프 페이지)가 담당한다. */
        .st-key-graph_status input,
        .st-key-graph_loc input,
        .st-key-graph_model input,
        .st-key-graph_maxn input {{
            caret-color: transparent; cursor: pointer;
        }}

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

        /* 행 구분선 (05 §3.3) — 줄이 많아지면 어느 값이 어느 행인지 눈으로 따라가기
           어렵다. 이벤트 행에만 걸도록 `.event-when`(행)·`.event-th`(헤더)로 범위를 좁힌다.
           대시보드의 다른 컬럼 블록까지 선이 그어지면 화면이 표처럼 보여 버린다. */
        /* 헤더는 min-height로 잡는다. Streamlit이 이 블록을 실제 글자 높이보다 작게
           보고해(16px 라벨인데 블록 14px), 그대로 두면 글자가 하단 구분선 아래로 삐져나온다.
           데이터 행에 쓴 height:auto 방식은 헤더에서 듣지 않았고(stMarkdown이 3px로 무너짐),
           padding-bottom도 블록 높이에 반영되지 않아 min-height가 유일하게 통했다.
           값은 라벨 글꼴(16px)에 연동한다 — 글꼴만 키우고 여기를 고정으로 두면 다시 넘친다. */
        div[data-testid="stHorizontalBlock"]:has(.event-th) {{
            border-bottom: 2px solid {p["border"]};
            /* center로 두면 Streamlit이 잘못 보고한 작은 상자를 기준으로 정렬해 글자가
               아래로 쏠리고 구분선에 1px까지 붙는다. 위에서 시작시키고 여백을 직접 준다. */
            align-items: flex-start; padding-top: 0.5em; min-height: 2.7em;
            margin-bottom: 2px;
        }}
        /* border_soft는 다크에서 surface와 거의 같아 선이 보이지 않는다 — border를 쓴다. */
        div[data-testid="stHorizontalBlock"]:has(.event-when) {{
            border-bottom: 1px solid {p["border"]};
            padding: 9px 0;
            /* stretch여야 컬럼이 행 높이만큼 늘어난다. center로 두면 아래 마크다운 높이
               문제와 겹쳐 콘텐츠가 행 아래로 밀려 구분선에 달라붙는다. */
            align-items: stretch;
        }}
        /* 데이터 행: Streamlit이 마크다운 래퍼를 한 줄 기준(16px)으로 보고해, 두 줄인
           "발생 일시"(32px)가 블록을 넘쳐 하단 구분선에 6px까지 달라붙었다.
           높이를 풀고 컬럼을 늘려 행 높이에 맞춘다. */
        div[data-testid="stHorizontalBlock"]:has(.event-when) [data-testid="stMarkdown"],
        div[data-testid="stHorizontalBlock"]:has(.event-when) [data-testid="stMarkdown"] > div {{
            height: auto !important; min-height: 0 !important;
        }}
        div[data-testid="stHorizontalBlock"]:has(.event-when) [data-testid="stColumn"] {{
            display: flex; align-items: center;
        }}
        /* 컬럼명은 본문(모터명 16px)과 같은 크기로 둔다. 12px일 때는 표의 머리글이 아니라
           작은 주석처럼 읽혀 어느 열이 무엇인지 눈에 들어오지 않았다. */
        .event-th {{
            font-size: 16px; font-weight: 700; color: {p["text_muted"]};
            letter-spacing: 0.01em;
        }}

        /* 값 변화 (05 §3.3, 2026-08-07 추가) — 상태만으로는 임계를 아슬하게 넘었는지
           크게 뛰었는지 알 수 없다. 담당자가 급한 정도를 가늠하는 수치라 이 열에서 가장
           크게 둔다. 이전 값은 흐리게, 현재 값을 굵게 해 "지금 얼마인가"에 시선이 먼저 간다. */
        .event-value {{
            display: flex; align-items: baseline; gap: 5px;
            font-size: 15px; white-space: nowrap;
        }}
        /* 리포트가 없는 행(NORMAL/WARNING 전이)의 버튼 자리. 버튼과 같은 높이·정렬로
           두어야 행 높이가 들쭉날쭉해지지 않는다 (05 §4.4). */
        .event-noreport {{
            font-size: 12.5px; color: {p["text_faint"]}; text-align: center;
            width: 100%; line-height: 1.2;
        }}
        .event-value .ev-prev {{ color: {p["text_faint"]}; font-weight: 500; }}
        .event-value .ev-now {{ font-weight: 800; color: {p["text_strong"]}; }}
        .event-value .ev-unit {{ font-size: 11.5px; color: {p["text_muted"]}; }}
        .event-value .ev-arrow {{ font-size: 13px; color: {p["text_faint"]}; }}
        .event-value .ev-arrow.worse {{ color: {status_colors["DANGER"]}; }}
        .event-value .ev-arrow.recover {{ color: {status_colors["NORMAL"]}; }}

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
