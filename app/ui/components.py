"""재사용 UI 조각. 05_ui_screens.md 기준."""

from datetime import datetime, timezone
from html import escape

import streamlit as st

from app.config import (
    CARD_CHANGE_EPSILON,
    CARD_FLASH_PHASES,
    CARD_HIGHLIGHT_STATUSES,
    DATA_FLOW_NODES,
    DISPLAY_DATETIME_FORMAT,
    EVENT_COLUMN_WIDTHS,
    EVENT_COLUMN_WIDTHS_WITH_MOTOR,
    EVENT_VALUE_DECIMALS,
    MAINTENANCE_CONFIRM_COLUMNS,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_UNITS,
    MOTOR_CARD_BUTTON_PREFIX,
    REFRESH_COUNTDOWN_HEIGHT_PX,
    REFRESH_COUNTDOWN_KEY,
    REFRESH_COUNTDOWN_TICK_MS,
    REPORT_DATE_FORMAT,
    REPORT_SESSION_ID_FORMAT,
    REPORT_TIME_FORMAT,
    REPORT_VIEWER_HEIGHT_PX,
    SERVICE_ICON,
    SERVICE_NAME,
    SPARKLINE_HEIGHT_PX,
    SPARKLINE_WIDTH_PX,
    STATUS_CARD_BUTTON_PREFIX,
    STATUS_GROUP_ORDER,
    STATUS_KOREAN_LABELS,
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
# 직전 렌더의 카드 지표값 {motor_id: {metric: value}} — 갱신 시 "바뀐 것"만 강조하는 데 쓴다.
_CARD_VALUES_KEY = "card_metric_values"

# 임계값 표의 구간 열 순서 (05 §4.2). 상태 심각도 오름차순이라 왼쪽에서 오른쪽으로
# 읽으면 그대로 악화 순서가 된다.
_THRESHOLD_COLUMNS = ("NORMAL", "WARNING", "DANGER", "FAULT")


def _page_nav(active: str | None) -> None:
    """상단 페이지 이동 내비 (메인 대시보드 / 모터 그래프 / 모터 현황).

    사이드바를 숨긴 구조라 메인 페이지 3개를 오갈 경로가 필요하다. 현재 페이지는
    primary 버튼으로 강조하고, 나머지는 클릭 시 해당 페이지로 전환한다.

    `active`가 None이면 아무 버튼도 강조하지 않는다 — 모터 상세처럼 내비에 없는
    하위 화면에서 쓴다. 그 화면도 세 곳으로 바로 갈 수 있어야 한다 (2026-08-10).
    """
    from app.ui.navigation import HEADER_NAV_PAGES  # 순환 import 방지를 위한 지연 import

    # 버튼 수만큼 좁은 열을 두고 남는 폭은 마지막 빈 열이 흡수한다 — 버튼이 늘어도
    # (관리자 추가처럼) 폭 상수를 다시 계산하지 않아도 된다.
    columns = st.columns([1.3] * len(HEADER_NAV_PAGES) + [9.0 - 1.3 * len(HEADER_NAV_PAGES)])
    for (key, label, path), column in zip(HEADER_NAV_PAGES, columns):
        with column:
            if st.button(
                label,
                key=f"nav-{key}",
                type="primary" if key == active else "secondary",
                width="stretch",
            ) and key != active:
                st.switch_page(path)

    # 남는 열은 종전에 비어 있었다 — 상태 범례를 여기에 둔다 (실측 빈 폭: 1600px 화면에서
    # 595px, 1280px에서 460px).
    with columns[-1]:
        _status_legend()


def _status_legend() -> None:
    """상태 4단계 범례 (05 §5-4, 2026-08-12 사용자 요청).

    이 서비스의 모든 화면이 상태를 영문 배지(NORMAL/WARNING/DANGER/FAULT)로만 표시한다.
    판정 기준을 아는 담당자에게는 충분하지만, 처음 보는 사람은 배지가 무슨 뜻인지 화면
    어디에서도 알 수 없었다 — 임계값 표(§4.2)까지 들어가야 한글 이름이 나온다.

    **내비 오른쪽 빈 열에 둔다.** `page_header()`는 로그인 이후 모든 페이지가 부르므로
    한 곳에 넣으면 전 화면에 노출되고, 이미 있던 빈 열을 쓰므로 세로 공간을 더 쓰지 않는다.
    화면을 내리면 함께 사라지는데(문서 흐름 안), 그 경우까지 필요하면 갱신 카운터처럼
    `position: fixed`로 띄우는 방법이 있다(`REFRESH_COUNTDOWN_*` 참고).
    """
    chips = "".join(
        f'<span class="sl-item">'
        f'<span class="status-badge status-{status.lower()}">{status}</span>'
        f'<span class="sl-ko">{korean}</span></span>'
        for status, korean in STATUS_KOREAN_LABELS.items()
    )
    st.markdown(f'<div class="status-legend">{chips}</div>', unsafe_allow_html=True)


def page_header(active: str | None = None) -> None:
    """상단 헤더 — 좌측 서비스명, 우측 로그인 정보와 로그아웃 (05 §5-4).

    사이드바 대신 일반 웹 서비스처럼 상단에 둔다. 로그인 화면에서 세운 브랜드가
    로그인 후에도 이어지고, 담당자는 지금 어느 회사 계정으로 보고 있는지 늘 확인할 수 있다.

    `active`는 페이지 이동 내비에서 현재 페이지를 강조하는 키다. **내비는 모든 화면에
    그린다** (2026-08-10 변경) — 종전에는 `active=None`이면 내비를 그리지 않아, 모터
    상세에서 다른 페이지로 가려면 `← 대시보드`로 한 번 나갔다가 다시 눌러야 했다.
    이제 상세에서도 세 곳으로 바로 간다. `None`이면 강조만 하지 않는다.
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
        if st.button("로그아웃", width="stretch"):
            end_session()
            st.rerun()

    _page_nav(active)

    st.markdown('<div class="app-header-rule"></div>', unsafe_allow_html=True)


def refresh_countdown(interval_seconds: int) -> None:
    """다음 자동 갱신까지 남은 시간 (05 §5-2, 2026-08-11 사용자 요청).

    자동 갱신이 돌아도 화면이 그 사실을 말하지 않으면, 값이 그대로인 것이 "아직 갱신 전"인지
    "화면이 멈춤"인지 담당자가 구분할 수 없다.

    **화면 우하단에 고정한다** (2026-08-11 2차 요청). 처음에는 문서 흐름 안에 두었는데,
    대시보드는 카드 20장 + 이벤트 목록이라 스크롤을 내리면 카운터가 화면 밖으로 나갔다 —
    정작 값이 바뀌는 카드를 보는 동안 카운터가 보이지 않았다. `st.container(key=...)`로 감싸
    `st-key-{key}` 클래스를 만들고 styles.py가 `position: fixed`로 띄운다(모터 카드 오버레이와
    같은 기법). 표시도 `다음 갱신까지 N초` 한 줄로 줄였다 — 떠 있는 배지는 작아야 방해가 없다.
    마지막 갱신 시각은 툴팁으로 남긴다.

    **브라우저에서 센다.** 서버에서 매초 다시 그리면 그때마다 조회와 틱이 돌아 갱신 주기의
    10배 비용이 든다. 그래서 iframe을 띄우고 그 안의 스크립트가 센다 —
    `st.markdown(unsafe_allow_html=True)`는 `<script>`를 제거하므로 쓸 수 없다.

    **`st.iframe`을 쓴다.** `st.components.v1.html`도 같은 일을 하지만 `2026-06-01 제거`
    예고가 이미 지나 경고가 뜬다 — `use_container_width`를 걷어낸 것과 같은 이유로
    새로 들이지 않는다. `st.iframe`은 `src`가 URL·경로 패턴에 맞지 않으면 HTML 문자열로
    보고 그대로 삽입하므로 그대로 대체된다(1.60.0 docstring 확인).

    갱신 주기마다 fragment가 다시 실행되면서 이 iframe도 새 시작 시각으로 다시 만들어져
    카운트가 자동으로 재시작한다. 0에 닿았는데 아직 갱신이 안 왔으면 "갱신 중"으로 바꿔
    멈춘 것처럼 보이지 않게 한다.
    """
    theme = palette()
    updated_at = format_display(datetime.now(timezone.utc), "%H:%M:%S")
    with st.container(key=REFRESH_COUNTDOWN_KEY):
        st.iframe(
            f"""<style>
  body {{ margin: 0; font-family: "Source Sans Pro", system-ui, sans-serif; }}
  .rc {{ display: flex; align-items: center; justify-content: center; gap: 7px;
         height: {REFRESH_COUNTDOWN_HEIGHT_PX}px; font-size: 12.5px;
         color: {theme["text_muted"]}; white-space: nowrap; }}
  .rc .dot {{ width: 7px; height: 7px; border-radius: 50%; background: {theme["status"]["NORMAL"]};
              flex-shrink: 0; animation: rc-pulse 2s ease-in-out infinite; }}
  .rc .num {{ color: {theme["text_strong"]}; font-weight: 600; font-variant-numeric: tabular-nums; }}
  @keyframes rc-pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.3; }} }}
</style>
<div class="rc" title="자동 갱신 {interval_seconds}초 · 마지막 갱신 {updated_at}">
  <span class="dot"></span>
  <span id="rc-text">다음 갱신까지 <span class="num" id="rc-num">{interval_seconds}</span>초</span>
</div>
<script>
  (function () {{
    var total = {interval_seconds} * 1000;
    var start = Date.now();
    var num = document.getElementById("rc-num");
    var text = document.getElementById("rc-text");
    function tick() {{
      var left = total - (Date.now() - start);
      if (left <= 0) {{
        // 갱신 요청이 서버를 오가는 사이 0초에서 멈춰 보이지 않게 한다.
        text.textContent = "갱신 중…";
        return;
      }}
      num.textContent = Math.ceil(left / 1000);
    }}
    tick();
    setInterval(tick, {REFRESH_COUNTDOWN_TICK_MS});
  }})();
</script>
""",
            height=REFRESH_COUNTDOWN_HEIGHT_PX,
        )


def summary_tiles(tiles: list[dict]) -> None:
    """대시보드 상단 요약 타일 (05 §3.1).

    `st.metric`을 쓰지 않는 이유: 라벨·값·보조줄이 아무 테두리 없이 텍스트로만 놓여
    화면 첫 화면인데도 무게가 실리지 않는다. 모터 카드와 같은 언어(상단 액센트 3px +
    카드 배경 + 테두리)로 그려 대시보드 전체가 한 벌로 보이게 한다.

    `tone`은 장식이 아니라 정보다 — 조치 필요가 0대면 초록, 있으면 빨강이 되므로
    숫자를 읽기 전에 색으로 상태를 먼저 안다. 각 타일은 다음 키를 받는다:
    `label`, `value`, `unit`, `sub`, `tone`(status 소문자 또는 "brand"), 선택 `status_key`.

    **`status_key`는 값 앞에 붙는 영문 상태명이다** (예: `FAULT`, 2026-08-12 사용자 요청).
    화면 전체가 상태를 영문으로 표시하므로(카드 배지·차트 배지·이벤트 목록·헤더 범례),
    요약 타일에도 같은 말이 있어야 "바로 조치 필요 4대"와 "FAULT 배지가 붙은 카드 4장"이
    같은 것임이 이어진다. 숫자보다 작게 두어 값의 무게는 그대로 둔다.

    한 덩어리 마크다운으로 그린다. `st.columns`로 나누면 컬럼마다 여백 규칙이 달라
    타일 사이 간격이 화면 폭에 따라 어긋난다. CSS 그리드는 폭이 좁아지면 자동으로
    줄을 바꾼다(styles.py `.summary-grid`).
    """
    cells = []
    for tile in tiles:
        unit = tile.get("unit")
        unit_html = f'<span class="sum-unit">{unit}</span>' if unit else ""
        status_key = tile.get("status_key")
        key_html = f'<span class="sum-status">{status_key}</span>' if status_key else ""
        cells.append(
            f'<div class="summary-tile tone-{tile["tone"]}">'
            f'<div class="sum-label"><span class="sum-dot"></span>{tile["label"]}</div>'
            f'<div class="sum-value">{key_html}{tile["value"]}{unit_html}</div>'
            f'<div class="sum-sub">{tile["sub"]}</div>'
            "</div>"
        )
    st.markdown(f'<div class="summary-grid">{"".join(cells)}</div>', unsafe_allow_html=True)


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


def lock_selectbox_typing(*keys: str) -> None:
    """셀렉트박스 입력을 읽기전용으로 만들어 검색/타이핑을 막는다 (드롭다운 선택만 허용).

    CSS로는 키보드 입력을 못 막는다 — 드롭다운을 열면 입력이 자동 포커스된다. 부모 DOM에
    접근하는 스크립트로 `readOnly`를 걸어야 하고, rerun 후 재렌더된 입력에도 다시 걸어야
    하므로 `MutationObserver`를 둔다.

    **`height=1`이다.** `st.iframe(height=0)`은 iframe 요소를 아예 만들지 않아 스크립트가
    실행되지 않는다 — 화면에 표시할 것이 없어 조용히 실패한다(01 §2.5의 함정 항목).

    관찰자는 **매번 새로 설치한다.** 페이지를 옮기면 이전 페이지의 iframe이 사라지면서 그
    안에서 만든 콜백도 죽는데, 죽은 콜백을 붙들고 있으면 새 페이지에서 재적용이 되지 않는다.
    키 목록도 페이지마다 교체한다(한 번에 한 페이지만 렌더되므로 누적할 이유가 없다).
    """
    key_list = ", ".join(f'"{key}"' for key in keys)
    st.iframe(
        f"""<script>
    const doc = window.parent.document;
    doc.__lockedSelectKeys = [{key_list}];
    function apply() {{
      (doc.__lockedSelectKeys || []).forEach(function (k) {{
        doc.querySelectorAll('.st-key-' + k + ' input').forEach(function (inp) {{
          inp.readOnly = true;
          inp.setAttribute('inputmode', 'none');
        }});
      }});
    }}
    apply();
    if (doc.__lockedSelectObserver) doc.__lockedSelectObserver.disconnect();
    doc.__lockedSelectObserver = new MutationObserver(apply);
    doc.__lockedSelectObserver.observe(doc.body, {{ childList: true, subtree: true }});
    </script>""",
        height=1,
    )


def detail_header(motor_name: str, metric_statuses: dict[str, str]) -> None:
    """모터 상세 제목 + 상태별 지표 배지 (05 §4, 2026-08-11).

    **어느 지표가 어느 상태인지 밝힌다** — `FAULT (온도, 소음)  DANGER (진동)`.
    종전에는 대표 상태 배지 하나(`DANGER`)만 띄워, 담당자가 무엇 때문에 위험한지도
    무엇을 먼저 봐야 하는지도 알 수 없었다. 상태는 여러 개가 동시에 나올 수 있다.

    배지는 심각도 내림차순으로 늘어놓고(`STATUS_GROUP_ORDER`), 괄호 안 지표는 카드와 같은
    고정 순서(`METRIC_NAMES`)로 적는다 — 화면마다 순서가 다르면 눈이 다시 찾아야 한다.
    이상이 하나도 없으면 `NORMAL` 하나만 둔다.

    제목과 한 덩어리로 그린다. 종전에는 `st.columns([4, 1])`로 나눠 배지가 화면 오른쪽 끝에
    붙었는데, 1600px 폭에서 제목과 1,000px 넘게 떨어져 **둘이 같은 설비를 말한다는 것이
    읽히지 않았다.** 모터 카드의 `motor-head`와 같이 이름 바로 옆에 둔다.

    제목은 `st.title()`이 아니라 마크다운 `<h1>`이다 — 배지와 같은 flex 줄에 넣으려면
    한 요소 안에 있어야 한다. Streamlit이 마크다운 `h1`에 제목 타이포그래피를 그대로
    적용하므로 크기·굵기는 달라지지 않는다.
    """
    badges = []
    for status in STATUS_GROUP_ORDER:
        if status == "NORMAL":
            continue
        metrics = [m for m in METRIC_NAMES if metric_statuses.get(m) == status]
        if not metrics:
            continue
        labels = ", ".join(METRIC_LABELS.get(m, m) for m in metrics)
        badges.append(
            f'<span class="status-badge status-{status.lower()}">{status}'
            f'<span class="badge-metrics">({escape(labels)})</span></span>'
        )
    if not badges:
        badges.append('<span class="status-badge status-normal">NORMAL</span>')

    st.markdown(
        f'<div class="detail-head">'
        f"<h1>{escape(motor_name)}</h1>"
        f"{''.join(badges)}"
        f"</div>",
        unsafe_allow_html=True,
    )


def motor_info_table(motor) -> None:
    """모터 기본 정보 표 (05 §4.1, 2026-08-10).

    종전에는 `st.write("**항목** 값")`을 두 열로 흩뿌렸다. 항목명과 값이 같은 줄에서
    굵기만 다르게 붙어 있어 어디까지가 이름인지 눈으로 잘라 읽어야 했고, 바로 아래
    임계값 표(`st.dataframe`)와 생김새가 달라 한 페이지에 두 종류의 표가 보였다.
    같은 테두리·같은 셀 여백을 쓰는 표로 통일한다.

    한 줄에 두 쌍(항목·값·항목·값)을 넣어 종전의 2열 배치가 주던 밀도를 유지한다.
    """
    pairs = (
        ("모터 ID", motor["motor_id"]),
        ("설치 위치", motor["installation_location"]),
        ("모델명", motor["model_name"]),
        ("수집 주기", f"{motor['collection_interval_seconds']}초"),
        ("시리얼 번호", motor["serial_number"] or "-"),
        ("등록일자", format_display(parse_utc(motor["created_at"]))),
    )

    rows = []
    for left, right in zip(pairs[::2], pairs[1::2]):
        cells = "".join(
            f'<td class="k">{escape(str(key))}</td><td class="v">{escape(str(value))}</td>'
            for key, value in (left, right)
        )
        rows.append(f"<tr>{cells}</tr>")

    st.markdown(
        f'<div class="detail-table-wrap"><table class="detail-table">'
        f"{''.join(rows)}</table></div>",
        unsafe_allow_html=True,
    )


def threshold_table(thresholds) -> None:
    """지표별 임계값 표 (05 §4.2, 2026-08-10).

    `st.dataframe`을 쓰지 않는 이유: 네 구간이 전부 같은 검은 글씨라 어느 값이 위험한
    구간인지 표를 훑어야 알 수 있었다. 구간 값을 상태색으로 칠하면 색이 곧 심각도라
    한눈에 읽힌다. 머리글도 같은 색으로 물들여 열과 색의 대응을 알려준다.

    색은 `05 §5-3`의 단조 증가 램프(녹색 → 앰버 → 주황 → 빨강)를 그대로 쓰며,
    테마별 팔레트(`config.THEMES[...]["status"]`)라 다크에서도 대비가 확보된다.
    """
    header = "".join(
        f'<th class="{status.lower()}">{STATUS_KOREAN_LABELS.get(status, status)}</th>'
        for status in _THRESHOLD_COLUMNS
    )

    rows = []
    for threshold in thresholds:
        metric = threshold["metric_name"]
        label = METRIC_LABELS.get(metric, metric)
        unit = METRIC_UNITS.get(metric, "")
        ranges = (
            f"< {threshold['warning_range']:g}",
            f"{threshold['warning_range']:g} ~ {threshold['danger_range']:g}",
            f"{threshold['danger_range']:g} ~ {threshold['fault_range']:g}",
            f"≥ {threshold['fault_range']:g}",
        )
        cells = "".join(
            f'<td class="range {status.lower()}">{escape(text)}</td>'
            for status, text in zip(_THRESHOLD_COLUMNS, ranges)
        )
        rows.append(
            f'<tr><td class="metric-cell">{escape(label)}'
            f'<span class="unit">{escape(unit)}</span></td>{cells}</tr>'
        )

    st.markdown(
        f'<div class="detail-table-wrap"><table class="detail-table">'
        f'<tr><th>지표</th>{header}</tr>{"".join(rows)}</table></div>',
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
        # pathLength="1"로 길이를 정규화한다. 값이 바뀐 카드에서 선을 그려 넣는 애니메이션을
        # 순수 CSS로 걸기 위함이다(05 §5-2-3) — 실제 경로 길이를 몰라도
        # stroke-dasharray: 1 / dashoffset 1→0 이면 어떤 모양이든 왼쪽부터 그려진다.
        f'<polyline points="{points}" pathLength="1" fill="none" stroke="{color}" '
        f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>'
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


def _changed_metrics(motor_id: str, readings: list[dict]) -> tuple[set[str], str]:
    """직전 렌더 대비 값이 바뀐 지표와, 이번 렌더의 애니메이션 교대 접미사.
    (05 §5-2-3, 2026-08-11 사용자 요청)

    자동 갱신으로 숫자가 조용히 바뀌기만 하면 담당자는 무엇이 달라졌는지 알아채지 못한다.
    바뀐 지표에만 강조를 걸기 위해 직전 값을 세션에 들고 비교한다 — **전부 번쩍이면**
    어느 것이 실제 변화인지 다시 알 수 없으므로 "이번에 바뀐 것"만 골라야 한다.

    `CARD_CHANGE_EPSILON`보다 작은 변화는 무시한다. 표시가 소수점 1자리라 그보다 작은
    변화는 화면에서 같은 숫자로 보이는데 강조만 들어가면 이유를 알 수 없는 깜빡임이 된다.

    첫 렌더에는 비교 대상이 없으므로 아무것도 강조하지 않는다(바뀐 게 아니라 처음 보는 것).

    **교대 접미사가 필요한 이유** (2026-08-11 4차 요청으로 발견): CSS 애니메이션은 요소가
    새로 삽입되거나 애니메이션 속성이 바뀔 때만 재생된다. Streamlit은 카드 마크다운을
    갈아끼우지 않고 DOM을 제자리에서 패치하므로, 연속으로 값이 바뀌는 지표는 `.changed`가
    계속 붙어 있어 **처음 한 번만 재생되고 이후로는 조용했다.** 값이 바뀔 때마다 접미사를
    번갈아 바꿔 animation-name을 갈아치우면 매번 다시 재생된다.
    """
    store = st.session_state.setdefault(_CARD_VALUES_KEY, {})
    entry = store.get(motor_id)
    current = {r["metric"]: r["value"] for r in readings}
    previous = entry["values"] if entry else None
    phase = entry["phase"] if entry else CARD_FLASH_PHASES[0]

    changed: set[str] = set()
    if previous is not None:
        changed = {
            metric
            for metric, value in current.items()
            if metric in previous and abs(value - previous[metric]) >= CARD_CHANGE_EPSILON
        }
    if changed:
        index = CARD_FLASH_PHASES.index(phase)
        phase = CARD_FLASH_PHASES[(index + 1) % len(CARD_FLASH_PHASES)]

    store[motor_id] = {"values": current, "phase": phase}
    return changed, phase


def _metric_html(reading: dict, changed: bool = False) -> str:
    """지표 1건 — 한 줄에 이름·값·설명, 그 아래 게이지.

    모든 카드가 4개 지표를 같은 순서로 담아 높이가 일정해진다. 이상 지표는 위치가 아니라
    색·굵기와 여유 문구로 구분한다.

    **설명을 값과 같은 줄에 둔다 (2026-08-10).** 종전에는 게이지 아래 별도 줄이라
    지표마다 17px(14px + margin 3px), 카드당 68px을 썼다. 대시보드는 카드를 20개
    깔아 두는 화면이라 카드 높이가 곧 스크롤 양이다 — 한 줄로 합쳐 그만큼 줄인다.
    """
    abnormal = reading["status"] in CARD_HIGHLIGHT_STATUSES
    remaining = reading["remaining"]

    # 설명은 모든 지표에 둔다. 이상일 때만 넣으면 카드마다 줄 구성이 달라져 높이가 어긋난다.
    if not abnormal:
        note = f"고장 임계의 {reading['ratio'] * 100:.0f}%"
    elif remaining > 0:
        note = f"고장까지 {remaining:,.1f}{reading['unit']} 남음"
    else:
        note = "고장 임계 초과"

    return (
        f'<div class="metric-block status-{reading["status"].lower()}'
        f'{" abnormal" if abnormal else ""}{" changed" if changed else ""}">'
        f'<div class="metric-row">'
        f'<span class="metric-lead">'
        f'<span class="metric-name">{reading["label"]}</span>'
        f'<span class="metric-value">{reading["value"]:,.1f}'
        f'<span class="metric-unit">{reading["unit"]}</span></span>'
        f"</span>"
        f'<span class="metric-note">{note}</span>'
        f"</div>"
        f"{_metric_gauge(reading)}"
        f"</div>"
    )


def _trend_html(reading: dict, trend: list[float], changed: bool = False) -> str:
    """카드 하단 추이 — 가장 심각한 지표 하나. 정상 카드에도 넣어 높이를 맞춘다."""
    if not trend:
        return ""
    arrow, word = _trend_direction(trend)
    return (
        f'<div class="metric-trend{" changed" if changed else ""}">'
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

    phase = CARD_FLASH_PHASES[0]
    if readings:
        # 표시는 늘 같은 순서(온도·진동·전류·소음)로, 추이는 가장 심각한 지표로.
        worst = readings[0]
        ordered = sorted(readings, key=lambda r: METRIC_NAMES.index(r["metric"]))
        # 자동 갱신으로 값이 바뀐 지표에만 강조를 건다 (05 §5-2-3).
        changed, phase = _changed_metrics(motor_id, readings)
        body = "".join(_metric_html(reading, reading["metric"] in changed) for reading in ordered)
        body += _trend_html(worst, motor.get("trend", []), worst["metric"] in changed)
    else:
        body = '<div class="metric-empty">수집된 계측값이 없습니다.</div>'

    # 하단 줄(상태 변경 시각 + "상세 보기 ›")은 두지 않는다 (2026-08-10).
    # 28px(16px + margin 12px)을 카드마다 쓰는데, 상태 변경 시각은 바로 위 추이 줄과
    # 이벤트 목록에도 있고, 진입 안내는 카드 전체가 클릭 영역이라는 hover 효과(살짝
    # 떠오르고 테두리가 상태색으로 바뀜)가 대신한다.
    st.markdown(
        # flash-{phase}는 강조 애니메이션 이름을 갈아치우기 위한 것이다 —
        # 값이 바뀔 때마다 번갈아 바뀌어야 애니메이션이 매번 다시 재생된다.
        f'<div class="motor-card status-{status.lower()} flash-{phase}">'
        f"{_data_flow_html(status)}"
        f'<div class="motor-head">'
        f'<span class="motor-name">{motor["motor_name"]}</span>'
        f'<span class="status-badge status-{status.lower()}">{status}</span>'
        f"</div>"
        f'<div class="motor-meta">{motor["model_name"]} · {motor["installation_location"]}</div>'
        f"{body}"
        f"</div>",
        unsafe_allow_html=True,
    )

    # 카드 위를 덮는 투명 버튼. 라벨은 화면에 보이지 않지만 스크린리더에는 읽힌다.
    if st.button(
        f"{motor['motor_name']} 상세 보기",
        key=f"{MOTOR_CARD_BUTTON_PREFIX}{motor_id}",
        width="stretch",
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
        width="stretch",
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


def render_maintenance_confirm(motors: list[dict]) -> None:
    """정비 완료 확인이 필요한 FAULT 모터 안내 + 모터별 확인 카드 (05 §3.1).

    설비 정지는 가장 급한 조치라, 건조한 상태색 배너 대신 아이콘·강조 링으로 '확인 필요'임을
    부각한다. 또 모터별로 이름·모델·설치 위치를 함께 보여줘 어떤 설비의 버튼인지 구분되게 하고,
    버튼은 카드 아래 작게 둔다(어느 모터의 것인지 카드가 바로 위에서 알려준다).
    """
    st.markdown(
        f'<div class="maint-alert">'
        f'<span class="maint-alert-icon">🔧</span>'
        f'<span class="maint-alert-text">'
        f"<b>정비 완료 확인 필요</b> — {len(motors)}대가 고장(FAULT) 상태입니다. "
        f"정비 후 아래에서 완료 확인을 해주세요.</span></div>",
        unsafe_allow_html=True,
    )
    for _start in range(0, len(motors), MAINTENANCE_CONFIRM_COLUMNS):
        _row = motors[_start : _start + MAINTENANCE_CONFIRM_COLUMNS]
        for _column, _motor in zip(st.columns(MAINTENANCE_CONFIRM_COLUMNS), _row):
            with _column:
                # 정보와 버튼을 하나의 테두리 박스(카드) 안에 함께 담는다.
                with st.container(border=True):
                    st.markdown(
                        f'<div class="maint-info">'
                        f'<div class="maint-name">{_motor["motor_name"]}</div>'
                        f'<div class="maint-meta">{_motor["model_name"]}</div>'
                        f'<div class="maint-loc">{_motor["installation_location"]}</div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    # 내용 맞춤 폭의 작은 버튼 — 카드 안, 정보 바로 아래.
                    maintenance_button(_motor, key_prefix="banner", type="primary")


def _discard_maintenance_pending() -> None:
    """다이얼로그를 확인/취소 없이 닫았을 때 대기 상태를 버린다.

    바깥 클릭·X·ESC로 닫으면 Streamlit은 콜백 없이 창만 닫는다. 그래서 세션에 담아 둔
    대상이 그대로 남아, 다음에 대시보드나 모터 상세로 들어갈 때 창이 저절로 다시 떴다
    (2026-08-10 배포본에서 확인). `on_dismiss`로 그 경로를 막는다.
    """
    st.session_state.pop(_MAINTENANCE_KEY, None)


def render_maintenance_dialog() -> None:
    """정비 완료 확인 다이얼로그. 페이지 끝에서 1회 호출한다.

    확인 대상을 세션에 담아 두는 이유: 버튼 클릭 여부로만 열면 다이얼로그 안의 체크박스를
    누르는 순간 rerun이 일어나 창이 닫히고 절차를 마칠 수 없다. 대신 닫히는 모든 경로에서
    대기 상태를 반드시 비워야 한다 — 확인/취소는 아래 버튼이, 그 밖의 닫기는
    `on_dismiss`가 맡는다.
    """
    pending = st.session_state.get(_MAINTENANCE_KEY)
    if not pending:
        return

    @st.dialog("정비 완료 확인", on_dismiss=_discard_maintenance_pending)
    def _dialog() -> None:
        labels = ", ".join(METRIC_LABELS.get(m, m) for m in pending["metrics"])
        st.write(f"**{pending['motor_name']}** 의 고장 상태를 정비 완료로 처리합니다.")
        st.markdown(f"- 대상 지표: **{labels}**")
        st.caption("확인 시 담당자 이력이 기록되고 해당 지표의 자동 상태 판정이 재개됩니다.")

        agreed = st.checkbox("정비가 완료되었음을 확인했습니다.")
        confirm_col, cancel_col = st.columns(2)
        if confirm_col.button(
            "정비 완료 처리", type="primary", disabled=not agreed, width="stretch"
        ):
            with connection_scope() as conn:
                for metric in pending["metrics"]:
                    confirm_maintenance(
                        conn, pending["motor_id"], metric, st.session_state.get("contact_id")
                    )
            st.session_state.pop(_MAINTENANCE_KEY, None)
            st.rerun()
        if cancel_col.button("취소", width="stretch"):
            st.session_state.pop(_MAINTENANCE_KEY, None)
            st.rerun()

    _dialog()


def event_list_header(show_motor: bool) -> None:
    """이벤트 리스트 헤더 (05 §3.3 / §4.4). 대시보드만 모터명 컬럼을 갖는다.

    `st.caption` 대신 `.event-th` 마크다운을 쓴다 — CSS가 `:has(.event-th)`로 헤더 행을
    찾아 아래쪽 구분선을 그린다. caption은 잡을 만한 클래스가 없다.
    """
    labels = ("발생 일시", "모터명", "상태 변화", "값 변화", "발생 사유", "")
    widths = EVENT_COLUMN_WIDTHS_WITH_MOTOR if show_motor else EVENT_COLUMN_WIDTHS
    if not show_motor:
        labels = tuple(label for label in labels if label != "모터명")

    for column, label in zip(st.columns(widths), labels):
        column.markdown(f'<div class="event-th">{label}</div>', unsafe_allow_html=True)


def _value_change_html(event, direction: str) -> str:
    """이벤트의 계측값 변화 `62.1 → 82.2 °C` (05 §3.3, 2026-08-07 추가).

    상태 전이만으로는 "임계를 아슬하게 넘었는지, 크게 뛰었는지"를 알 수 없다. 담당자가
    급한 정도를 가늠하려면 수치가 필요하다.

    이전 값이 없거나(첫 수집) 계측 컬럼이 없는 지표(connectivity)는 있는 쪽만 표시한다 —
    빈칸으로 두면 데이터가 누락된 것처럼 보인다.
    """
    metric = event["metric_name"]
    unit = METRIC_UNITS.get(metric, "")
    current, previous = event["metric_value"], event["previous_value"]

    if current is None and previous is None:
        return '<div class="event-value">-</div>'

    if previous is None or current is None:
        value = f"{(current if current is not None else previous):,.{EVENT_VALUE_DECIMALS}f}"
        return (
            f'<div class="event-value"><span class="ev-now">{value}</span>'
            f'<span class="ev-unit">{unit}</span></div>'
        )

    # 기본 2자리(config.EVENT_VALUE_DECIMALS). 그래도 두 값이 같게 찍히면 자릿수를 늘린다 —
    # 임계 바로 앞뒤에서 전이가 일어나면 반올림에 묻혀 "임계를 넘었다"는 사실이 사라진다.
    for digits in range(EVENT_VALUE_DECIMALS, EVENT_VALUE_DECIMALS + 3):
        before, after = f"{previous:,.{digits}f}", f"{current:,.{digits}f}"
        if before != after:
            break

    return (
        f'<div class="event-value">'
        f'<span class="ev-prev">{before}</span>'
        f'<span class="ev-arrow {direction}">→</span>'
        f'<span class="ev-now">{after}</span>'
        f'<span class="ev-unit">{unit}</span>'
        f"</div>"
    )


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

    columns.pop(0).markdown(_value_change_html(event, direction), unsafe_allow_html=True)

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
    if st.button("보고서", key=f"report-{log_id}", width="stretch"):
        # 최초 열람은 진단 에이전트 호출을 포함해 수 초가 걸린다(2026-08-10). 무엇을
        # 기다리는지 모르는 채 멈춰 있는 것이 대기 자체보다 나쁘므로 문구로 알린다.
        # 두 번째 열람부터는 report_html 캐시라 스피너가 사실상 보이지 않는다.
        with st.spinner("AI 진단 리포트를 생성하는 중입니다… (최초 열람은 몇 초 걸립니다)"):
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

        # 내용은 환경과 무관하게 항상 화면에 띄운다 (2026-08-10 확정, 05 §3.3).
        # 종전에는 PDF가 만들어지면 다운로드 버튼만 보여줘, 담당자가 파일을 내려받아
        # 열기 전에는 진단 내용을 확인할 수 없었다.
        # HTML 문자열을 그대로 넘기면 srcdoc으로 렌더된다 — 파일시스템을 경유하지 않는다.
        # st.components.v1.html은 2026-06-01자로 제거 예고된 API라 st.iframe을 쓴다.
        st.iframe(result["html"], height=REPORT_VIEWER_HEIGHT_PX)

        # 내려받기는 만들 수 있는 형식으로 하나만 제공한다. 두 개를 함께 두면
        # 담당자가 무엇을 받아야 하는지 고민하게 된다 — PDF가 되면 PDF가 정답이다.
        if result["pdf"] is not None:
            st.download_button(
                "PDF 문서 다운로드",
                data=result["pdf"],
                file_name=f"{view['basename']}.pdf",
                mime="application/pdf",
                width="stretch",
            )
        else:
            st.download_button(
                "HTML 문서 다운로드",
                data=result["html"],
                file_name=f"{view['basename']}.html",
                mime="text/html",
                width="stretch",
            )
            st.caption("이 환경에서는 PDF를 만들 수 없어 HTML로만 내려받을 수 있습니다.")

    _show()
