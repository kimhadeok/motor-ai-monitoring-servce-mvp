"""재사용 UI 조각. 05_ui_screens.md 기준."""

import streamlit as st

from app.config import (
    DATA_FLOW_NODES,
    REPORT_DATE_FORMAT,
    REPORT_SESSION_ID_FORMAT,
    REPORT_TIME_FORMAT,
    REPORT_VIEWER_HEIGHT_PX,
    format_display,
    parse_utc,
)
from app.reports.service import REPORTABLE_STATUSES, get_report

_REPORT_VIEW_KEY = "report_view"


def status_badge(status: str) -> None:
    st.markdown(
        f'<span class="status-badge status-{status.lower()}">{status}</span>',
        unsafe_allow_html=True,
    )


def data_flow(status: str) -> None:
    """모터 → API → AI Agent 데이터 흐름 표시 (05_ui_screens.md §3.2).

    연결선의 그라데이션을 흘려보내 데이터가 이동하는 것처럼 보이게 한다. 색상은 모터
    대표 상태를 따른다. 외부 라이브러리(streamlit-lottie)나 네트워크 자산 없이 CSS만
    쓰므로 오프라인·배포 환경에서 동일하게 동작한다.
    """
    nodes = [
        f'<div class="node"><span class="icon">{icon}</span>'
        f'<span class="label">{label}</span></div>'
        for icon, label in DATA_FLOW_NODES
    ]
    # 노드 사이마다 연결선을 끼운다. 두 번째 선은 반 주기 늦게 출발해 흐름 방향이 드러난다.
    links = ['<div class="link"></div>', '<div class="link delayed"></div>']
    parts = [nodes[0]]
    for i, node in enumerate(nodes[1:]):
        parts.append(links[i % len(links)])
        parts.append(node)

    st.markdown(
        f'<div class="data-flow status-{status.lower()}">{"".join(parts)}</div>',
        unsafe_allow_html=True,
    )


def motor_card(motor: dict) -> None:
    """05_ui_screens.md §3.2 모터별 카드.

    데이터 흐름 애니메이션, 대표 상태 배지, 최근 상태 변경 일시를 보여주고
    [상세 보기]를 누르면 상세 페이지로 이동한다.
    """
    from app.ui.navigation import MOTOR_DETAIL_PAGE  # 순환 import 방지를 위한 지연 import

    motor_id = motor["motor_id"]
    with st.container(border=True):
        data_flow(motor["status"])
        st.write(f"**{motor['motor_name']}**")
        st.caption(motor["model_name"])
        status_badge(motor["status"])

        last_changed = motor.get("last_changed_at")
        st.caption(
            format_display(parse_utc(last_changed)) if last_changed else "상태 변경 이력 없음"
        )

        if st.button("상세 보기", key=f"motor-{motor_id}", use_container_width=True):
            st.session_state["selected_motor_id"] = motor_id
            st.switch_page(MOTOR_DETAIL_PAGE)


def _report_basename(log) -> str:
    """리포트 파일명. 본문에 찍히는 세션 ID와 같은 규칙을 쓴다 (06 §2.1)."""
    event_dt = parse_utc(log["created_at"])
    return REPORT_SESSION_ID_FORMAT.format(
        motor_id=log["motor_id"],
        date=format_display(event_dt, REPORT_DATE_FORMAT),
        time=format_display(event_dt, REPORT_TIME_FORMAT),
    )


def report_button(log) -> None:
    """05_ui_screens.md §3.3 리포트 버튼.

    노출 조건은 `new_status`가 DANGER/FAULT인 로그. PDF를 요청 시점에 만드는 방식이라
    최초에는 `report_pdf`가 항상 NULL이므로 이를 조건으로 쓸 수 없다.

    클릭 결과는 세션에 담고 다이얼로그로 띄운다. 리스트 행 안에서 바로 HTML을 렌더하면
    표 레이아웃이 무너지기 때문이다.
    """
    if log["new_status"] not in REPORTABLE_STATUSES:
        return

    log_id = log["log_id"]
    if st.button("보고서", key=f"report-{log_id}", use_container_width=True):
        with st.spinner("리포트를 준비하는 중입니다…"):
            result = get_report(log_id)
        st.session_state[_REPORT_VIEW_KEY] = {
            "basename": _report_basename(log),
            "motor_name": log["motor_name"],
            "result": result,
        }
        st.rerun()


def render_report_dialog() -> None:
    """직전 클릭으로 준비된 리포트를 다이얼로그로 표시한다. 페이지 하단에서 1회 호출."""
    view = st.session_state.pop(_REPORT_VIEW_KEY, None)
    if view is None:
        return

    @st.dialog(f"진단 리포트 — {view['motor_name']}", width="large")
    def _show() -> None:
        result = view["result"]
        if result is None:
            st.warning("리포트를 생성할 수 없습니다. 관련 데이터가 남아 있지 않습니다.")
            return

        kind, payload = result
        if kind == "pdf":
            st.success("PDF 리포트가 준비되었습니다.")
            st.download_button(
                "PDF 다운로드",
                data=payload,
                file_name=f"{view['basename']}.pdf",
                mime="application/pdf",
            )
            return

        # PDF 생성이 불가한 환경 — 저장된 HTML을 그대로 보여준다 (06 §1)
        st.caption("이 환경에서는 PDF를 만들 수 없어 HTML로 표시합니다.")
        # HTML 문자열을 그대로 넘기면 srcdoc으로 렌더된다 — 파일시스템을 경유하지 않는다(05 §3.3).
        # st.components.v1.html은 2026-06-01자로 제거 예고된 API라 st.iframe을 쓴다.
        st.iframe(payload, height=REPORT_VIEWER_HEIGHT_PX)
        st.download_button(
            "HTML 다운로드",
            data=payload,
            file_name=f"{view['basename']}.html",
            mime="text/html",
        )

    _show()
