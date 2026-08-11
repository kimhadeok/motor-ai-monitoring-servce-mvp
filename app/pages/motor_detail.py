"""모터 상세 페이지. 05_ui_screens.md §4."""

import streamlit as st

from app.config import (
    DASHBOARD_EVENT_STATUSES,
    DETAIL_EVENT_PAGE_SIZE,
    GRAPH_TREND_BUCKETS,
    GRAPH_TREND_HOURS,
    METRIC_LABELS,
    STATUS_KOREAN_LABELS,
)
from app.db.connection import connection_scope
from app.services.events import count_motor_events, list_motor_events
from app.services.motors import (
    find_unconfirmed_fault_metrics,
    get_motor,
    get_motor_metric_series,
    get_representative_status,
    get_thresholds,
)
from app.ui.charts import metric_graph_grid
from app.ui.components import (
    event_list_header,
    event_row,
    maintenance_button,
    motor_info_table,
    page_header,
    render_maintenance_dialog,
    render_report_dialog,
    status_badge,
    threshold_table,
)
from app.ui.navigation import DASHBOARD_PAGE

_PAGE_KEY = "detail_event_page"

page_header()

motor_id = st.session_state.get("selected_motor_id")
company_id = st.session_state.get("company_id")

if not motor_id:
    st.title("모터 상세")
    st.warning("모터를 선택해 주세요. 대시보드의 모터 카드에서 [상세 보기]를 누르면 이동합니다.")
    if st.button("대시보드로 이동"):
        st.switch_page(DASHBOARD_PAGE)
    st.stop()

with connection_scope() as conn:
    motor = get_motor(conn, motor_id, company_id)

if motor is None:
    # 다른 회사 모터이거나 삭제된 모터 — 선택을 비우고 안내한다.
    st.session_state.pop("selected_motor_id", None)
    st.title("모터 상세")
    st.error("해당 모터를 찾을 수 없습니다.")
    if st.button("대시보드로 이동"):
        st.switch_page(DASHBOARD_PAGE)
    st.stop()

with connection_scope() as conn:
    representative_status = get_representative_status(conn, motor_id)
    fault_metrics = find_unconfirmed_fault_metrics(conn, motor_id)
    thresholds = get_thresholds(conn, motor_id)
    total_events = count_motor_events(conn, motor_id, DASHBOARD_EVENT_STATUSES)

title_col, badge_col = st.columns([4, 1])
title_col.title(motor["motor_name"])
with badge_col:
    st.write("")
    status_badge(representative_status)

# --- §4.1 기본 정보 ---
st.subheader("기본 정보")
motor_info_table(motor)

# --- §4.3 FAULT 정비 완료 처리 ---
if fault_metrics:
    labels = ", ".join(METRIC_LABELS.get(m, m) for m in fault_metrics)
    st.error(
        f"고장(FAULT) 상태입니다 — {labels}. "
        "정비 완료 확인 전까지 자동 상태 판정이 재개되지 않습니다."
    )

    maintenance_button(
        {"motor_id": motor_id, "motor_name": motor["motor_name"], "fault_metrics": fault_metrics},
        key_prefix="detail",
        type="primary",
    )

# --- §4.1-A 모터 그래프 ---
# 정비 완료 확인(§4.3) 아래에 둔다. 그래프가 위로 오면 설비가 멈춘 상태에서 가장 급한
# 조치 버튼이 화면 아래로 밀린다.
st.subheader("모터 그래프")
with connection_scope() as conn:
    _series = {motor_id: get_motor_metric_series(conn, motor_id, GRAPH_TREND_HOURS, GRAPH_TREND_BUCKETS)}

# 모터 그래프 페이지(§3-A)와 같은 차트를 쓴다. 다만 여기는 한 대뿐이라 차트마다 모터명을
# 반복하지 않는다 — 페이지 제목과 상단 상태 배지가 이미 알려준다.
metric_graph_grid(
    [{"motor_id": motor_id, "motor_name": motor["motor_name"], "status": representative_status}],
    _series,
    show_motor_row=False,
)
st.caption(f"최근 {GRAPH_TREND_HOURS}시간 추이입니다. 점선은 경고·위험·고장 임계선입니다.")

# --- §4.2 지표별 임계값 ---
st.subheader("지표별 임계값")
if not thresholds:
    st.info("등록된 임계값이 없습니다.")
else:
    threshold_table(thresholds)
    st.caption("이 설비에 설정된 기준값입니다. 모터마다 다르게 설정될 수 있습니다.")

# --- §4.4 이벤트 발생 내역 (페이지당 20개) ---
st.subheader("이벤트 발생 내역")

_event_scope = " · ".join(STATUS_KOREAN_LABELS.get(s, s) for s in DASHBOARD_EVENT_STATUSES)

if total_events == 0:
    st.info(f"{_event_scope} 이벤트가 없습니다.")
else:
    last_page = (total_events - 1) // DETAIL_EVENT_PAGE_SIZE
    page = min(st.session_state.get(_PAGE_KEY, 0), last_page)

    with connection_scope() as conn:
        events = list_motor_events(
            conn,
            motor_id,
            DETAIL_EVENT_PAGE_SIZE,
            page * DETAIL_EVENT_PAGE_SIZE,
            DASHBOARD_EVENT_STATUSES,
        )

    _caption = f"{_event_scope} 전이 {total_events}건"
    if last_page > 0:
        _caption += f" · {page + 1}/{last_page + 1} 페이지"
    st.caption(f"{_caption} · 이 모터의 이력만 모아서 보여줍니다.")

    event_list_header(show_motor=True)
    for event in events:
        event_row(event, show_motor=True)

    if last_page > 0:
        prev_col, label_col, next_col = st.columns([1, 2, 1])
        if prev_col.button("← 이전", disabled=page == 0, width="stretch"):
            st.session_state[_PAGE_KEY] = page - 1
            st.rerun()
        # 총 건수는 위 캡션이 이미 말한다 — 여기서는 현재 위치만 표시한다.
        label_col.markdown(
            f"<div style='text-align:center'>{page + 1} / {last_page + 1}</div>",
            unsafe_allow_html=True,
        )
        if next_col.button("다음 →", disabled=page == last_page, width="stretch"):
            st.session_state[_PAGE_KEY] = page + 1
            st.rerun()

render_report_dialog()
render_maintenance_dialog()
