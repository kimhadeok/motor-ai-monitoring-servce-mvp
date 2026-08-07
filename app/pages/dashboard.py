"""메인 대시보드. 05_ui_screens.md §3 (상단 요약 / 모터 카드 / 이벤트 리스트)."""

import streamlit as st

from app.config import (
    DASHBOARD_EVENT_LIST_LIMIT,
    DASHBOARD_EVENT_STATUSES,
    DASHBOARD_MOTOR_CARD_LIMIT,
    DASHBOARD_RECENT_WINDOW_HOURS,
    MOTOR_CARD_COLUMNS,
    STATUS_KOREAN_LABELS,
    SUMMARY_DATE_FORMAT,
    format_display,
    format_relative,
)
from app.db.connection import connection_scope
from app.services.company import build_summary
from app.services.events import list_company_events
from app.services.motors import list_company_motors, select_priority_cards
from app.ui.components import (
    alert_banner,
    event_list_header,
    event_row,
    motor_card,
    page_header,
    render_maintenance_confirm,
    render_maintenance_dialog,
    render_report_dialog,
    summary_tiles,
)

page_header(active="dashboard")

_company_id = st.session_state.get("company_id")

with connection_scope() as conn:
    motors = list_company_motors(conn, _company_id)
    summary = build_summary(conn, _company_id, motors)
    events = list_company_events(
        conn, _company_id, DASHBOARD_EVENT_LIST_LIMIT, DASHBOARD_EVENT_STATUSES
    )

# --- §3.1 상단 요약 ---
if summary:
    # 계약 정보는 매일 확인할 값이 아니므로 한 줄로 내린다. 회사명은 상단 헤더에 있어 뺀다.
    st.caption(
        f"모터 {summary['motor_count']}대 · "
        f"서비스 시작 {format_display(summary['started_at'], SUMMARY_DATE_FORMAT)}"
        f" ({summary['operating_days']:,}일째)"
    )

    counts = summary["status_counts"]
    _collected = summary["last_collected_at"]

    # 타일 색이 곧 상태다 — 조치 필요가 0대면 초록, 있으면 상태색이라 숫자를 읽기 전에
    # 색으로 먼저 안다. 상태색은 카드·배너와 같은 팔레트를 쓴다.
    # 고장이 하나라도 있으면 FAULT(빨강), 위험만 있으면 DANGER(주황)로 구분한다 —
    # 2026-08-07 팔레트 재정리로 FAULT가 램프의 최상단이 되어 그대로 쓸 수 있다.
    if counts["FAULT"]:
        _action_tone = "fault"
    elif summary["action_required"]:
        _action_tone = "danger"
    else:
        _action_tone = "normal"

    summary_tiles(
        [
            {
                "label": "조치 필요",
                "value": summary["action_required"],
                "unit": "대",
                "sub": f"고장 {counts['FAULT']} · 위험 {counts['DANGER']}",
                "tone": _action_tone,
            },
            {
                "label": "주의 관찰",
                "value": summary["watch_count"],
                "unit": "대",
                "sub": f"정상 {summary['normal_count']}대",
                "tone": "warning" if summary["watch_count"] else "normal",
            },
            {
                "label": f"최근 {DASHBOARD_RECENT_WINDOW_HOURS}시간 이벤트",
                "value": summary["recent_event_count"],
                "unit": "건",
                "sub": f"악화 {summary['recent_worsened']} · 회복 {summary['recent_recovered']}",
                "tone": "brand",
            },
            {
                "label": "마지막 수집",
                "value": format_relative(_collected) if _collected else "-",
                "unit": "",
                "sub": "정상 수집 중" if _collected else "데이터 없음",
                "tone": "normal" if _collected else "danger",
            },
        ]
    )

# 조치가 필요한 설비를 화면 맨 위에서 이름으로 알린다 — 카드를 훑어 찾게 하지 않는다.
# 확인 대기와 "확인은 끝났지만 수치가 여전히 고장 범위"는 담당자가 할 일이 달라 나눠 알린다.
_needs_confirm = [m for m in motors if m["fault_metrics"]]
_still_faulted = [m for m in motors if m["status"] == "FAULT" and not m["fault_metrics"]]
_dangered = [m for m in motors if m["status"] == "DANGER"]


def _names(items) -> str:
    return ", ".join(m["motor_name"] for m in items)


if _needs_confirm:
    render_maintenance_confirm(_needs_confirm)
if _still_faulted:
    alert_banner(
        "FAULT",
        f"<b>{_names(_still_faulted)}</b> 는 정비 완료 확인을 마쳤지만 "
        "여전히 고장 임계를 넘는 값이 들어오고 있습니다. 현장 재점검이 필요합니다.",
    )
if _dangered:
    alert_banner(
        "DANGER",
        f"<b>{_names(_dangered)}</b> 가 위험(DANGER) 상태입니다. 진단 리포트를 확인해주세요.",
    )

st.subheader("모터 현황")

# 카드는 심각한 순으로 일부만 그린다 (config.DASHBOARD_MOTOR_CARD_LIMIT).
# 상단 요약과 배너는 위에서 전체 목록으로 이미 계산했으므로 집계는 그대로 정확하다.
_cards = select_priority_cards(motors, DASHBOARD_MOTOR_CARD_LIMIT)

if not motors:
    st.info("등록된 모터가 없습니다.")
else:
    if len(_cards) < len(motors):
        st.caption(
            f"조치가 급한 순으로 {len(_cards)}대만 표시합니다 "
            f"(전체 {len(motors)}대 · 목록 전체는 '모터 현황' 페이지에서 볼 수 있습니다)."
        )
    for row_start in range(0, len(_cards), MOTOR_CARD_COLUMNS):
        for column, motor in zip(
            st.columns(MOTOR_CARD_COLUMNS), _cards[row_start : row_start + MOTOR_CARD_COLUMNS]
        ):
            with column:
                motor_card(motor)

st.subheader("이벤트 발생 내역")

# 걸러서 보여준다는 사실을 화면이 직접 말한다 — 관찰 단계(WARNING) 전이가 안 보이는 것을
# 데이터 누락으로 오해하지 않도록. 전체 이력은 모터 상세(§4.4)에 있다.
_event_scope = " · ".join(STATUS_KOREAN_LABELS.get(s, s) for s in DASHBOARD_EVENT_STATUSES)

if not events:
    st.info(f"최근 {_event_scope} 이벤트가 없습니다.")
else:
    st.caption(
        f"{_event_scope} 전이 {len(events)}건 · "
        "주의(WARNING)를 포함한 전체 이력은 모터별 상세 페이지에서 볼 수 있습니다."
    )
    event_list_header(show_motor=True)
    for event in events:
        event_row(event, show_motor=True)

render_report_dialog()
render_maintenance_dialog()
