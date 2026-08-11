"""모터 상세 페이지. 05_ui_screens.md §4.

**자동 갱신** (05 §5-2, 2026-08-11): 대시보드와 함께 자동 갱신을 적용한 두 화면 중 하나다.
한 대만 보는 화면이라 조회가 2회로 가장 가볍고, 커레이션 모터(수집 주기 10/20/30초)를 열면
그래프가 초 단위로 자라는 것이 그대로 보인다.

헤더·"모터 없음" 안내·다이얼로그는 fragment 밖에 둔다 — 갱신할 이유가 없고, 다이얼로그는
갱신 때마다 다시 그리면 열려 있는 창이 닫힌다. fragment 안의 버튼은 `st.rerun()`의 기본
scope가 `app`이라 바깥 다이얼로그를 정상적으로 연다.
"""

import streamlit as st

from app.config import (
    DASHBOARD_EVENT_STATUSES,
    DASHBOARD_REFRESH_INTERVAL_SECONDS,
    DETAIL_EVENT_PAGE_SIZE,
    GRAPH_TREND_BUCKETS,
    GRAPH_TREND_HOURS,
    METRIC_LABELS,
    STATUS_KOREAN_LABELS,
)
from app.db.connection import connection_scope
from app.services.events import count_motor_events, list_motor_events
from app.services.motors import (
    get_metric_status_view,
    get_motor,
    get_motor_metric_series,
    get_thresholds,
)
from app.services.runtime_tick import run_tick
from app.ui.charts import metric_graph_grid
from app.ui.components import (
    detail_header,
    event_list_header,
    event_row,
    maintenance_button,
    motor_info_table,
    page_header,
    refresh_countdown,
    render_maintenance_dialog,
    render_report_dialog,
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

@st.fragment(run_every=DASHBOARD_REFRESH_INTERVAL_SECONDS)
def render_live_detail() -> None:
    """조회부터 렌더까지 — 이 함수만 주기적으로 다시 실행된다."""
    with connection_scope() as conn:
        # 갱신 주기마다 경과분 텔레메트리를 이어 붙인다 (services/runtime_tick.py).
        run_tick(conn, company_id)

        # 지표별 상태·미확인 FAULT·대표 상태를 한 번에 받는다 — 종전에는 같은 쿼리를
        # 두 번씩 돌렸다(자동 갱신으로 10초마다 반복되는 경로다).
        metric_statuses, fault_metrics, representative_status = get_metric_status_view(
            conn, motor_id
        )
        thresholds = get_thresholds(conn, motor_id)
        total_events = count_motor_events(conn, motor_id, DASHBOARD_EVENT_STATUSES)
        series = {
            motor_id: get_motor_metric_series(
                conn, motor_id, GRAPH_TREND_HOURS, GRAPH_TREND_BUCKETS
            )
        }

    # 갱신 카운터는 fragment 안 맨 위에 둔다 — 이 함수가 다시 실행될 때마다 새 시작 시각으로
    # 다시 만들어져야 카운트가 재시작한다.
    refresh_countdown(DASHBOARD_REFRESH_INTERVAL_SECONDS)

    # 제목 옆에 **상태별 지표 배지**를 붙인다 — "FAULT (온도, 소음) DANGER (진동)".
    # 대표 상태 하나만 보여주면 무엇 때문에 위험한지 알 수 없다 (2026-08-11 사용자 지적).
    detail_header(motor["motor_name"], metric_statuses)

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
            {
                "motor_id": motor_id,
                "motor_name": motor["motor_name"],
                "fault_metrics": fault_metrics,
            },
            key_prefix="detail",
            type="primary",
        )

    # --- §4.1-A 모터 그래프 ---
    # 정비 완료 확인(§4.3) 아래에 둔다. 그래프가 위로 오면 설비가 멈춘 상태에서 가장 급한
    # 조치 버튼이 화면 아래로 밀린다.
    st.subheader("모터 그래프")
    # 모터 그래프 페이지(§3-A)와 같은 차트를 쓴다. 다만 여기는 한 대뿐이라 차트마다 모터명을
    # 반복하지 않는다 — 페이지 제목과 상단 상태 배지가 이미 알려준다.
    metric_graph_grid(
        [
            {
                "motor_id": motor_id,
                "motor_name": motor["motor_name"],
                "status": representative_status,
            }
        ],
        series,
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

    event_scope = " · ".join(STATUS_KOREAN_LABELS.get(s, s) for s in DASHBOARD_EVENT_STATUSES)

    if total_events == 0:
        st.info(f"{event_scope} 이벤트가 없습니다.")
        return

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

    caption = f"{event_scope} 전이 {total_events}건"
    if last_page > 0:
        caption += f" · {page + 1}/{last_page + 1} 페이지"
    st.caption(f"{caption} · 이 모터의 이력만 모아서 보여줍니다.")

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


render_live_detail()

# 다이얼로그는 fragment 밖에 둔다 — 갱신 때마다 다시 그리면 열려 있는 창이 닫힌다.
render_report_dialog()
render_maintenance_dialog()
