"""모터 현황 페이지 (재정리안 2페이지).

라디오 버튼으로 그룹핑 방식을 고르고, 그룹 헤더 아래 모터 카드를 반응형으로 배치한다.
카드 클릭 시 상세 페이지로 이동한다.

- 상태별 그룹핑(기본): FAULT → DANGER → WARNING → NORMAL
- 위치별 그룹핑: installation_location 기준

그룹핑 기본값과 순서는 config(=환경설정)에서 관리한다. 한 그룹의 카드를 단일 컬럼 블록에
넣고 CSS(styles.py)가 flex-wrap으로 감싸, 한 줄 카드 수가 화면 폭에 맞춰 자동으로 줄어든다
(최대 STATUS_CARDS_PER_ROW). 카드 폭은 STATUS_CARD_MIN_WIDTH_PX 밑으로는 내려가지 않는다.

**검색**(2026-08-12, 고객 의견): 모터 이름·ID 부분 일치로 목록을 좁힌다. 설비가 200대면
카드를 눈으로 훑어 특정 호기를 찾는 것이 불가능하다.

**"확인 사항 정보" 그룹핑을 뺐다**(2026-08-12 사용자 요청). 상태별 정보와 답하는 질문이
같은데 NORMAL만 빠진 부분집합이었다. 그 옵션이 사라지면서 검색이 NORMAL을 되살려야 하는
예외도 함께 없어졌다 — 이제 어느 그룹핑에서든 정상 설비가 검색된다.
"""

import streamlit as st

from app.config import (
    DEFAULT_GROUPING_MODE,
    GROUPING_MODE_LOCATION,
    GROUPING_MODES,
    STATUS_GROUP_ORDER,
)
from app.db.connection import connection_scope
from app.services.motors import list_company_motor_status
from app.ui.components import page_header, status_card

# 검색과 그룹핑은 **한 줄에 나란히** 둔다 (2026-08-12 사용자 요청). 둘 다 "무엇을 볼지"를
# 정하는 조작부라 위아래로 쌓으면 카드가 그만큼 아래로 밀린다.
#
# 순서는 **그룹핑 → 검색**이고 각각 화면 폭의 **1/4**씩 쓴다 (2026-08-12 사용자 요청).
# 마지막 칸(2/4)은 비워 둔다 — 조작부가 전체 폭을 차지하면 카드 그리드와 무게가 비슷해져
# 어느 쪽을 먼저 봐야 하는지 흐려진다. 두 박스의 테두리·배경은 `ui/styles.py`에서 한 벌로
# 준다(`.st-key-status_grouping_mode, .st-key-status_search`).
_CONTROL_COLUMNS = [1, 1, 2]

page_header(active="status")

_company_id = st.session_state.get("company_id")

st.subheader("모터 현황")

_mode_col, _search_col, _ = st.columns(_CONTROL_COLUMNS)

# 라디오는 두지 않으면 내용 폭(실측 202px)으로 줄어 옆 검색칸과 어긋난다.
# `width="stretch"`로 컬럼 폭을 채운다.
_mode = _mode_col.radio(
    "그룹핑 방식 선택",
    options=list(GROUPING_MODES.keys()),
    format_func=lambda key: GROUPING_MODES[key],
    index=list(GROUPING_MODES.keys()).index(DEFAULT_GROUPING_MODE),
    horizontal=True,
    key="status_grouping_mode",
    width="stretch",
)

_query = _search_col.text_input(
    "모터 검색",
    placeholder="모터 이름 또는 ID (예: 송풍기, MTR-001)",
    key="status_search",
).strip()

with connection_scope() as conn:
    _motors = list_company_motor_status(conn, _company_id)

if not _motors:
    st.info("등록된 모터가 없습니다.")
    st.stop()

if _query:
    _needle = _query.lower()
    _motors = [
        motor
        for motor in _motors
        if _needle in motor["motor_name"].lower() or _needle in motor["motor_id"].lower()
    ]
    if not _motors:
        st.info(f"'{_query}'와 일치하는 모터가 없습니다. 이름 일부나 모터 ID로 다시 찾아보세요.")
        st.stop()
    st.caption(f"'{_query}' 검색 결과 {len(_motors):,}대")


def _grouped() -> list[tuple[str, list[dict]]]:
    """(그룹 라벨, 모터 목록) 리스트를 그룹핑 방식에 맞게 구성한다. 빈 그룹은 제외한다."""
    if _mode == GROUPING_MODE_LOCATION:
        buckets: dict[str, list[dict]] = {}
        for motor in _motors:
            buckets.setdefault(motor["installation_location"], []).append(motor)
        return [(location, buckets[location]) for location in sorted(buckets)]

    groups = []
    for status in STATUS_GROUP_ORDER:
        members = [motor for motor in _motors if motor["status"] == status]
        if members:
            groups.append((status, members))
    return groups


_groups = _grouped()

if not _groups:
    st.info("해당 조건에 표시할 모터가 없습니다.")
    st.stop()

for _label, _members in _groups:
    st.markdown(f"##### {_label} ({len(_members):,}대)")
    # 그룹 카드를 단일 컬럼 블록에 담는다 — CSS가 flex-wrap으로 감싸 반응형 열을 만든다.
    for _column, _motor in zip(st.columns(len(_members)), _members):
        with _column:
            status_card(_motor)
