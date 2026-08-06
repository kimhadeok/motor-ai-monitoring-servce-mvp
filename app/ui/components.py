"""재사용 UI 조각. 05_ui_screens.md 기준."""

import streamlit as st

from app.config import (
    CARD_HIGHLIGHT_STATUSES,
    DATA_FLOW_NODES,
    DISPLAY_DATETIME_FORMAT,
    EVENT_COLUMN_WIDTHS,
    EVENT_COLUMN_WIDTHS_WITH_MOTOR,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_UNITS,
    MOTOR_CARD_BUTTON_PREFIX,
    REPORT_DATE_FORMAT,
    REPORT_SESSION_ID_FORMAT,
    REPORT_TIME_FORMAT,
    REPORT_VIEWER_HEIGHT_PX,
    SERVICE_ICON,
    SERVICE_NAME,
    SPARKLINE_HEIGHT_PX,
    SPARKLINE_WIDTH_PX,
    STATUS_CARD_BUTTON_PREFIX,
    THEME_HINT,
    THEME_HINT_TOOLTIP,
    THEME_LABELS,
    TREND_CHANGE_THRESHOLD,
    TREND_WINDOW_HOURS,
    format_display,
    format_relative,
    parse_utc,
)
from app.db.connection import connection_scope
from app.reports.service import REPORTABLE_STATUSES, get_report
from app.services.events import FLAT, RECOVER, WORSE, transition_direction
from app.services.motors import confirm_maintenance
from app.ui.theme import current_theme, palette

_REPORT_VIEW_KEY = "report_view"


def _page_nav(active: str | None) -> None:
    """상단 페이지 이동 내비 (메인 대시보드 / 모터 그래프 / 모터 현황).

    사이드바를 숨긴 구조라 메인 페이지 3개를 오갈 경로가 필요하다. 현재 페이지는
    primary 버튼으로 강조하고, 나머지는 클릭 시 해당 페이지로 전환한다.
    """
    from app.ui.navigation import HEADER_NAV_PAGES  # 순환 import 방지를 위한 지연 import

    columns = st.columns([1.3, 1.3, 1.3, 5.1])
    for (key, label, path), column in zip(HEADER_NAV_PAGES, columns):
        with column:
            if st.button(
                label,
                key=f"nav-{key}",
                type="primary" if key == active else "secondary",
                use_container_width=True,
            ) and key != active:
                st.switch_page(path)


def page_header(active: str | None = None) -> None:
    """상단 헤더 — 좌측 서비스명, 우측 로그인 정보와 로그아웃 (05 §5-4).

    사이드바 대신 일반 웹 서비스처럼 상단에 둔다. 로그인 화면에서 세운 브랜드가
    로그인 후에도 이어지고, 담당자는 지금 어느 회사 계정으로 보고 있는지 늘 확인할 수 있다.

    `active`는 페이지 이동 내비에서 현재 페이지를 강조하는 키다. None이면 내비를 그리지
    않는다 (모터 상세처럼 자체 뒤로가기를 갖는 하위 화면).
    """
    from app.auth.session import end_session  # 순환 import 방지를 위한 지연 import

    brand_col, info_col, action_col = st.columns([4.6, 4.2, 1.2], vertical_alignment="center")

    brand_col.markdown(
        f'<div class="app-brand"><span class="icon">{SERVICE_ICON}</span>'
        f'<span class="name">{SERVICE_NAME}</span></div>',
        unsafe_allow_html=True,
    )

    # 로그인 정보와 테마 안내를 한 블록에 담는다. 컬럼으로 나누면 폭이 좁아질 때
    # 한쪽이 밀려 다른 쪽 자리를 차지한다.
    # 앱에서 테마를 바꾸는 API가 없어 현재 테마와 변경 위치만 알린다 (05 §5-5).
    _icon, _label = THEME_LABELS[current_theme()]
    info_col.markdown(
        f'<div class="app-side">'
        f'<div class="app-user">'
        f'<span class="company">{st.session_state.get("company_name", "")}</span>'
        f'<span class="contact">{st.session_state.get("contact_name", "")}</span>'
        f"</div>"
        f'<div class="app-theme" title="{THEME_HINT_TOOLTIP}">'
        f'<span class="now">{_icon} {_label}</span>'
        f'<span class="hint">{THEME_HINT}</span>'
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    with action_col:
        if st.button("로그아웃", use_container_width=True):
            end_session()
            st.rerun()

    if active is not None:
        _page_nav(active)

    st.markdown('<div class="app-header-rule"></div>', unsafe_allow_html=True)


def alert_banner(status: str, message: str) -> None:
    """상태색을 그대로 쓰는 경고 배너 (05 §3.1).

    `st.error`/`st.warning`은 빨강·노랑 두 가지뿐이라 카드의 상태색(DANGER 빨강,
    FAULT 짙은 회색)과 어긋난다. 같은 상태를 두 화면 요소가 다른 색으로 말하면
    담당자가 심각도를 잘못 읽는다.
    """
    st.markdown(
        f'<div class="alert-banner status-{status.lower()}">{message}</div>',
        unsafe_allow_html=True,
    )


def status_badge(status: str) -> None:
    st.markdown(
        f'<span class="status-badge status-{status.lower()}">{status}</span>',
        unsafe_allow_html=True,
    )


def _data_flow_html(status: str) -> str:
    """모터 → API → AI Agent 데이터 흐름 (05_ui_screens.md §3.2).

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

    return f'<div class="data-flow status-{status.lower()}">{"".join(parts)}</div>'


def _sparkline_svg(values: list[float], status: str) -> str:
    """추이 스파크라인. 외부 차트 라이브러리 없이 인라인 SVG로 그린다.

    카드마다 하나씩 들어가므로 plotly를 띄우면 렌더 비용이 카드 수만큼 붙는다.
    """
    width, height = SPARKLINE_WIDTH_PX, SPARKLINE_HEIGHT_PX
    pad = 3
    low, high = min(values), max(values)
    span = high - low or 1.0  # 값이 모두 같으면 가운데 수평선

    step = (width - pad * 2) / max(len(values) - 1, 1)
    points = " ".join(
        f"{pad + i * step:.1f},{pad + (height - pad * 2) * (1 - (v - low) / span):.1f}"
        for i, v in enumerate(values)
    )
    # SVG 획 색은 CSS 변수를 못 쓰므로 현재 테마 팔레트에서 직접 가져온다.
    status_colors = palette()["status"]
    color = status_colors.get(status, status_colors["NORMAL"])
    return (
        f'<svg class="sparkline" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" preserveAspectRatio="none" aria-hidden="true">'
        f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.6" '
        f'stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def _trend_direction(values: list[float]) -> tuple[str, str]:
    """추세 방향 (기호, 설명). 앞 1/3 평균과 뒤 1/3 평균을 비교한다."""
    if len(values) < 4:
        return "", ""
    third = max(len(values) // 3, 1)
    head = sum(values[:third]) / third
    tail = sum(values[-third:]) / third
    if head == 0:
        return "", ""

    change = (tail - head) / abs(head)
    if change > TREND_CHANGE_THRESHOLD:
        return "↑", "상승"
    if change < -TREND_CHANGE_THRESHOLD:
        return "↓", "하락"
    return "→", "유지"


def _metric_gauge(reading: dict) -> str:
    """고장 임계를 100%로 둔 게이지. 주의·위험 임계 위치에 눈금을 찍는다."""
    return (
        f'<div class="metric-gauge status-{reading["status"].lower()}">'
        f'<div class="fill" style="width:{reading["ratio"] * 100:.1f}%"></div>'
        f'<div class="tick" style="left:{reading["warning_at"] * 100:.1f}%"></div>'
        f'<div class="tick" style="left:{reading["danger_at"] * 100:.1f}%"></div>'
        f"</div>"
    )


def _metric_html(reading: dict) -> str:
    """지표 1건 — 이름, 값, 게이지, (이상일 때만) 고장까지 남은 여유.

    모든 카드가 4개 지표를 같은 순서로 담아 높이가 일정해진다. 이상 지표는 위치가 아니라
    색·굵기와 여유 문구로 구분한다.
    """
    abnormal = reading["status"] in CARD_HIGHLIGHT_STATUSES
    remaining = reading["remaining"]

    # 설명 줄은 모든 지표에 둔다. 이상일 때만 넣으면 카드마다 줄 수가 달라져 높이가 어긋난다.
    if not abnormal:
        note = f"고장 임계의 {reading['ratio'] * 100:.0f}%"
    elif remaining > 0:
        note = f"고장까지 {remaining:,.1f}{reading['unit']} 남음"
    else:
        note = "고장 임계 초과"

    return (
        f'<div class="metric-block status-{reading["status"].lower()}'
        f'{" abnormal" if abnormal else ""}">'
        f'<div class="metric-row">'
        f'<span class="metric-name">{reading["label"]}</span>'
        f'<span class="metric-value">{reading["value"]:,.1f}'
        f'<span class="metric-unit">{reading["unit"]}</span></span>'
        f"</div>"
        f"{_metric_gauge(reading)}"
        f'<div class="metric-note">{note}</div>'
        f"</div>"
    )


def _trend_html(reading: dict, trend: list[float]) -> str:
    """카드 하단 추이 — 가장 심각한 지표 하나. 정상 카드에도 넣어 높이를 맞춘다."""
    if not trend:
        return ""
    arrow, word = _trend_direction(trend)
    return (
        f'<div class="metric-trend">'
        f'<span class="trend-label">{reading["label"]}</span>'
        f'{_sparkline_svg(trend, reading["status"])}'
        f'<span class="trend-note">{TREND_WINDOW_HOURS}시간 {arrow} {word}</span></div>'
    )


def motor_card(motor: dict) -> None:
    """05_ui_screens.md §3.2 모터별 카드.

    모든 카드가 같은 구조를 갖는다 — 지표 4개를 늘 같은 순서로 두고, 가장 심각한 지표의
    추이를 하단에 한 번 그린다. 카드마다 항목 수가 달라지면 3열 배치에서 높이가 어긋나
    화면이 성기게 보이기 때문이다. 이상 지표는 위치가 아니라 색·굵기로 드러낸다.

    카드 본문은 마크다운 한 번으로 렌더한다. Streamlit은 `st.markdown`으로 연 `<div>`가
    다음 요소를 감싸도록 두지 않으므로, 여러 번 나눠 부르면 상태색 테두리를 입힐 수 없다.

    카드 전체가 클릭 영역이다. 마크다운(카드)과 버튼을 컬럼 안에 **형제로** 두고, CSS가
    버튼 컨테이너를 카드 위에 투명하게 덮는다. 버튼 `key`는 DOM에서 그 컨테이너의
    `st-key-{key}` 클래스로 나타난다 (05 §3.2 참고).

    카드와 버튼 사이에 `st.container`를 끼우면 안 된다 — 래퍼가 한 겹 더 생겨 CSS의
    기준점이 어긋난다. 같은 이유로 카드 안에는 다른 위젯을 두지 않는다.
    """
    from app.ui.navigation import MOTOR_DETAIL_PAGE  # 순환 import 방지를 위한 지연 import

    motor_id = motor["motor_id"]
    status = motor["status"]
    readings = motor.get("readings", [])

    if readings:
        # 표시는 늘 같은 순서(온도·진동·전류·소음)로, 추이는 가장 심각한 지표로.
        worst = readings[0]
        ordered = sorted(readings, key=lambda r: METRIC_NAMES.index(r["metric"]))
        body = "".join(_metric_html(reading) for reading in ordered)
        body += _trend_html(worst, motor.get("trend", []))
    else:
        body = '<div class="metric-note">수집된 계측값이 없습니다.</div>'

    last_changed = motor.get("last_changed_at")
    footer = (
        f"{format_relative(parse_utc(last_changed))} 상태 변경"
        if last_changed
        else "상태 변경 이력 없음"
    )

    st.markdown(
        f'<div class="motor-card status-{status.lower()}">'
        f"{_data_flow_html(status)}"
        f'<div class="motor-head">'
        f'<span class="motor-name">{motor["motor_name"]}</span>'
        f'<span class="status-badge status-{status.lower()}">{status}</span>'
        f"</div>"
        f'<div class="motor-meta">{motor["model_name"]} · {motor["installation_location"]}</div>'
        f"{body}"
        f'<div class="motor-foot">{footer}<span class="go">상세 보기 ›</span></div>'
        f"</div>",
        unsafe_allow_html=True,
    )

    # 카드 위를 덮는 투명 버튼. 라벨은 화면에 보이지 않지만 스크린리더에는 읽힌다.
    if st.button(
        f"{motor['motor_name']} 상세 보기",
        key=f"{MOTOR_CARD_BUTTON_PREFIX}{motor_id}",
        use_container_width=True,
    ):
        st.session_state["selected_motor_id"] = motor_id
        st.switch_page(MOTOR_DETAIL_PAGE)


def _sc_metric_span(metric: str, value, status: str) -> str:
    """현황 카드의 지표 1개 — 라벨·값·단위를 색을 나눠 표기한다 (메인 대시보드 색 체계 공유).

    이상(WARNING/DANGER/FAULT)으로 판정된 지표는 `scm-abn status-{status}` 클래스를 붙여
    상태색으로 강조한다 — 어느 지표가 문제인지 한눈에 구분되게 한다.
    """
    abnormal = status in ("WARNING", "DANGER", "FAULT")
    cls = f"scm scm-abn status-{status.lower()}" if abnormal else "scm"
    if value is None:
        return f'<span class="{cls}"><span class="scm-l">{METRIC_LABELS[metric]}</span>' \
               f'<span class="scm-v">-</span></span>'
    return (
        f'<span class="{cls}"><span class="scm-l">{METRIC_LABELS[metric]}</span>'
        f'<span class="scm-v">{value:,.1f}</span>'
        f'<span class="scm-u">{METRIC_UNITS[metric]}</span></span>'
    )


def status_card(motor: dict) -> None:
    """모터 현황 페이지의 경량 카드 (재정리안 2페이지).

    200대를 한 화면에 그리므로 인라인 SVG·게이지·흐름 애니메이션을 가진 `motor_card`를
    쓰지 않고 텍스트 위주로만 그린다. 상태 색상 클래스(`status-{status}`)는 공유한다.

    카드 전체가 클릭 영역이다. `motor_card`와 같은 오버레이 기법 — 카드 마크다운과 투명
    `st.button`을 컬럼 안 형제로 두고 CSS가 버튼을 카드 위에 덮는다(styles.py의
    `:has(.status-card)` 규칙). st.button을 쓰는 이유: 웹소켓으로 처리돼 페이지 리로드가
    없어 로그인 세션이 유지된다(마크다운 `<a href>`는 전체 리로드라 세션이 날아간다).
    반응형 열 수는 컬럼을 감싼 flex-wrap 블록이 담당한다.

    상태 라벨을 좌상단에 먼저 두고 그 아래 모터명을 둔다 — 길이가 다른 모터명과 배지가
    한 줄에서 겹치는 문제를 없애기 위함이다. 입력은 `list_company_motor_status()`의 dict.
    """
    from app.ui.navigation import MOTOR_DETAIL_PAGE  # 순환 import 방지를 위한 지연 import

    motor_id = motor["motor_id"]
    status = motor["status"]
    values = motor.get("values", {})
    statuses = motor.get("statuses", {})
    lower = status.lower()

    def _span(metric: str) -> str:
        return _sc_metric_span(metric, values.get(metric), statuses.get(metric, "NORMAL"))

    line1 = f'{_span("temperature")}<span class="scm-sep">·</span>{_span("vibration")}'
    line2 = f'{_span("current")}<span class="scm-sep">·</span>{_span("sound")}'

    last_changed = motor.get("last_changed_at")
    footer = (
        f"{format_relative(parse_utc(last_changed))} 상태변경"
        if last_changed
        else "상태변경 이력 없음"
    )

    st.markdown(
        f'<div class="status-card status-{lower}">'
        f'<div class="sc-badge-row">'
        f'<span class="status-badge status-{lower}">{status}</span></div>'
        f'<div class="sc-name">{motor["motor_name"]}</div>'
        f'<div class="sc-loc">{motor["installation_location"]}</div>'
        f'<div class="sc-model">{motor["model_name"]}</div>'
        f'<div class="sc-metrics">'
        f'<div class="sc-metric-line">{line1}</div>'
        f'<div class="sc-metric-line">{line2}</div></div>'
        f'<div class="sc-foot status-{lower}">{footer}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )

    if st.button(
        f"{motor['motor_name']} 상세 보기",
        key=f"{STATUS_CARD_BUTTON_PREFIX}{motor_id}",
        use_container_width=True,
    ):
        st.session_state["selected_motor_id"] = motor_id
        st.switch_page(MOTOR_DETAIL_PAGE)


_DIRECTION_MARK = {WORSE: ("▲", "악화"), RECOVER: ("▼", "회복"), FLAT: ("·", "")}
_MAINTENANCE_KEY = "maintenance_confirm"


def maintenance_button(motor: dict, key_prefix: str, **button_kwargs) -> bool:
    """정비 완료 확인 버튼 (05 §4.3). 미확인 FAULT 지표가 없으면 아무것도 그리지 않는다.

    대시보드 카드와 상세 페이지가 함께 쓴다. 설비가 멈춘 상태에서 가장 급한 조치가
    상세 페이지 안에만 있으면 담당자가 두 번 이동해야 한다.
    """
    fault_metrics = motor.get("fault_metrics") or []
    if not fault_metrics:
        return False

    clicked = st.button(
        "정비 완료 확인", key=f"{key_prefix}-maint-{motor['motor_id']}", **button_kwargs
    )
    if clicked:
        st.session_state[_MAINTENANCE_KEY] = {
            "motor_id": motor["motor_id"],
            "motor_name": motor["motor_name"],
            "metrics": list(fault_metrics),
        }
        st.rerun()
    return True


def render_maintenance_dialog() -> None:
    """정비 완료 확인 다이얼로그. 페이지 끝에서 1회 호출한다.

    확인 대상을 세션에 담아 두는 이유: 버튼 클릭 여부로만 열면 다이얼로그 안의 체크박스를
    누르는 순간 rerun이 일어나 창이 닫히고 절차를 마칠 수 없다.
    """
    pending = st.session_state.get(_MAINTENANCE_KEY)
    if not pending:
        return

    @st.dialog("정비 완료 확인")
    def _dialog() -> None:
        labels = ", ".join(METRIC_LABELS.get(m, m) for m in pending["metrics"])
        st.write(f"**{pending['motor_name']}** 의 고장 상태를 정비 완료로 처리합니다.")
        st.markdown(f"- 대상 지표: **{labels}**")
        st.caption("확인 시 담당자 이력이 기록되고 해당 지표의 자동 상태 판정이 재개됩니다.")

        agreed = st.checkbox("정비가 완료되었음을 확인했습니다.")
        confirm_col, cancel_col = st.columns(2)
        if confirm_col.button(
            "정비 완료 처리", type="primary", disabled=not agreed, use_container_width=True
        ):
            with connection_scope() as conn:
                for metric in pending["metrics"]:
                    confirm_maintenance(
                        conn, pending["motor_id"], metric, st.session_state.get("contact_id")
                    )
            st.session_state.pop(_MAINTENANCE_KEY, None)
            st.rerun()
        if cancel_col.button("취소", use_container_width=True):
            st.session_state.pop(_MAINTENANCE_KEY, None)
            st.rerun()

    _dialog()


def event_list_header(show_motor: bool) -> None:
    """이벤트 리스트 헤더 (05 §3.3 / §4.4). 대시보드만 모터명 컬럼을 갖는다."""
    labels = ("발생 일시", "모터명", "상태 변화", "발생 사유", "")
    widths = EVENT_COLUMN_WIDTHS_WITH_MOTOR if show_motor else EVENT_COLUMN_WIDTHS
    if not show_motor:
        labels = tuple(label for label in labels if label != "모터명")

    for column, label in zip(st.columns(widths), labels):
        column.caption(label)


def event_row(event, show_motor: bool) -> None:
    """이벤트 1건. 무슨 지표가 어디서 어디로 왜 바뀌었는지를 한 줄에 담는다.

    상태값만 보여주면 "DANGER"라는 결과만 알 뿐 원인과 방향을 알 수 없어, 담당자가
    상세 페이지까지 들어가야 상황을 파악할 수 있다.
    """
    widths = EVENT_COLUMN_WIDTHS_WITH_MOTOR if show_motor else EVENT_COLUMN_WIDTHS
    columns = list(st.columns(widths))

    occurred_at = columns.pop(0)
    event_dt = parse_utc(event["created_at"])
    occurred_at.markdown(
        f'<div class="event-when"><span class="rel">{format_relative(event_dt)}</span>'
        f'<span class="abs">{format_display(event_dt, DISPLAY_DATETIME_FORMAT)}</span></div>',
        unsafe_allow_html=True,
    )

    if show_motor:
        columns.pop(0).write(event["motor_name"])

    direction = transition_direction(event["previous_status"], event["new_status"])
    mark, word = _DIRECTION_MARK[direction]
    columns.pop(0).markdown(
        f'<div class="event-change">'
        f'<span class="metric-tag">{METRIC_LABELS.get(event["metric_name"], event["metric_name"])}</span>'
        f'<span class="chip status-{event["previous_status"].lower()}">'
        f'{event["previous_status"]}</span>'
        f'<span class="arrow {direction}" title="{word}">{mark}</span>'
        f'<span class="chip status-{event["new_status"].lower()}">{event["new_status"]}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    columns.pop(0).markdown(
        f'<div class="event-reason {direction}">{event["trigger_reason"] or "-"}</div>',
        unsafe_allow_html=True,
    )

    with columns.pop(0):
        report_button(event)


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
