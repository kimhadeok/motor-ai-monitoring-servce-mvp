"""메인 대시보드. 05_ui_screens.md §3 (상단 요약 / 모터 카드 / 이벤트 리스트)."""

import streamlit as st

from app.auth.session import end_session
from app.config import (
    DASHBOARD_EVENT_LIST_LIMIT,
    DASHBOARD_RECENT_WINDOW_HOURS,
    MOTOR_CARD_COLUMNS,
    SUMMARY_DATE_FORMAT,
    format_display,
    format_relative,
)
from app.db.connection import connection_scope
from app.services.company import build_summary
from app.services.events import list_company_events
from app.services.motors import list_company_motors
from app.ui.components import (
    event_list_header,
    event_row,
    motor_card,
    render_maintenance_dialog,
    render_report_dialog,
)

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
    # 계약 정보(회사·모터 수·서비스 시작일)는 매일 확인할 값이 아니므로 한 줄로 내린다.
    st.caption(
        f"{summary['company_name']} · 모터 {summary['motor_count']}대 · "
        f"서비스 시작 {format_display(summary['started_at'], SUMMARY_DATE_FORMAT)}"
        f" ({summary['operating_days']:,}일째)"
    )

    counts = summary["status_counts"]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "조치 필요",
        f"{summary['action_required']}대",
        delta=f"고장 {counts['FAULT']} · 위험 {counts['DANGER']}",
        delta_color="inverse" if summary["action_required"] else "off",
    )
    col2.metric(
        "주의 관찰",
        f"{summary['watch_count']}대",
        delta=f"정상 {summary['normal_count']}대",
        delta_color="off",
    )
    col3.metric(
        f"최근 {DASHBOARD_RECENT_WINDOW_HOURS}시간 이벤트",
        f"{summary['recent_event_count']}건",
        delta=f"악화 {summary['recent_worsened']} · 회복 {summary['recent_recovered']}",
        delta_color="off",
    )
    col4.metric(
        "마지막 수집",
        format_relative(summary["last_collected_at"]) if summary["last_collected_at"] else "-",
        delta="정상 수집 중" if summary["last_collected_at"] else "데이터 없음",
        delta_color="off",
    )

# 조치가 필요한 설비를 화면 맨 위에서 이름으로 알린다 — 카드를 훑어 찾게 하지 않는다.
# 확인 대기와 "확인은 끝났지만 수치가 여전히 고장 범위"는 담당자가 할 일이 달라 나눠 알린다.
_needs_confirm = [m for m in motors if m["fault_metrics"]]
_still_faulted = [m for m in motors if m["status"] == "FAULT" and not m["fault_metrics"]]
_dangered = [m for m in motors if m["status"] == "DANGER"]


def _names(items) -> str:
    return ", ".join(m["motor_name"] for m in items)


if _needs_confirm:
    st.error(
        f"**{_names(_needs_confirm)}** 가 고장(FAULT) 상태입니다. "
        "정비 후 아래 카드에서 완료 확인을 해주세요."
    )
if _still_faulted:
    st.error(
        f"**{_names(_still_faulted)}** 는 정비 완료 확인을 마쳤지만 "
        "여전히 고장 임계를 넘는 값이 들어오고 있습니다. 현장 재점검이 필요합니다."
    )
if _dangered:
    st.warning(f"**{_names(_dangered)}** 가 위험(DANGER) 상태입니다. 진단 리포트를 확인해주세요.")

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
render_maintenance_dialog()
