"""지표 추이 라인차트 (05_ui_screens.md §3-A / §4.1-A).

모터 그래프 페이지와 모터 상세 페이지가 **같은 차트**를 쓴다. 종전에는 그리는 코드가
`app/pages/motor_graph.py` 안에만 있어 상세에서 재사용할 수 없었다 — 축 구성·임계선·
Y범위 규칙이 한 벌만 존재해야 두 화면의 그래프를 같은 눈으로 비교할 수 있으므로,
페이지 밖으로 꺼내 공유한다 (2026-08-10).

설계 원칙 (모터 그래프 페이지에서 확정된 것을 그대로 유지):
- 숫자 Y축을 반복하지 않는다. 열 헤더에 임계값을 한 번만 적고, 모든 차트가 같은 고정
  Y범위를 공유해 임계선 위치로 값을 읽는다.
- 지표마다 라인 색과 열 테두리를 달리해 열을 구분한다.
- 축은 `None` 대신 `alt.Axis(...)`로 준다(`axis=None`은 일부 Vega에서 렌더 크래시).
  `.configure_*()`도 쓰지 않는다(Streamlit이 렌더하지 못한다).
"""

import math

import altair as alt
import pandas as pd
import streamlit as st

from app.config import (
    DISPLAY_TIMEZONE,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_THRESHOLDS,
    METRIC_UNITS,
)
from app.ui.theme import palette

# 차트 높이(px). 두 화면이 같은 값을 써야 세로 축척이 같아 눈으로 비교된다.
CHART_HEIGHT_PX = 130


def _y_ticks(fault: float) -> tuple[list[float], float]:
    """0 ~ 고장선 위까지의 '나이스' 눈금값과 축 상한.

    고장 임계가 90/95처럼 커도 최상단 값(예: 100)이 반드시 라벨로 찍히도록, step을 나이스
    단위(1/2/2.5/5 × 10^k)로 고르고 상한을 그 배수로 올린 뒤 눈금값을 명시한다. tickCount에
    맡기면 온도(상한 103)·소음(109)에서 0·40·80으로 끊겨 최상단이 라벨 없이 남는다.
    """
    raw = fault * 1.05  # 고장선 살짝 위
    magnitude = 10 ** math.floor(math.log10(raw))
    top = next(s * magnitude for s in (1, 2, 2.5, 5, 10) if s * magnitude >= raw)
    # 눈금 3개만 둔다(0·중간·최상단). Vega가 눈금이 많으면 격자·라벨을 자동으로 솎아
    # 최상단(예: 100)을 떨어뜨리는데, 3개면 솎이지 않아 최상단이 항상 보인다.
    return [0, round(top / 2, 2), top], top


def metric_chart(df: pd.DataFrame, metric: str) -> alt.LayerChart:
    """지표 추이 라인 + 데이터 포인트 마커 + 상태 임계선.

    `df`는 `t`(naive datetime, 표시 타임존)와 `v`(값) 열을 갖는다.
    """
    pal = palette()
    metric_colors, status_colors = pal["metric_chart"], pal["status"]
    _, warning, danger, fault = METRIC_THRESHOLDS[metric]
    y_ticks, y_max = _y_ticks(fault)

    x_axis = alt.Axis(
        format="%H:%M", labelFontSize=8, tickCount=4, title=None, grid=True, domain=True
    )
    # format ".1~f": 12.5 같은 반정수 눈금이 "13"으로 반올림되지 않게(불필요한 0은 제거)
    y_axis = alt.Axis(
        values=y_ticks, labelFontSize=8, title=None, grid=True, domain=True, format=".1~f"
    )
    line = (
        alt.Chart(df)
        .mark_line(
            color=metric_colors[metric],
            strokeWidth=2,
            point=alt.OverlayMarkDef(color=metric_colors[metric], filled=True, size=22),
        )
        .encode(
            x=alt.X("t:T", axis=x_axis),
            y=alt.Y("v:Q", scale=alt.Scale(domain=[0, y_max], clamp=True), axis=y_axis),
        )
    )
    thresholds = pd.DataFrame(
        {"y": [warning, danger, fault], "status": ["WARNING", "DANGER", "FAULT"]}
    )
    rules = (
        alt.Chart(thresholds)
        .mark_rule(strokeDash=[3, 3], strokeWidth=1, opacity=0.85)
        .encode(
            y="y:Q",
            color=alt.Color(
                "status:N",
                scale=alt.Scale(
                    domain=["WARNING", "DANGER", "FAULT"],
                    range=[
                        status_colors["WARNING"],
                        status_colors["DANGER"],
                        status_colors["FAULT"],
                    ],
                ),
                legend=None,
            ),
        )
    )
    return (rules + line).properties(height=CHART_HEIGHT_PX)


def _metric_header(metric: str) -> None:
    """지표명 + 임계값 범례. 차트 박스 '밖'에 둬 헤더와 차트를 명확히 구분한다."""
    pal = palette()
    status_colors = pal["status"]
    _, warning, danger, fault = METRIC_THRESHOLDS[metric]
    st.markdown(
        f'<div class="mg-headbox" style="--mg-color:{pal["metric_chart"][metric]}">'
        f'<div class="mg-head">'
        f'<span class="mg-metric">{METRIC_LABELS[metric]}</span>'
        f'<span class="mg-unit">{METRIC_UNITS[metric]}</span></div>'
        f'<div class="mg-legend">'
        f'<span style="color:{status_colors["WARNING"]}">▬ 경고 {warning:g}</span>'
        f'<span style="color:{status_colors["DANGER"]}">▬ 위험 {danger:g}</span>'
        f'<span style="color:{status_colors["FAULT"]}">▬ 고장 {fault:g}</span>'
        f"</div></div>",
        unsafe_allow_html=True,
    )


def _motor_charts(motor, series, metric: str) -> None:
    """모터 한 대의 특정 지표 차트 하나."""
    times, by_metric = series[motor["motor_id"]]
    values = by_metric.get(metric, [])
    if not times or not values:
        st.caption("데이터 없음")
        return
    frame = pd.DataFrame({"t": pd.to_datetime(times, utc=True), "v": values})
    # UTC → 표시 타임존, tz 제거(naive) — Vega가 브라우저 tz로 재해석하지 않게.
    frame["t"] = frame["t"].dt.tz_convert(DISPLAY_TIMEZONE).dt.tz_localize(None)
    st.altair_chart(metric_chart(frame, metric), width="stretch")


def metric_graph_grid(motors, series, *, show_motor_row: bool = True) -> None:
    """지표 4열 헤더 아래에 **모터 한 대 = 가로 한 행**으로 차트를 배치한다.

    `motors`는 `motor_id`·`motor_name`·`status`를 갖는 항목의 목록,
    `series`는 `{motor_id: (시각 목록, {지표: 값 목록})}`.

    **모터를 행 단위로 묶는 이유 (2026-08-10 변경).** 종전에는 지표 열이 바깥 루프였다
    (열 하나에 모터들을 세로로 쌓음). 그래서 ① 모터명·상태 배지가 **열마다 4번 반복**됐고
    ② 모터 사이 구분선을 열 경계 밖으로 그릴 수 없어 어디까지가 한 모터인지 눈으로
    이어 붙여야 했다. 모터를 행으로 묶으면 이름은 행 왼쪽에 **한 번만** 나오고,
    테두리 컨테이너가 4열을 가로로 감싸 행 경계가 그대로 보인다.

    `show_motor_row`는 행 머리(모터명·상태 배지)를 넣을지다. 모터 상세는 한 대뿐이라
    페이지 제목과 상단 배지가 이미 알려주므로 넣지 않는다.
    """
    # 헤더는 위에 한 줄만. 차트 박스 '밖'이라 헤더와 차트가 명확히 구분된다.
    for column, metric in zip(st.columns(len(METRIC_NAMES)), METRIC_NAMES):
        with column:
            _metric_header(metric)

    for motor in motors:
        # 테두리 컨테이너가 한 모터의 4열을 가로로 감싼다 — 이것이 행 구분선 역할을 한다.
        with st.container(border=True):
            if show_motor_row:
                status = motor["status"]
                st.markdown(
                    f'<div class="mg-row">'
                    f'<span class="mg-name">{motor["motor_name"]}</span>'
                    f'<span class="status-badge status-{status.lower()}">{status}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            for column, metric in zip(st.columns(len(METRIC_NAMES)), METRIC_NAMES):
                with column:
                    _motor_charts(motor, series, metric)
