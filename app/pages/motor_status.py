"""모터 현황 페이지 (재정리안 2페이지).

라디오 버튼으로 그룹핑 방식을 고르고, 그룹 헤더 아래 모터 카드를 반응형으로 배치한다.
카드 클릭 시 상세 페이지로 이동한다.

- 상태별 그룹핑: FAULT → DANGER → WARNING → NORMAL
- 위치별 그룹핑: installation_location 기준
- 확인사항 그룹핑: FAULT → DANGER → WARNING (NORMAL 제외)

그룹핑 기본값과 순서는 config(=환경설정)에서 관리한다. 한 그룹의 카드를 단일 컬럼 블록에
넣고 CSS(styles.py)가 flex-wrap으로 감싸, 한 줄 카드 수가 화면 폭에 맞춰 자동으로 줄어든다
(최대 STATUS_CARDS_PER_ROW). 카드 폭은 STATUS_CARD_MIN_WIDTH_PX 밑으로는 내려가지 않는다.
"""

import streamlit as st

from app.config import (
    DEFAULT_GROUPING_MODE,
    GROUPING_MODE_ISSUE,
    GROUPING_MODE_LOCATION,
    GROUPING_MODES,
    ISSUE_GROUP_ORDER,
    STATUS_CARDS_PER_ROW,
    STATUS_GROUP_ORDER,
)
from app.db.connection import connection_scope
from app.services.motors import list_company_motor_status
from app.ui.components import page_header, status_card

page_header(active="status")

_company_id = st.session_state.get("company_id")

st.subheader("모터 현황")

_mode = st.radio(
    "그룹핑 방식 선택",
    options=list(GROUPING_MODES.keys()),
    format_func=lambda key: GROUPING_MODES[key],
    index=list(GROUPING_MODES.keys()).index(DEFAULT_GROUPING_MODE),
    horizontal=True,
    key="status_grouping_mode",
)

with connection_scope() as conn:
    _motors = list_company_motor_status(conn, _company_id)

if not _motors:
    st.info("등록된 모터가 없습니다.")
    st.stop()


def _grouped() -> list[tuple[str, list[dict]]]:
    """(그룹 라벨, 모터 목록) 리스트를 그룹핑 방식에 맞게 구성한다. 빈 그룹은 제외한다."""
    if _mode == GROUPING_MODE_LOCATION:
        buckets: dict[str, list[dict]] = {}
        for motor in _motors:
            buckets.setdefault(motor["installation_location"], []).append(motor)
        return [(location, buckets[location]) for location in sorted(buckets)]

    order = ISSUE_GROUP_ORDER if _mode == GROUPING_MODE_ISSUE else STATUS_GROUP_ORDER
    groups = []
    for status in order:
        members = [motor for motor in _motors if motor["status"] == status]
        if members:
            groups.append((f"[{status}]", members))
    return groups


_groups = _grouped()

if not _groups:
    st.info("해당 조건에 표시할 모터가 없습니다.")
    st.stop()

st.caption(
    f"총 {len(_motors):,}대 · 가로 최대 {STATUS_CARDS_PER_ROW}개(화면 폭에 따라 자동 조절) · "
    "카드를 누르면 상세로 이동합니다."
)

for _label, _members in _groups:
    st.markdown(f"##### {_label} ({len(_members):,}대)")
    # 그룹 카드를 단일 컬럼 블록에 담는다 — CSS가 flex-wrap으로 감싸 반응형 열을 만든다.
    for _column, _motor in zip(st.columns(len(_members)), _members):
        with _column:
            status_card(_motor)
