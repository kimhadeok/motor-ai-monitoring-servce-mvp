"""메인 대시보드. 05_ui_screens.md §3 (상단 요약 / 모터 카드 / 이벤트 리스트).

**자동 갱신** (05 §5-2, 2026-08-11): 데이터에 기대는 부분 전체를 하나의
`st.fragment(run_every=...)`로 묶어 `DASHBOARD_REFRESH_INTERVAL_SECONDS`마다 그 영역만
다시 그린다. 헤더·내비게이션·다이얼로그는 fragment 밖에 둔다 — 재실행할 이유가 없고,
갱신 때마다 다시 그리면 열려 있는 다이얼로그가 닫힌다.

요약·배너·카드·이벤트를 **한 fragment로 묶은 이유**: 넷이 같은 조회 결과(`motors`)를
공유한다. 나누면 조회를 네 번 하게 되고, 갱신 시점이 어긋나 상단 요약과 카드가 서로 다른
순간을 말하게 된다.
"""

import streamlit as st

from app.config import (
    DASHBOARD_EVENT_LIST_LIMIT,
    DASHBOARD_EVENT_STATUSES,
    DASHBOARD_MOTOR_CARD_LIMIT,
    DASHBOARD_RECENT_WINDOW_HOURS,
    DASHBOARD_REFRESH_INTERVAL_SECONDS,
    MOTOR_CARD_COLUMNS,
    STATUS_KOREAN_LABELS,
    SUMMARY_COLLECTED_FORMAT,
    SUMMARY_DATE_FORMAT,
    format_display,
    format_relative,
)
from app.db.connection import connection_scope
from app.services.company import build_summary
from app.services.events import list_company_events
from app.services.motors import (
    attach_card_trends,
    list_company_motors,
    select_priority_cards,
)
from app.services.runtime_tick import run_tick
from app.ui.components import (
    alert_banner,
    event_list_header,
    event_row,
    motor_card,
    page_header,
    refresh_countdown,
    render_maintenance_confirm,
    render_maintenance_dialog,
    render_report_dialog,
    summary_tiles,
)

page_header(active="dashboard")

_company_id = st.session_state.get("company_id")


@st.fragment(run_every=DASHBOARD_REFRESH_INTERVAL_SECONDS)
def render_live_dashboard() -> None:
    """조회부터 렌더까지 — 이 함수만 주기적으로 다시 실행된다."""
    with connection_scope() as conn:
        # 갱신 주기마다 경과분 텔레메트리를 이어 붙인다. 이게 없으면 화면은 다시 그려지지만
        # 숫자가 그대로여서 담당자 눈에는 아무 일도 일어나지 않는다
        # (services/runtime_tick.py 모듈 주석).
        run_tick(conn, _company_id)

        motors = list_company_motors(conn, _company_id)
        # 카드는 심각한 순으로 일부만 그린다 (config.DASHBOARD_MOTOR_CARD_LIMIT).
        # 상단 요약과 배너는 전체 목록으로 계산하므로 집계는 그대로 정확하다.
        # 스파크라인 추이는 **여기서 고른 카드에만** 채운다 — 그리지 않을 모터의 GROUP BY를
        # 돌리지 않기 위해서다(services/motors.py `list_company_motors` docstring 참조).
        _cards = attach_card_trends(conn, select_priority_cards(motors, DASHBOARD_MOTOR_CARD_LIMIT))
        summary = build_summary(conn, _company_id, motors)
        events = list_company_events(
            conn, _company_id, DASHBOARD_EVENT_LIST_LIMIT, DASHBOARD_EVENT_STATUSES
        )

    # 갱신 카운터는 fragment 안 맨 위에 둔다 — 이 함수가 다시 실행될 때마다 새 시작 시각으로
    # 다시 만들어져야 카운트가 재시작한다.
    refresh_countdown(DASHBOARD_REFRESH_INTERVAL_SECONDS)
    _render(motors, _cards, summary, events)


def _names(items) -> str:
    return ", ".join(m["motor_name"] for m in items)


def _render(motors, cards, summary, events) -> None:
    # --- §3.1 상단 요약 ---
    if summary:
        # 계약 정보는 매일 확인할 값이 아니므로 한 줄로 내린다. 회사명은 상단 헤더에 있어 뺀다.
        st.caption(
            f"모터 {summary['motor_count']}대 · "
            f"서비스 시작 {format_display(summary['started_at'], SUMMARY_DATE_FORMAT)}"
            f" ({summary['operating_days']:,}일째)"
        )

        counts = summary["status_counts"]
        collected = summary["last_collected_at"]

        # **상태 한 칸에 타일 하나** (2026-08-12 사용자 요청). 종전에는 `조치 필요`(DANGER+FAULT
        # 합산)와 `최근 24시간 이벤트`(악화/회복)로 묶여 있었는데, 두 숫자 모두 집계 규칙을
        # 알아야 읽혔다 — 왜 17인지, 무엇이 '악화'인지가 화면에 없었다. 상태별로 나누면
        # 규칙이 사라지고, 헤더 상태 범례(§2-1)와 같은 어휘·같은 색으로 1:1 대응된다.
        #
        # FAULT와 DANGER를 나눈 이유: 대응이 다르다. FAULT는 정비 완료 확인이 필요한 정지
        # 상태(아래 배너·버튼이 그것을 처리한다), DANGER는 가동 중 악화다.
        #
        # 색은 항상 그 상태색이 아니다 — **0대면 초록**으로 준다. 고장 0대가 빨간 타일로
        # 보이면 숫자를 읽기 전에는 문제가 있는 것처럼 보인다.
        recent_into = summary["recent_worsened_into"]
        window = DASHBOARD_RECENT_WINDOW_HOURS

        def _state_tile(status: str, label: str) -> dict:
            count = counts[status]
            # 보조줄 = 한글 상태명 + 최근 창의 악화 유입. 상태 4칸이 전부 '지금' 스냅샷이라
            # 이것이 없으면 "밤사이 무슨 일이 있었나"에 답하는 숫자가 화면에서 사라진다.
            korean = STATUS_KOREAN_LABELS[status]
            new_count = recent_into.get(status, 0)
            sub = f"{korean} · {window}h +{new_count}" if new_count else korean
            return {
                "label": label,
                # 값 앞에 영문 상태명을 붙인다 — 카드·차트 배지와 같은 말로 이어 준다.
                "status_key": status,
                "value": count,
                "unit": "대",
                "sub": sub,
                "tone": status.lower() if count else "normal",
            }

        summary_tiles(
            [
                _state_tile("FAULT", "바로 조치 필요"),
                _state_tile("DANGER", "조치 필요"),
                _state_tile("WARNING", "관찰 필요"),
                {
                    "label": "이상 없음",
                    "status_key": "NORMAL",
                    "value": summary["normal_count"],
                    "unit": "대",
                    "sub": STATUS_KOREAN_LABELS["NORMAL"],
                    "tone": "normal",
                },
                {
                    # 큰 글씨는 상대 시각이다 — 절대 시각만 두면 "몇 분 전이지?"를 암산해야
                    # 신선도를 알 수 있다. 정확한 시각은 보조줄에 함께 싣는다.
                    "label": "마지막 수집",
                    "value": format_relative(collected) if collected else "-",
                    "unit": "",
                    "sub": (
                        f"{format_display(collected, SUMMARY_COLLECTED_FORMAT)} · 정상 수집 중"
                        if collected
                        else "데이터 없음"
                    ),
                    "tone": "normal" if collected else "danger",
                },
            ]
        )

    # 조치가 필요한 설비를 화면 맨 위에서 이름으로 알린다 — 카드를 훑어 찾게 하지 않는다.
    # 확인 대기와 "확인은 끝났지만 수치가 여전히 고장 범위"는 담당자가 할 일이 달라 나눠 알린다.
    needs_confirm = [m for m in motors if m["fault_metrics"]]
    still_faulted = [m for m in motors if m["status"] == "FAULT" and not m["fault_metrics"]]
    dangered = [m for m in motors if m["status"] == "DANGER"]

    if needs_confirm:
        render_maintenance_confirm(needs_confirm)
    if still_faulted:
        alert_banner(
            "FAULT",
            f"<b>{_names(still_faulted)}</b> 는 정비 완료 확인을 마쳤지만 "
            "여전히 고장 임계를 넘는 값이 들어오고 있습니다. 현장 재점검이 필요합니다.",
        )
    if dangered:
        alert_banner(
            "DANGER",
            f"<b>{_names(dangered)}</b> 가 위험(DANGER) 상태입니다. 진단 리포트를 확인해주세요.",
        )

    st.subheader("모터 현황")

    if not motors:
        st.info("등록된 모터가 없습니다.")
    else:
        if len(cards) < len(motors):
            st.caption(
                f"조치가 급한 순으로 {len(cards)}대만 표시합니다 "
                f"(전체 {len(motors)}대 · 목록 전체는 '모터 현황' 페이지에서 볼 수 있습니다)."
            )
        for row_start in range(0, len(cards), MOTOR_CARD_COLUMNS):
            for column, motor in zip(
                st.columns(MOTOR_CARD_COLUMNS), cards[row_start : row_start + MOTOR_CARD_COLUMNS]
            ):
                with column:
                    motor_card(motor)

    st.subheader("이벤트 발생 내역")

    # 걸러서 보여준다는 사실을 화면이 직접 말한다 — 관찰 단계(WARNING) 전이가 안 보이는 것을
    # 데이터 누락으로 오해하지 않도록. 모터 상세(§4.4)는 같은 규칙으로 그 모터 것만 보여준다.
    event_scope = " · ".join(STATUS_KOREAN_LABELS.get(s, s) for s in DASHBOARD_EVENT_STATUSES)

    if not events:
        st.info(f"최근 {event_scope} 이벤트가 없습니다.")
    else:
        st.caption(
            f"{event_scope} 전이 {len(events)}건 · "
            "모터별 이력은 상세 페이지에서 볼 수 있습니다."
        )
        event_list_header(show_motor=True)
        for event in events:
            event_row(event, show_motor=True)


render_live_dashboard()

# 다이얼로그는 fragment 밖에 둔다 — 갱신 때마다 다시 그리면 열려 있는 창이 닫힌다.
render_report_dialog()
render_maintenance_dialog()
