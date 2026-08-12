"""지표 추이 라인차트 (05_ui_screens.md §3-A / §4.1-A).

모터 그래프 페이지와 모터 상세 페이지가 **같은 차트**를 쓴다. 종전에는 그리는 코드가
`app/pages/motor_graph.py` 안에만 있어 상세에서 재사용할 수 없었다 — 축 구성·임계선·
Y범위 규칙이 한 벌만 존재해야 두 화면의 그래프를 같은 눈으로 비교할 수 있으므로,
페이지 밖으로 꺼내 공유한다 (2026-08-10).

**세로 크기·Y축 눈금 수·마커 표시만 화면별로 갈린다 (2026-08-12).** 축 구성·임계선·Y범위
규칙은 그대로 공유하되, 나머지는 호출부가 인자로 준다 — 그래프 페이지는 여러 대를 세로로
쌓아 비교하는 화면이라 낮아야 하고(기본값 = `GRAPH_CHART_*`), 상세는 한 대뿐이라 세로를
키워야 값의 변화 추이가 보인다(`DETAIL_CHART_*`). 자세한 근거는 config의 두 상수 주석.

**두 화면 모두 수집된 원본을 그대로 넘긴다** (`get_motor_metric_raw_series`, 2026-08-12).
종전의 15분 구간 평균은 스파이크를 지워 임계선을 넘은 적이 없는 것처럼 보이게 했다 —
근거 수치는 그 함수의 docstring에 있다. 이 모듈은 받은 계열을 그릴 뿐이라 평균이든 원본이든
동작하지만, 원본은 점이 모터·지표당 2천 개라 `show_points=False`로 넘겨야 한다.

설계 원칙 (모터 그래프 페이지에서 확정된 것을 그대로 유지):
- 숫자 Y축을 반복하지 않는다. 열 헤더에 임계값을 한 번만 적고, 한 화면 안의 모든 차트가
  같은 고정 Y범위를 공유해 임계선 위치로 값을 읽는다.
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
    GRAPH_CHART_HEIGHT_PX,
    GRAPH_CHART_Y_TICKS,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_THRESHOLDS,
    METRIC_UNITS,
)
from app.ui.theme import palette


def _y_ticks(fault: float, tick_count: int) -> tuple[list[float], float]:
    """0 ~ 고장선 위까지의 '나이스' 눈금값과 축 상한.

    고장 임계가 90/95처럼 커도 최상단 값(예: 100)이 반드시 라벨로 찍히도록, step을 나이스
    단위(1/2/2.5/5 × 10^k)로 고르고 상한을 그 배수로 올린 뒤 눈금값을 명시한다. tickCount에
    맡기면 온도(상한 103)·소음(109)에서 0·40·80으로 끊겨 최상단이 라벨 없이 남는다.

    `tick_count`는 0과 최상단을 포함한 눈금 개수다. Vega는 눈금이 많으면 격자·라벨을 자동으로
    솎아 최상단(예: 100)을 떨어뜨리므로, **차트 높이에 맞는 개수를 호출부가 정한다** —
    130px는 3개, 260px는 5개(config의 `GRAPH_CHART_Y_TICKS` / `DETAIL_CHART_Y_TICKS`).
    """
    raw = fault * 1.05  # 고장선 살짝 위
    magnitude = 10 ** math.floor(math.log10(raw))
    top = next(s * magnitude for s in (1, 2, 2.5, 5, 10) if s * magnitude >= raw)
    steps = tick_count - 1
    return [round(top * i / steps, 2) for i in range(tick_count)], top


def metric_chart(
    df: pd.DataFrame,
    metric: str,
    thresholds: dict | None = None,
    *,
    height: int = GRAPH_CHART_HEIGHT_PX,
    y_tick_count: int = GRAPH_CHART_Y_TICKS,
    show_points: bool = True,
) -> alt.LayerChart:
    """지표 추이 라인 + 데이터 포인트 마커 + 상태 임계선.

    `df`는 `t`(naive datetime, 표시 타임존)와 `v`(값) 열을 갖는다.

    `thresholds`는 해당 모터의 임계값(`motors.get_metric_thresholds`)이다. 생략하면
    회사 기본값을 쓴다 — 여러 모터를 한 화면에 겹쳐 비교하는 모터 그래프 페이지가
    그렇게 쓴다(아래 `metric_graph_grid` 참조).

    `height`·`y_tick_count`의 기본값은 모터 그래프 페이지 값이다. 모터 상세는 config의
    `DETAIL_CHART_*`를 넘겨 세로를 2배로 쓴다(모듈 docstring 참조).

    `show_points`는 값 지점마다 원형 마커를 얹을지다. **다운샘플된 계열에서만 켠다** —
    마커는 "이 점이 실제 수집 지점"이라는 표시인데, 상세처럼 원본을 그대로 그리면 점이
    2천 개라 선이 마커로 뒤덮여 오히려 추이가 안 보인다.
    """
    pal = palette()
    metric_colors, status_colors = pal["metric_chart"], pal["status"]
    _, warning, danger, fault = (thresholds or METRIC_THRESHOLDS)[metric]
    y_ticks, y_max = _y_ticks(fault, y_tick_count)

    x_axis = alt.Axis(
        format="%H:%M", labelFontSize=8, tickCount=4, title=None, grid=True, domain=True
    )
    # format ".2~f": 12.5 같은 눈금이 "13"으로 반올림되지 않게(불필요한 0은 제거).
    # 소수 2자리인 이유 — 눈금 5개일 때 전류(상한 25)는 6.25·18.75가 나오는데, ".1~f"는
    # 이를 6.3·18.8로 반올림해 라벨이 격자선 위치와 어긋난다. 눈금 3개 값(50·5·12.5)은
    # 자릿수를 늘려도 표기가 달라지지 않아 모터 그래프 페이지에는 영향이 없다.
    y_axis = alt.Axis(
        values=y_ticks, labelFontSize=8, title=None, grid=True, domain=True, format=".2~f"
    )
    line = (
        alt.Chart(df)
        .mark_line(
            color=metric_colors[metric],
            strokeWidth=2,
            point=(
                alt.OverlayMarkDef(color=metric_colors[metric], filled=True, size=22)
                if show_points
                else False
            ),
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
    return (rules + line).properties(height=height)


def _metric_header(metric: str, thresholds: dict | None = None) -> None:
    """지표명 + 임계값 범례. 차트 박스 '밖'에 둬 헤더와 차트를 명확히 구분한다."""
    pal = palette()
    status_colors = pal["status"]
    _, warning, danger, fault = (thresholds or METRIC_THRESHOLDS)[metric]
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


def _motor_charts(
    motor,
    series,
    metric: str,
    thresholds: dict | None = None,
    *,
    height: int = GRAPH_CHART_HEIGHT_PX,
    y_tick_count: int = GRAPH_CHART_Y_TICKS,
    show_points: bool = True,
) -> None:
    """모터 한 대의 특정 지표 차트 하나."""
    times, by_metric = series[motor["motor_id"]]
    values = by_metric.get(metric, [])
    if not times or not values:
        st.caption("데이터 없음")
        return
    frame = pd.DataFrame({"t": pd.to_datetime(times, utc=True), "v": values})
    # UTC → 표시 타임존, tz 제거(naive) — Vega가 브라우저 tz로 재해석하지 않게.
    frame["t"] = frame["t"].dt.tz_convert(DISPLAY_TIMEZONE).dt.tz_localize(None)
    st.altair_chart(
        metric_chart(
            frame,
            metric,
            thresholds,
            height=height,
            y_tick_count=y_tick_count,
            show_points=show_points,
        ),
        width="stretch",
    )


def metric_graph_grid(
    motors,
    series,
    *,
    show_motor_row: bool = True,
    thresholds: dict | None = None,
    height: int = GRAPH_CHART_HEIGHT_PX,
    y_tick_count: int = GRAPH_CHART_Y_TICKS,
    show_points: bool = True,
) -> None:
    """지표 4열 헤더 아래에 **모터 한 대 = 가로 한 행**으로 차트를 배치한다.

    `motors`는 `motor_id`·`motor_name`·`status`를 갖는 항목의 목록,
    `series`는 `{motor_id: (시각 목록, {지표: 값 목록})}`.

    **`thresholds`는 모터 한 대를 그릴 때만 넘긴다** (2026-08-11). 이 배치는 열 헤더에
    임계값을 한 번만 적고 모든 차트가 같은 Y범위를 공유해, 임계선 위치로 값을 읽는
    구조다. 모터마다 임계값이 다르면 그 전제가 깨지므로 **여러 대를 나열하는 모터 그래프
    페이지는 회사 기본값을 쓰고**, 표시 중인 모터의 설정이 기본과 다르면 그 페이지가
    캡션으로 알린다. 모터 상세는 한 대뿐이라 그 모터의 임계값을 그대로 쓴다.

    **모터를 행 단위로 묶는 이유 (2026-08-10 변경).** 종전에는 지표 열이 바깥 루프였다
    (열 하나에 모터들을 세로로 쌓음). 그래서 ① 모터명·상태 배지가 **열마다 4번 반복**됐고
    ② 모터 사이 구분선을 열 경계 밖으로 그릴 수 없어 어디까지가 한 모터인지 눈으로
    이어 붙여야 했다. 모터를 행으로 묶으면 이름은 행 왼쪽에 **한 번만** 나오고,
    테두리 컨테이너가 4열을 가로로 감싸 행 경계가 그대로 보인다.

    `show_motor_row`는 행 머리(모터명·상태 배지)를 넣을지다. 모터 상세는 한 대뿐이라
    페이지 제목과 상단 배지가 이미 알려주므로 넣지 않는다.

    `height`·`y_tick_count`도 **모터 한 대를 그릴 때만 기본값과 다르게 준다** (2026-08-12).
    여러 대를 세로로 쌓는 모터 그래프 페이지에서 키우면 스크롤이 그대로 곱절이 되고, 나열된
    모터를 같은 세로 축척으로 비교한다는 전제도 깨진다. 모터 상세만 `DETAIL_CHART_*`를 준다.
    """
    # 헤더는 위에 한 줄만. 차트 박스 '밖'이라 헤더와 차트가 명확히 구분된다.
    for column, metric in zip(st.columns(len(METRIC_NAMES)), METRIC_NAMES):
        with column:
            _metric_header(metric, thresholds)

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
                    _motor_charts(
                        motor,
                        series,
                        metric,
                        thresholds,
                        height=height,
                        y_tick_count=y_tick_count,
                        show_points=show_points,
                    )
