"""모터 그래프 페이지 (재정리안 1페이지).

지표 4열(온도/진동/전류/소음)에 필터링·정렬된 모터의 추이 라인차트를 세로로 나열한다.

- 표시 범위 필터: 상태 / 위치 / 모델명 / 표시 최대 수
- 정렬: 대표 상태 심각도 내림차순 (FAULT → DANGER → WARNING → NORMAL)
- 각 차트에 상태 임계선(경고/위험/고장)을 색으로 그려 값이 어느 구간인지 한눈에 보인다.
- 지표마다 라인 색과 열 영역(테두리)을 달리해 열을 구분한다.
- 숫자 Y축은 반복하지 않는다 — 열 헤더에 임계값을 한 번만 적고, 모든 차트가 같은 고정
  Y범위를 공유해 임계선 위치로 값을 읽는다(공간 절약).
"""

import streamlit as st
import streamlit.components.v1 as components

from app.config import (
    GRAPH_DEFAULT_MAX_MOTORS,
    GRAPH_MAX_MOTORS_OPTIONS,
    GRAPH_STATUS_FILTER_ORDER,
    GRAPH_TREND_BUCKETS,
    GRAPH_TREND_HOURS,
    STATUS_SEVERITY_RANK,
)
from app.db.connection import connection_scope
from app.services.motors import get_motor_metric_series, list_company_motor_status
from app.ui.charts import metric_graph_grid
from app.ui.components import page_header

page_header(active="graph")

_company_id = st.session_state.get("company_id")

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


# 4열 차트는 모터 상세(§4.1-A)와 공유한다 — 축 구성·임계선·Y범위 규칙이 한 벌만
# 있어야 두 화면의 그래프를 같은 눈으로 비교할 수 있다 (app/ui/charts.py).
metric_graph_grid(_subset, _series)

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
