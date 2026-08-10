"""모터 상세 페이지. 05_ui_screens.md §4."""

import pandas as pd
import streamlit as st

from app.config import (
    DETAIL_EVENT_PAGE_SIZE,
    METRIC_LABELS,
    METRIC_UNITS,
    format_display,
    parse_utc,
)
from app.db.connection import connection_scope
from app.services.events import count_motor_events, list_motor_events
from app.services.motors import (
    find_unconfirmed_fault_metrics,
    get_motor,
    get_representative_status,
    get_thresholds,
)
from app.ui.components import (
    event_list_header,
    event_row,
    maintenance_button,
    page_header,
    render_maintenance_dialog,
    render_report_dialog,
    status_badge,
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
    total_events = count_motor_events(conn, motor_id)

# 뒤로가기는 모터명 위에 둔다 — 페이지 최상단에서 대시보드로 돌아갈 경로를 먼저 보인다.
if st.button("← 대시보드"):
    st.switch_page(DASHBOARD_PAGE)

title_col, badge_col = st.columns([4, 1])
title_col.title(motor["motor_name"])
with badge_col:
    st.write("")
    status_badge(representative_status)

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

    maintenance_button(
        {"motor_id": motor_id, "motor_name": motor["motor_name"], "fault_metrics": fault_metrics},
        key_prefix="detail",
        type="primary",
    )

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

    # 대시보드(§3.3)와 같은 자리·같은 형식의 안내 줄. 대시보드는 조치가 필요한 전이만
    # 걸러 보여주고 "전체 이력은 상세에서"라고 안내하므로, 이쪽에서도 무엇을 보고 있는지를
    # 같은 방식으로 말해준다. 건수는 페이지가 없을 때도 항상 보여준다 —
    # 종전에는 20건을 넘겨 페이지네이션이 생겨야만 총 건수를 알 수 있었다.
    _caption = f"전체 상태 전이 {total_events}건"
    if last_page > 0:
        _caption += f" · {page + 1}/{last_page + 1} 페이지"
    st.caption(f"{_caption} · 메인 대시보드는 이 중 고장·위험 전이만 모아서 보여줍니다.")

    event_list_header(show_motor=False)
    for event in events:
        event_row(event, show_motor=False)

    if last_page > 0:
        prev_col, label_col, next_col = st.columns([1, 2, 1])
        if prev_col.button("← 이전", disabled=page == 0, use_container_width=True):
            st.session_state[_PAGE_KEY] = page - 1
            st.rerun()
        # 총 건수는 위 캡션이 이미 말한다 — 여기서는 현재 위치만 표시한다.
        label_col.markdown(
            f"<div style='text-align:center'>{page + 1} / {last_page + 1}</div>",
            unsafe_allow_html=True,
        )
        if next_col.button("다음 →", disabled=page == last_page, use_container_width=True):
            st.session_state[_PAGE_KEY] = page + 1
            st.rerun()

render_report_dialog()
render_maintenance_dialog()
