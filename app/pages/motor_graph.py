"""모터 그래프 페이지 (재정리안 1페이지).

지표 4열(온도/진동/전류/소음)에 회사 전체 모터의 최근 추이 라인차트를 세로로 나열한다.
200대 × 4지표 = 800차트를 한 번에 그리면 브라우저가 멈추므로, 한 화면에 GRAPH_PAGE_SIZE
대씩만 그리고 나머지는 범위 선택으로 넘긴다 (성능 근거는 계획서 참고).
"""

import math

import streamlit as st

from app.config import (
    GRAPH_PAGE_SIZE,
    GRAPH_TREND_BUCKETS,
    GRAPH_TREND_HOURS,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_UNITS,
)
from app.db.connection import connection_scope
from app.services.motors import get_motor_metric_series, list_company_motor_status
from app.ui.components import page_header

page_header(active="graph")

_company_id = st.session_state.get("company_id")

st.subheader("모터 그래프")
st.caption(f"지표별 최근 {GRAPH_TREND_HOURS}시간 추이 · 온도 · 진동 · 전류 · 소음")

with connection_scope() as conn:
    _motors = list_company_motor_status(conn, _company_id)

if not _motors:
    st.info("등록된 모터가 없습니다.")
    st.stop()

# --- 페이지네이션 ---
_total = len(_motors)
_page_count = math.ceil(_total / GRAPH_PAGE_SIZE)


def _range_label(page: int) -> str:
    start = page * GRAPH_PAGE_SIZE + 1
    end = min((page + 1) * GRAPH_PAGE_SIZE, _total)
    return f"모터 {start:,}–{end:,} / {_total:,}"


if _page_count > 1:
    _page = st.selectbox(
        "표시 범위", range(_page_count), format_func=_range_label, key="graph_page"
    )
else:
    _page = 0
    st.caption(_range_label(0))

_subset = _motors[_page * GRAPH_PAGE_SIZE : (_page + 1) * GRAPH_PAGE_SIZE]

# 현재 페이지 모터의 4지표 시계열만 조회한다 (모터당 쿼리 1회).
with connection_scope() as conn:
    _series = {
        motor["motor_id"]: get_motor_metric_series(
            conn, motor["motor_id"], GRAPH_TREND_HOURS, GRAPH_TREND_BUCKETS
        )
        for motor in _subset
    }

# --- 4열 라인차트 (지표별 열, 각 열에 현재 페이지 모터를 세로로) ---
_columns = st.columns(len(METRIC_NAMES))
for _column, _metric in zip(_columns, METRIC_NAMES):
    with _column:
        st.markdown(f"**{METRIC_LABELS[_metric]}** ({METRIC_UNITS[_metric]})")
        for _motor in _subset:
            st.caption(_motor["motor_name"])
            _values = _series[_motor["motor_id"]].get(_metric, [])
            if _values:
                st.line_chart(_values, height=110)
            else:
                st.caption("데이터 없음")
