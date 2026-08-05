"""모터 상세 페이지. 05_ui_screens.md §4."""

import pandas as pd
import streamlit as st

from app.auth.session import end_session
from app.config import (
    DETAIL_EVENT_PAGE_SIZE,
    DISPLAY_DATETIME_FORMAT,
    METRIC_LABELS,
    METRIC_UNITS,
    format_display,
    parse_utc,
)
from app.db.connection import connection_scope
from app.services.events import count_motor_events, list_motor_events
from app.services.motors import (
    confirm_maintenance,
    find_unconfirmed_fault_metrics,
    get_motor,
    get_representative_status,
    get_thresholds,
)
from app.ui.components import render_report_dialog, report_button, status_badge
from app.ui.navigation import DASHBOARD_PAGE

_PAGE_KEY = "detail_event_page"
_CONFIRM_KEY = "maintenance_confirm_metric"

with st.sidebar:
    st.write(f"담당자: {st.session_state.get('contact_name', '')}")
    if st.button("로그아웃"):
        end_session()
        st.rerun()

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
    total_events = count_motor_events(conn, motor_id)

title_col, badge_col = st.columns([4, 1])
title_col.title(motor["motor_name"])
with badge_col:
    st.write("")
    status_badge(representative_status)

if st.button("← 대시보드"):
    st.switch_page(DASHBOARD_PAGE)

# --- §4.1 기본 정보 ---
st.subheader("기본 정보")
info_left, info_right = st.columns(2)
info_left.write(f"**모터 ID** {motor['motor_id']}")
info_left.write(f"**모델명** {motor['model_name']}")
info_left.write(f"**시리얼 번호** {motor['serial_number'] or '-'}")
info_right.write(f"**설치 위치** {motor['installation_location']}")
info_right.write(f"**수집 주기** {motor['collection_interval_seconds']}초")
info_right.write(f"**등록일자** {format_display(parse_utc(motor['created_at']))}")

# --- §4.3 FAULT 정비 완료 처리 ---
if fault_metrics:
    labels = ", ".join(METRIC_LABELS.get(m, m) for m in fault_metrics)
    st.error(
        f"고장(FAULT) 상태입니다 — {labels}. "
        "정비 완료 확인 전까지 자동 상태 판정이 재개되지 않습니다."
    )

    for metric in fault_metrics:
        if st.button(f"{METRIC_LABELS.get(metric, metric)} 정비 완료 확인", key=f"fault-{metric}"):
            st.session_state[_CONFIRM_KEY] = metric
            st.rerun()

    # 어떤 지표를 확인 중인지 세션에 남겨둔다. 다이얼로그 안의 체크박스를 누르면 rerun이
    # 일어나는데, 버튼 클릭 여부로만 열면 그 순간 다이얼로그가 닫혀 확인 절차를 마칠 수 없다.
    _pending = st.session_state.get(_CONFIRM_KEY)
    if _pending in fault_metrics:

        @st.dialog("정비 완료 확인")
        def _confirm_dialog(metric: str) -> None:
            label = METRIC_LABELS.get(metric, metric)
            st.write(f"**{motor['motor_name']}**의 **{label}** 지표를 정비 완료로 처리합니다.")
            st.caption("확인 시 담당자 이력이 기록되고 해당 지표의 자동 상태 판정이 재개됩니다.")
            agreed = st.checkbox("정비가 완료되었음을 확인했습니다.")

            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button(
                "정비 완료 처리", type="primary", disabled=not agreed, use_container_width=True
            ):
                with connection_scope() as conn:
                    confirm_maintenance(conn, motor_id, metric, st.session_state.get("contact_id"))
                st.session_state.pop(_CONFIRM_KEY, None)
                st.session_state[_PAGE_KEY] = 0
                st.rerun()
            if cancel_col.button("취소", use_container_width=True):
                st.session_state.pop(_CONFIRM_KEY, None)
                st.rerun()

        _confirm_dialog(_pending)

# --- §4.2 지표별 임계값 ---
st.subheader("지표별 임계값")
if not thresholds:
    st.info("등록된 임계값이 없습니다.")
else:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "지표": METRIC_LABELS.get(t["metric_name"], t["metric_name"]),
                    "단위": METRIC_UNITS.get(t["metric_name"], ""),
                    "NORMAL": f"< {t['warning_range']:g}",
                    "WARNING": f"{t['warning_range']:g} ~ {t['danger_range']:g}",
                    "DANGER": f"{t['danger_range']:g} ~ {t['fault_range']:g}",
                    "FAULT": f"≥ {t['fault_range']:g}",
                }
                for t in thresholds
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )

# --- §4.4 이벤트 발생 내역 (페이지당 20개) ---
st.subheader("이벤트 발생 내역")

if total_events == 0:
    st.info("이벤트가 없습니다.")
else:
    last_page = (total_events - 1) // DETAIL_EVENT_PAGE_SIZE
    page = min(st.session_state.get(_PAGE_KEY, 0), last_page)

    with connection_scope() as conn:
        events = list_motor_events(
            conn, motor_id, DETAIL_EVENT_PAGE_SIZE, page * DETAIL_EVENT_PAGE_SIZE
        )

    _COLUMN_WIDTHS = [2, 1.5, 2.5, 1.5, 1]
    header = st.columns(_COLUMN_WIDTHS)
    for col, label in zip(header, ("발생 일시", "지표", "발생 사유", "모터 상태", "")):
        col.caption(label)

    for event in events:
        occurred_at, metric_col, reason, status, action = st.columns(_COLUMN_WIDTHS)
        occurred_at.write(format_display(parse_utc(event["created_at"]), DISPLAY_DATETIME_FORMAT))
        metric_col.write(METRIC_LABELS.get(event["metric_name"], event["metric_name"]))
        reason.write(event["trigger_reason"] or "-")
        with status:
            status_badge(event["new_status"])
        with action:
            report_button(event)

    if last_page > 0:
        prev_col, label_col, next_col = st.columns([1, 2, 1])
        if prev_col.button("← 이전", disabled=page == 0, use_container_width=True):
            st.session_state[_PAGE_KEY] = page - 1
            st.rerun()
        label_col.markdown(
            f"<div style='text-align:center'>{page + 1} / {last_page + 1} "
            f"(총 {total_events}건)</div>",
            unsafe_allow_html=True,
        )
        if next_col.button("다음 →", disabled=page == last_page, use_container_width=True):
            st.session_state[_PAGE_KEY] = page + 1
            st.rerun()

render_report_dialog()
