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
    GRAPH_CHART_Y_DIVISIONS,
    GRAPH_DETAIL_BUTTON_LABEL,
    GRAPH_DETAIL_BUTTON_PREFIX,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_THRESHOLDS,
    METRIC_UNITS,
)
from app.ui.theme import palette


def _y_ticks(fault: float, divisions: int) -> tuple[list[float], float]:
    """0 ~ 고장선 위까지의 '나이스' 눈금값과 축 상한.

    고장 임계가 90/95처럼 커도 최상단 값(예: 100)이 반드시 라벨로 찍히도록, step을 나이스
    단위(1/2/2.5/5 × 10^k)로 고르고 상한을 그 배수로 올린 뒤 눈금값을 명시한다. tickCount에
    맡기면 온도(상한 103)·소음(109)에서 0·40·80으로 끊겨 최상단이 라벨 없이 남는다.

    `divisions`는 **0~상한을 몇 단계로 나눌지**다(눈금 개수는 `divisions + 1`). 개수가 아니라
    단계로 받는 이유는 상한을 등분한 값이 나이스 숫자로 떨어지기 때문이다 — 10단계면 온도·소음
    0·10·…·100, 진동 0·1·…·10, 전류 0·2.5·…·25가 된다(눈금 개수 10으로 잡으면 9등분이라
    11.11·22.22가 나온다).

    Vega는 눈금이 많으면 격자·라벨을 자동으로 솎아 최상단(예: 100)을 떨어뜨리므로,
    **차트 높이에 맞는 단계 수를 호출부가 정한다** — 130px는 2단계, 260px는 10단계
    (config의 `GRAPH_CHART_Y_DIVISIONS` / `DETAIL_CHART_Y_DIVISIONS`).
    """
    raw = fault * 1.05  # 고장선 살짝 위
    magnitude = 10 ** math.floor(math.log10(raw))
    top = next(s * magnitude for s in (1, 2, 2.5, 5, 10) if s * magnitude >= raw)
    return [round(top * i / divisions, 2) for i in range(divisions + 1)], top


def metric_chart(
    df: pd.DataFrame,
    metric: str,
    thresholds: dict | None = None,
    *,
    height: int = GRAPH_CHART_HEIGHT_PX,
    y_divisions: int = GRAPH_CHART_Y_DIVISIONS,
    show_points: bool = True,
    x_tick_minutes: int | None = None,
) -> alt.LayerChart:
    """지표 추이 라인 + 데이터 포인트 마커 + 상태 임계선.

    `df`는 `t`(naive datetime, 표시 타임존)와 `v`(값) 열을 갖는다.

    `thresholds`는 해당 모터의 임계값(`motors.get_metric_thresholds`)이다. 생략하면
    회사 기본값을 쓴다 — 여러 모터를 한 화면에 겹쳐 비교하는 모터 그래프 페이지가
    그렇게 쓴다(아래 `metric_graph_grid` 참조).

    `height`·`y_divisions`의 기본값은 모터 그래프 페이지 값이다. 모터 상세는 config의
    `DETAIL_CHART_*`를 넘겨 세로를 2배로 쓴다(모듈 docstring 참조).

    `show_points`는 값 지점마다 원형 마커를 얹을지다. **다운샘플된 계열에서만 켠다** —
    마커는 "이 점이 실제 수집 지점"이라는 표시인데, 상세처럼 원본을 그대로 그리면 점이
    2천 개라 선이 마커로 뒤덮여 오히려 추이가 안 보인다.

    `x_tick_minutes`를 주면 X축 눈금·격자를 그 분 간격으로 고정한다. 생략하면 Vega가
    창 길이에 맞춰 고른다(6시간 창에서는 1시간). 모터 그래프 페이지가 30분으로 고정한다.
    """
    pal = palette()
    metric_colors, status_colors = pal["metric_chart"], pal["status"]
    _, warning, danger, fault = (thresholds or METRIC_THRESHOLDS)[metric]
    y_ticks, y_max = _y_ticks(fault, y_divisions)

    # `x_tick_minutes`는 **간격이 아니라 개수로 환산해서** 넘긴다. Vega-Lite 문법상
    # `tickCount={"interval":"minute","step":30}`가 맞지만, 이 번들의 Vega에서는 렌더가
    # 통째로 깨진다(실측: 차트 40개가 전부 빈칸, 콘솔에 `Cannot read properties of
    # undefined (reading 'bounds')`). 데이터 구간을 그 분 단위로 나눈 개수를 주면 Vega가
    # 나이스 시간 단위 중 30분을 골라 같은 결과가 된다.
    if x_tick_minutes:
        span_minutes = (df["t"].max() - df["t"].min()).total_seconds() / 60
        x_tick_count = max(2, round(span_minutes / x_tick_minutes))
    else:
        x_tick_count = 4
    x_axis = alt.Axis(
        format="%H:%M",
        labelFontSize=8,
        tickCount=x_tick_count,
        title=None,
        grid=True,
        domain=True,
    )
    # format ".2~f": 12.5 같은 눈금이 "13"으로 반올림되지 않게(불필요한 0은 제거).
    # 소수 2자리인 이유 — 눈금 5개일 때 전류(상한 25)는 6.25·18.75가 나오는데, ".1~f"는
    # 이를 6.3·18.8로 반올림해 라벨이 격자선 위치와 어긋난다. 눈금 3개 값(50·5·12.5)은
    # 자릿수를 늘려도 표기가 달라지지 않아 모터 그래프 페이지에는 영향이 없다.
    # labelOverlap=False: Vega는 라벨이 촘촘하면 스스로 솎아낸다. 10단계를 요청했는데
    # 260px에서 0·20·40·60·80·100만 남아 5단계로 보였다(실측). 격자선은 11줄 그대로였다.
    # 8px 글씨에 26px 간격이라 실제로는 겹치지 않으므로 솎기를 끈다.
    y_axis = alt.Axis(
        values=y_ticks,
        labelFontSize=8,
        title=None,
        grid=True,
        domain=True,
        format=".2~f",
        labelOverlap=False,
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
            # 임계선 레이어에도 **같은 축 설정을 준다.** 레이어가 같은 스케일을 공유하면 Vega가
            # 축을 하나로 합치는데, 이 레이어를 비워 두면 기본 축 설정이 섞여 들어와 라벨
            # 솎기(labelOverlap)가 되살아난다 — 10단계를 줘도 화면에는 6개만 찍혔다(실측).
            y=alt.Y("y:Q", scale=alt.Scale(domain=[0, y_max], clamp=True), axis=y_axis),
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
    y_divisions: int = GRAPH_CHART_Y_DIVISIONS,
    show_points: bool = True,
    x_tick_minutes: int | None = None,
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
            y_divisions=y_divisions,
            show_points=show_points,
            x_tick_minutes=x_tick_minutes,
        ),
        width="stretch",
    )


def _metric_status(motor, metric: str) -> str | None:
    """이 모터의 해당 지표 상태. 미확인 FAULT는 수치가 내려가도 FAULT로 본다 (03 §4.3).

    `list_company_motor_status()`가 돌려주는 `statuses`(지표별)·`fault_metrics`를 그대로 쓴다.
    """
    if metric in (motor.get("fault_metrics") or []):
        return "FAULT"
    return (motor.get("statuses") or {}).get(metric)


def _metric_status_badge(motor, metric: str) -> None:
    """차트 위 오른쪽에 그 지표의 상태 배지 한 개."""
    status = _metric_status(motor, metric)
    if not status:
        return
    st.markdown(
        f'<div class="mg-cell-status">'
        f'<span class="status-badge status-{status.lower()}">{status}</span></div>',
        unsafe_allow_html=True,
    )


def _motor_row_head(motor, *, show_status: bool, detail_link: bool) -> None:
    """행 머리 — 모터명과 (선택) 대표 상태 배지.

    `detail_link`면 이름 대신 **"(모터명) 상세 보기 ›" 버튼 하나**로 대체한다
    (라벨 서식은 `GRAPH_DETAIL_BUTTON_LABEL`).
    """
    from app.ui.navigation import MOTOR_DETAIL_PAGE  # 순환 import 방지를 위한 지연 import

    status = motor["status"]
    badge = (
        f'<span class="status-badge status-{status.lower()}">{status}</span>'
        if show_status
        else ""
    )
    name_html = (
        f'<div class="mg-row"><span class="mg-name">{motor["motor_name"]}</span>{badge}</div>'
    )
    if not detail_link:
        st.markdown(name_html, unsafe_allow_html=True)
        return

    # **모터명을 버튼 라벨 안에 넣는다** (2026-08-12 사용자 요청). 이름 마크다운과 버튼을
    # 따로 두면 둘 사이 간격을 아무리 좁혀도 "이름"과 "그 이름의 버튼"이라는 두 덩어리로
    # 읽힌다. 하나로 합치면 행 머리가 곧 진입점이 되고, 스크린리더에도 어느 모터의 상세로
    # 가는 버튼인지 그대로 읽힌다. 컬럼 3:9는 1600px 화면에서 약 360px — 가장 긴 라벨
    # (모터명 15자 + " 상세 보기 ›")이 잘리지 않는다.
    link_col, _rest = st.columns([3, 9], vertical_alignment="center")
    if link_col.button(
        GRAPH_DETAIL_BUTTON_LABEL.format(motor_name=motor["motor_name"]),
        key=f"{GRAPH_DETAIL_BUTTON_PREFIX}{motor['motor_id']}",
        width="stretch",
    ):
        st.session_state["selected_motor_id"] = motor["motor_id"]
        st.switch_page(MOTOR_DETAIL_PAGE)


def metric_graph_grid(
    motors,
    series,
    *,
    show_motor_row: bool = True,
    thresholds: dict | None = None,
    height: int = GRAPH_CHART_HEIGHT_PX,
    y_divisions: int = GRAPH_CHART_Y_DIVISIONS,
    show_points: bool = True,
    x_tick_minutes: int | None = None,
    show_metric_status: bool = False,
    detail_link: bool = False,
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

    **`show_metric_status`를 켜면 상태 배지가 행 머리에서 차트 4개 위로 옮겨간다**
    (2026-08-12 사용자 요청). 행 머리의 배지 하나는 대표 상태(가장 심각한 지표)라서 *어느*
    지표가 그 상태인지 알려주지 못했다 — 온도가 정상인데 소음 때문에 FAULT인 모터도 행 전체가
    FAULT로만 보였다. 지표별 배지는 `motors` 항목의 `statuses`·`fault_metrics`에서 읽으므로
    `list_company_motor_status()` 결과를 그대로 넘겨야 한다.

    `detail_link`는 행 머리 오른쪽에 "상세 보기" 버튼을 둘지다. 종전에는 그래프에서 이상을
    발견해도 상단 내비로 나가 대시보드에서 그 모터를 다시 찾아야 했다.

    `height`·`y_divisions`도 **모터 한 대를 그릴 때만 기본값과 다르게 준다** (2026-08-12).
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
                # 지표별 배지를 켰으면 행 머리의 대표 배지는 뺀다 — 같은 정보가 두 번이다.
                _motor_row_head(
                    motor, show_status=not show_metric_status, detail_link=detail_link
                )
            for column, metric in zip(st.columns(len(METRIC_NAMES)), METRIC_NAMES):
                with column:
                    if show_metric_status:
                        _metric_status_badge(motor, metric)
                    _motor_charts(
                        motor,
                        series,
                        metric,
                        thresholds,
                        height=height,
                        y_divisions=y_divisions,
                        show_points=show_points,
                        x_tick_minutes=x_tick_minutes,
                    )
