"""메인 대시보드. 05_ui_screens.md §3 (상단 요약 / 모터 카드 / 이벤트 리스트)."""

import streamlit as st

from app.auth.session import end_session
from app.config import (
    DASHBOARD_EVENT_LIST_LIMIT,
    MOTOR_CARD_COLUMNS,
    SUMMARY_DATE_FORMAT,
    format_display,
)
from app.db.connection import connection_scope
from app.services.company import build_summary
from app.services.events import list_company_events
from app.services.motors import list_company_motors
from app.ui.components import event_list_header, event_row, motor_card, render_report_dialog

st.title("메인 대시보드")

with st.sidebar:
    st.write(f"담당자: {st.session_state.get('contact_name', '')}")
    if st.button("로그아웃"):
        end_session()
        st.rerun()

_company_id = st.session_state.get("company_id")

with connection_scope() as conn:
    motors = list_company_motors(conn, _company_id)
    summary = build_summary(conn, _company_id, motors)
    events = list_company_events(conn, _company_id, DASHBOARD_EVENT_LIST_LIMIT)

# --- §3.1 상단 요약 ---
if summary:
    st.caption(summary["company_name"])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("등록된 모터 수", f"{summary['motor_count']}대")
    col2.metric("서비스 시작 일자", format_display(summary["started_at"], SUMMARY_DATE_FORMAT))
    col3.metric("총 운영 일수", f"{summary['operating_days']:,}일")
    col4.metric(
        "주의 이상 모터 수",
        f"{summary['attention_count']}대",
        # 상태별 내역 (§3.1 — NORMAL 제외). 값이 0이어도 구성이 보이도록 전 상태를 표기한다.
        delta=" · ".join(f"{s} {n}" for s, n in summary["status_counts"].items()),
        delta_color="off",
    )

st.subheader("모터 현황")

if not motors:
    st.info("등록된 모터가 없습니다.")
else:
    for row_start in range(0, len(motors), MOTOR_CARD_COLUMNS):
        for column, motor in zip(
            st.columns(MOTOR_CARD_COLUMNS), motors[row_start : row_start + MOTOR_CARD_COLUMNS]
        ):
            with column:
                motor_card(motor)

st.subheader("이벤트 발생 내역")

if not events:
    st.info("최근 이벤트가 없습니다.")
else:
    st.caption(f"최근 {len(events)}건 · 상세 이력은 모터별 상세 페이지에서 볼 수 있습니다.")
    event_list_header(show_motor=True)
    for event in events:
        event_row(event, show_motor=True)

render_report_dialog()
