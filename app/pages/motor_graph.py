"""모터 그래프 페이지 (재정리안 1페이지).

지표 4열(온도/진동/전류/소음)에 필터링·정렬된 모터의 추이 라인차트를 세로로 나열한다.

- 표시 범위 필터: 상태 / 위치 / 모델명 / 표시 최대 수
- 정렬: 대표 상태 심각도 내림차순 (FAULT → DANGER → WARNING → NORMAL)
- 각 차트에 상태 임계선(경고/위험/고장)을 색으로 그려 값이 어느 구간인지 한눈에 보인다.
- 지표마다 라인 색과 열 영역(테두리)을 달리해 열을 구분한다.
- 숫자 Y축은 반복하지 않는다 — 열 헤더에 임계값을 한 번만 적고, 모든 차트가 같은 고정
  Y범위를 공유해 임계선 위치로 값을 읽는다(공간 절약).
"""

import math

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from app.config import (
    DISPLAY_TIMEZONE,
    GRAPH_DEFAULT_MAX_MOTORS,
    GRAPH_MAX_MOTORS_OPTIONS,
    GRAPH_STATUS_FILTER_ORDER,
    GRAPH_TREND_BUCKETS,
    GRAPH_TREND_HOURS,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_THRESHOLDS,
    METRIC_UNITS,
    STATUS_SEVERITY_RANK,
)
from app.db.connection import connection_scope
from app.services.motors import get_motor_metric_series, list_company_motor_status
from app.ui.components import page_header
from app.ui.theme import palette

page_header(active="graph")

_company_id = st.session_state.get("company_id")
_pal = palette()
_metric_colors = _pal["metric_chart"]
_status_colors = _pal["status"]

st.subheader("모터 그래프")

with connection_scope() as conn:
    _motors = list_company_motor_status(conn, _company_id)

if not _motors:
    st.info("등록된 모터가 없습니다.")
    st.stop()

# --- 표시 범위 필터 ---
st.caption("표시 범위")
_f1, _f2, _f3, _f4 = st.columns(4)
_status_sel = _f1.selectbox(
    "상태",
    GRAPH_STATUS_FILTER_ORDER,
    format_func=lambda s: "전체" if s == "ALL" else s,
    key="graph_status",
)
_loc_options = ["ALL"] + sorted({m["installation_location"] for m in _motors})
_loc_sel = _f2.selectbox(
    "위치", _loc_options, format_func=lambda v: "전체" if v == "ALL" else v, key="graph_loc"
)
_model_options = ["ALL"] + sorted({m["model_name"] for m in _motors})
_model_sel = _f3.selectbox(
    "모델명", _model_options, format_func=lambda v: "전체" if v == "ALL" else v, key="graph_model"
)
_max_n = _f4.selectbox(
    "표시 최대 수",
    GRAPH_MAX_MOTORS_OPTIONS,
    index=GRAPH_MAX_MOTORS_OPTIONS.index(GRAPH_DEFAULT_MAX_MOTORS),
    format_func=lambda n: f"{n}개",
    key="graph_maxn",
)

# --- 필터 적용 → 심각도 정렬 → 최대 수만큼 ---
_filtered = [
    m
    for m in _motors
    if (_status_sel == "ALL" or m["status"] == _status_sel)
    and (_loc_sel == "ALL" or m["installation_location"] == _loc_sel)
    and (_model_sel == "ALL" or m["model_name"] == _model_sel)
]
_filtered.sort(key=lambda m: (-STATUS_SEVERITY_RANK.get(m["status"], 0), m["motor_id"]))
_subset = _filtered[:_max_n]

if not _subset:
    st.info("조건에 맞는 모터가 없습니다. 필터를 조정해 주세요.")
    st.stop()

with connection_scope() as conn:
    _series = {
        m["motor_id"]: get_motor_metric_series(
            conn, m["motor_id"], GRAPH_TREND_HOURS, GRAPH_TREND_BUCKETS
        )
        for m in _subset
    }


def _y_ticks(fault: float) -> tuple[list[float], float]:
    """0 ~ 고장선 위까지의 '나이스' 눈금값과 축 상한을 만든다.

    고장 임계가 90/95처럼 커도 최상단 값(예: 100)이 반드시 라벨로 찍히도록, step을 나이스
    단위(1/2/2.5/5 × 10^k)로 고르고 상한을 그 배수로 올린 뒤 눈금값을 명시한다. tickCount에
    맡기면 온도(상한 103)·소음(109)에서 0·40·80으로 끊겨 최상단이 라벨 없이 남는다.
    """
    raw = fault * 1.05  # 고장선 살짝 위
    magnitude = 10 ** math.floor(math.log10(raw))
    top = next(s * magnitude for s in (1, 2, 2.5, 5, 10) if s * magnitude >= raw)  # 나이스 올림
    # 눈금 3개만 둔다(0·중간·최상단). Vega가 눈금이 많으면 격자·라벨을 자동으로 솎아
    # 최상단(예: 100)을 떨어뜨리는데, 3개면 솎이지 않아 최상단이 항상 보인다.
    return [0, round(top / 2, 2), top], top


def _chart(df: pd.DataFrame, metric: str) -> alt.LayerChart:
    """지표 추이 라인 + 데이터 포인트 마커 + 상태 임계선.

    - X축(시간 HH:MM)·Y 숫자 눈금·축선·격자를 모든 차트에 동일하게 표시한다. 모든 차트가
      같은 축 구성·높이·Y범위를 써 세로 축척이 동일하므로, 서로 다른 모터를 눈으로 비교할 수 있다.
    - 값 지점마다 원형 마커를 찍는다.
    - Y 눈금은 3개(0·중간·최상단)만 둔다(_y_ticks) — Vega가 눈금이 많으면 격자·라벨을 격줄로
      솎아 최상단(예: 100)을 떨어뜨리는데, 3개면 솎여도 최상단이 항상 남는다.
    - 축은 None 대신 `alt.Axis(...)`로 준다(axis=None은 일부 Vega에서 렌더 크래시).
      `.configure_*()`도 쓰지 않는다(Streamlit이 렌더 못함).
    """
    _, warning, danger, fault = METRIC_THRESHOLDS[metric]
    y_ticks, y_max = _y_ticks(fault)  # 최상단이 항상 찍히는 3눈금 + 축 상한
    _x_axis = alt.Axis(
        format="%H:%M", labelFontSize=8, tickCount=4, title=None, grid=True, domain=True
    )
    # format ".1~f": 12.5 같은 반정수 눈금이 "13"으로 반올림되지 않게(소수 1자리, 불필요한 0은 제거)
    _y_axis = alt.Axis(
        values=y_ticks, labelFontSize=8, title=None, grid=True, domain=True, format=".1~f"
    )
    line = (
        alt.Chart(df)
        .mark_line(
            color=_metric_colors[metric],
            strokeWidth=2,
            point=alt.OverlayMarkDef(color=_metric_colors[metric], filled=True, size=22),
        )
        .encode(
            x=alt.X("t:T", axis=_x_axis),
            y=alt.Y("v:Q", scale=alt.Scale(domain=[0, y_max], clamp=True), axis=_y_axis),
        )
    )
    thr_df = pd.DataFrame(
        {"y": [warning, danger, fault], "status": ["WARNING", "DANGER", "FAULT"]}
    )
    rules = (
        alt.Chart(thr_df)
        .mark_rule(strokeDash=[3, 3], strokeWidth=1, opacity=0.85)
        .encode(
            y="y:Q",
            color=alt.Color(
                "status:N",
                scale=alt.Scale(
                    domain=["WARNING", "DANGER", "FAULT"],
                    range=[
                        _status_colors["WARNING"],
                        _status_colors["DANGER"],
                        _status_colors["FAULT"],
                    ],
                ),
                legend=None,
            ),
        )
    )
    return (rules + line).properties(height=130)


# --- 4열 (지표별 색·테두리로 영역 구분) ---
for _column, _metric in zip(st.columns(len(METRIC_NAMES)), METRIC_NAMES):
    _, _warning, _danger, _fault = METRIC_THRESHOLDS[_metric]
    _color = _metric_colors[_metric]
    with _column:
        # 지표 헤더 + 임계값 라운드 박스 — 차트 박스(테두리 컨테이너) '밖'에 둬 명확히 구분한다.
        st.markdown(
            f'<div class="mg-headbox" style="--mg-color:{_color}">'
            f'<div class="mg-head">'
            f'<span class="mg-metric">{METRIC_LABELS[_metric]}</span>'
            f'<span class="mg-unit">{METRIC_UNITS[_metric]}</span></div>'
            f'<div class="mg-legend">'
            f'<span style="color:{_status_colors["WARNING"]}">▬ 경고 {_warning:g}</span>'
            f'<span style="color:{_status_colors["DANGER"]}">▬ 위험 {_danger:g}</span>'
            f'<span style="color:{_status_colors["FAULT"]}">▬ 고장 {_fault:g}</span>'
            f"</div></div>",
            unsafe_allow_html=True,
        )
        # 차트들만 테두리 박스 안에 담는다.
        with st.container(border=True):
            for _motor in _subset:
                _lower = _motor["status"].lower()
                st.markdown(
                    f'<div class="mg-row">'
                    f'<span class="mg-name">{_motor["motor_name"]}</span>'
                    f'<span class="status-badge status-{_lower}">{_motor["status"]}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
                _times, _sr = _series[_motor["motor_id"]]
                _vals = _sr.get(_metric, [])
                if _times and _vals:
                    _df = pd.DataFrame({"t": pd.to_datetime(_times, utc=True), "v": _vals})
                    # UTC → 표시 타임존, tz 제거(naive) — Vega가 브라우저 tz로 재해석하지 않게 한다.
                    _df["t"] = _df["t"].dt.tz_convert(DISPLAY_TIMEZONE).dt.tz_localize(None)
                    st.altair_chart(_chart(_df, _metric), use_container_width=True)
                else:
                    st.caption("데이터 없음")

# 표시 범위 셀렉트박스 입력을 읽기전용으로 만들어 검색/타이핑을 막는다(드롭다운 선택만 허용).
# CSS로는 keyboard 입력을 못 막으므로(드롭다운 열 때 입력이 자동 포커스됨) 부모 DOM에 접근하는
# 컴포넌트 스크립트로 readOnly를 건다. MutationObserver로 rerun 후 재렌더된 입력에도 재적용.
components.html(
    """
    <script>
    const doc = window.parent.document;
    const KEYS = ['graph_status', 'graph_loc', 'graph_model', 'graph_maxn'];
    function apply() {
      KEYS.forEach(function (k) {
        doc.querySelectorAll('.st-key-' + k + ' input').forEach(function (inp) {
          inp.readOnly = true;
          inp.setAttribute('inputmode', 'none');
        });
      });
    }
    apply();
    if (!doc.__graphSelReadonly) {
      doc.__graphSelReadonly = true;
      new MutationObserver(apply).observe(doc.body, { childList: true, subtree: true });
    }
    </script>
    """,
    height=0,
)
