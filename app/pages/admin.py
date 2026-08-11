"""관리자 페이지 — 기본 테이블 관리. 05_ui_screens.md §6.

회사 / 담당자 / 모터 / 지표 임계값 네 가지만 다룬다. 텔레메트리·상태로그·알림 같은 시계열은
시드와 런타임 틱이 만들며 여기서 건드리지 않는다.

**자동 갱신을 넣지 않는다.** 입력 중인 폼이 10초마다 다시 그려지면 타이핑하던 값이 날아간다.
관리 화면은 사용자가 저장을 누를 때만 바뀌면 된다.

로그인한 담당자는 **자기 회사 데이터만** 보고 고칠 수 있다(`services/admin.py`가 모든
쿼리를 `company_id`로 좁힌다). 별도의 관리자 권한 개념은 두지 않았다 — `company_contacts`에
role 컬럼이 없고, 시연용 MVP라 도입하지 않기로 했다(2026-08-11 확정).
"""

import streamlit as st

from app.config import (
    ADMIN_THRESHOLD_HISTORY_LIMIT,
    ALLOWED_COLLECTION_INTERVALS_SECONDS,
    DEMO_DATA_MAX_AGE_HOURS,
    format_display,
    parse_utc,
)
from app.db.connection import connection_scope
from app.services.admin import (
    AdminError,
    count_motor_references,
    create_contact,
    create_motor,
    delete_contact,
    delete_motor,
    get_company,
    list_contacts,
    list_motors,
    list_threshold_history,
    list_thresholds,
    update_company,
    update_contact,
    update_motor,
    update_thresholds,
)
from app.ui.components import lock_selectbox_typing, page_header

_NEW = "＋ 새로 추가"
_DELETE_MOTOR_KEY = "admin_delete_motor"
# 셀렉트박스는 전체 폭을 쓸 이유가 없다 — 값이 짧은데 입력칸만 1,400px가 되면 어디를 눌러야
# 하는지 오히려 흐려진다. `st.columns`의 첫 칸에만 그려 폭을 제한한다 (2026-08-11 사용자 요청).
_PICKER_COLUMNS = [2, 2]  # 편집 대상 — "MTR-101 · 11호기 메인 송풍기"가 들어가야 해 2/4
_INTERVAL_COLUMNS = [1, 3]  # 수집 주기 — 값이 두 자리라 1/4로 충분
# 드롭다운 선택만 허용할 셀렉트박스 key (모터 그래프의 표시 범위 필터와 같은 방식).
_LOCKED_SELECT_KEYS = (
    "admin_contact_pick",
    "admin_motor_pick",
    "admin_threshold_pick",
    "admin_motor_interval",
)

page_header(active="admin")

company_id = st.session_state.get("company_id")
current_contact_id = st.session_state.get("contact_id")

st.subheader("관리자")
st.caption(
    "고객 회사 · 담당자 · 모터 · 지표 임계값을 관리합니다. "
    f"계측 데이터는 여기서 다루지 않습니다. 로그인한 회사({company_id})의 정보만 보입니다."
)

# 데이터가 사라지는 조건을 화면이 직접 말한다 — 등록해 두고 다음 날 없어지면 버그로 보인다.
st.warning(
    f"**시연용 데이터입니다.** 앱을 {DEMO_DATA_MAX_AGE_HOURS}시간 이상 껐다가 다시 열면 "
    "데모 데이터가 새로 만들어지면서 여기서 등록·수정한 내용도 초기화됩니다 "
    "(`02_architecture.md` §6.1). 배포본은 재시작할 때마다 초기화됩니다.",
    icon="⚠️",
)

_company_tab, _contact_tab, _motor_tab, _threshold_tab = st.tabs(
    ["고객 회사", "담당자", "모터", "지표 임계값"]
)


def _run(action, success: str) -> None:
    """CRUD 실행 공통 처리 — 규칙 위반은 화면 메시지로, 성공하면 다시 그린다."""
    try:
        with connection_scope() as conn:
            action(conn)
    except AdminError as exc:
        st.error(str(exc))
        return
    st.session_state["admin_flash"] = success
    st.rerun()


if _flash := st.session_state.pop("admin_flash", None):
    st.success(_flash)


# --- 고객 회사 -------------------------------------------------------------
with _company_tab:
    with connection_scope() as conn:
        _company = get_company(conn, company_id)

    if _company is None:
        st.error("회사 정보를 찾을 수 없습니다.")
    else:
        st.caption(
            "회사 추가·삭제는 두지 않습니다 — 자기 회사만 보이는 구조라 추가해도 화면에 "
            "나타나지 않고, 자기 회사를 지우면 로그인이 성립하지 않습니다."
        )
        with st.form("company_form"):
            st.text_input("회사 ID", value=_company["company_id"], disabled=True)
            _name = st.text_input("회사명", value=_company["company_name"])
            if st.form_submit_button("저장", type="primary"):
                _run(
                    lambda conn: update_company(conn, company_id, _name),
                    "회사 정보를 저장했습니다.",
                )


# --- 담당자 ----------------------------------------------------------------
with _contact_tab:
    with connection_scope() as conn:
        _contacts = list_contacts(conn, company_id)

    st.dataframe(
        [
            {
                "ID": c["contact_id"],
                "담당자명": c["contact_name"],
                "연락처": c["phone_number"],
                "이메일": c["email"],
                "대표": "○" if c["is_primary"] else "",
            }
            for c in _contacts
        ],
        hide_index=True,
        width="stretch",
    )

    _options = [_NEW] + [f"{c['contact_id']} · {c['contact_name']}" for c in _contacts]
    _picked = st.columns(_PICKER_COLUMNS)[0].selectbox(
        "편집 대상", _options, key="admin_contact_pick"
    )
    _target = None if _picked == _NEW else _contacts[_options.index(_picked) - 1]

    with st.form("contact_form"):
        _cname = st.text_input("담당자명", value=_target["contact_name"] if _target else "")
        _cphone = st.text_input(
            "연락처", value=_target["phone_number"] if _target else "", placeholder="010-0000-0000"
        )
        _cmail = st.text_input(
            "이메일 (로그인 ID로 사용합니다.)", value=_target["email"] if _target else ""
        )
        _cpw = st.text_input(
            "비밀번호",
            type="password",
            help="수정할 때는 비워 두면 기존 비밀번호를 유지합니다.",
        )
        _cprimary = st.checkbox("대표 담당자", value=bool(_target["is_primary"]) if _target else False)

        _save_col, _delete_col = st.columns([1, 1])
        _save = _save_col.form_submit_button(
            "등록" if _target is None else "저장", type="primary", width="stretch"
        )
        _delete = _delete_col.form_submit_button(
            "삭제", disabled=_target is None, width="stretch"
        )

    if _save:
        if _target is None:
            _run(
                lambda conn: create_contact(
                    conn, company_id, _cname, _cphone, _cmail, _cpw, _cprimary
                ),
                f"담당자 '{_cname}'을(를) 등록했습니다.",
            )
        else:
            _run(
                lambda conn: update_contact(
                    conn,
                    company_id,
                    _target["contact_id"],
                    _cname,
                    _cphone,
                    _cmail,
                    _cprimary,
                    _cpw,
                ),
                f"담당자 '{_cname}'을(를) 저장했습니다.",
            )
    if _delete and _target is not None:
        _run(
            lambda conn: delete_contact(
                conn, company_id, _target["contact_id"], current_contact_id
            ),
            f"담당자 '{_target['contact_name']}'을(를) 삭제했습니다.",
        )
    st.caption(
        "담당자를 삭제하면 그 담당자에게 나간 **알림 이력이 함께 삭제**됩니다. "
        "정비 확인·로그인 이력은 담당자 참조만 지우고 기록은 남깁니다. "
        "로그인 중인 본인과 회사의 마지막 담당자는 삭제할 수 없습니다."
    )


# --- 모터 ------------------------------------------------------------------
with _motor_tab:
    with connection_scope() as conn:
        _motors = list_motors(conn, company_id)

    st.caption(f"등록된 모터 {len(_motors)}대")
    st.dataframe(
        [
            {
                "모터 ID": m["motor_id"],
                "모터명": m["motor_name"],
                "설치 위치": m["installation_location"],
                "모델명": m["model_name"],
                "시리얼": m["serial_number"] or "",
                "수집 주기(초)": m["collection_interval_seconds"],
            }
            for m in _motors
        ],
        hide_index=True,
        width="stretch",
        height=280,
    )

    _m_options = [_NEW] + [f"{m['motor_id']} · {m['motor_name']}" for m in _motors]
    _m_picked = st.columns(_PICKER_COLUMNS)[0].selectbox(
        "편집 대상", _m_options, key="admin_motor_pick"
    )
    _m_target = None if _m_picked == _NEW else _motors[_m_options.index(_m_picked) - 1]

    with st.form("motor_form"):
        _mid = st.text_input(
            "모터 ID",
            value=_m_target["motor_id"] if _m_target else "",
            disabled=_m_target is not None,
            help="등록 후에는 바꿀 수 없습니다 — 계측 데이터가 이 값을 참조합니다.",
            placeholder="MTR-301",
        )
        _mname = st.text_input("모터명", value=_m_target["motor_name"] if _m_target else "")
        _mloc = st.text_input(
            "설치 위치", value=_m_target["installation_location"] if _m_target else ""
        )
        _mmodel = st.text_input("모델명", value=_m_target["model_name"] if _m_target else "")
        _mserial = st.text_input(
            "시리얼 번호", value=(_m_target["serial_number"] or "") if _m_target else ""
        )
        _minterval = st.columns(_INTERVAL_COLUMNS)[0].selectbox(
            "수집 주기(초)",
            ALLOWED_COLLECTION_INTERVALS_SECONDS,
            key="admin_motor_interval",
            index=(
                ALLOWED_COLLECTION_INTERVALS_SECONDS.index(
                    _m_target["collection_interval_seconds"]
                )
                if _m_target
                and _m_target["collection_interval_seconds"] in ALLOWED_COLLECTION_INTERVALS_SECONDS
                else 0
            ),
        )

        _ms_col, _md_col = st.columns([1, 1])
        _m_save = _ms_col.form_submit_button(
            "등록" if _m_target is None else "저장", type="primary", width="stretch"
        )
        _m_delete = _md_col.form_submit_button(
            "삭제", disabled=_m_target is None, width="stretch"
        )

    if _m_save:
        if _m_target is None:
            _run(
                lambda conn: create_motor(
                    conn, company_id, _mid, _mname, _mloc, _mmodel, _mserial, _minterval
                ),
                f"모터 '{_mname}'을(를) 등록했습니다. 지표 임계값 4건도 기본값으로 만들었습니다.",
            )
        else:
            _run(
                lambda conn: update_motor(
                    conn,
                    company_id,
                    _m_target["motor_id"],
                    _mname,
                    _mloc,
                    _mmodel,
                    _mserial,
                    _minterval,
                ),
                f"모터 '{_mname}'을(를) 저장했습니다.",
            )
    if _m_delete and _m_target is not None:
        # 딸린 행이 수만 건일 수 있어 바로 지우지 않고 건수를 보여준 뒤 확인받는다.
        with connection_scope() as conn:
            _refs = count_motor_references(conn, _m_target["motor_id"])
        st.session_state[_DELETE_MOTOR_KEY] = {
            "motor_id": _m_target["motor_id"],
            "motor_name": _m_target["motor_name"],
            "refs": _refs,
        }
        st.rerun()

    st.caption(
        "**새로 등록한 모터에는 계측값이 없습니다.** 시드는 부팅 때 한 번만 돌고 런타임 틱은 "
        "기존 데이터가 있는 모터만 이어 붙이므로, 대시보드 카드에 '수집된 계측값이 없습니다'로 "
        "표시되는 것이 정상입니다."
    )


def _render_motor_delete_dialog() -> None:
    """모터 삭제 확인. 함께 지워질 행 수를 먼저 보여준다."""
    pending = st.session_state.get(_DELETE_MOTOR_KEY)
    if not pending:
        return

    @st.dialog("모터 삭제 확인", on_dismiss=lambda: st.session_state.pop(_DELETE_MOTOR_KEY, None))
    def _dialog() -> None:
        refs = pending["refs"]
        st.write(f"**{pending['motor_name']}** ({pending['motor_id']})를 삭제합니다.")
        st.markdown(
            f"- 텔레메트리 **{refs['telemetry']:,}행**\n"
            f"- 상태 전이 로그 **{refs['status_logs']:,}건** (리포트 포함)\n"
            f"- 알림 이력 **{refs['notifications']:,}건**\n"
            "- 지표 임계값 4건"
        )
        st.caption("위 데이터가 함께 삭제되며 되돌릴 수 없습니다.")
        agreed = st.checkbox("삭제에 동의합니다.")
        confirm_col, cancel_col = st.columns(2)
        if confirm_col.button("삭제", type="primary", disabled=not agreed, width="stretch"):
            motor_id, motor_name = pending["motor_id"], pending["motor_name"]
            st.session_state.pop(_DELETE_MOTOR_KEY, None)
            _run(
                lambda conn: delete_motor(conn, company_id, motor_id),
                f"모터 '{motor_name}'을(를) 삭제했습니다.",
            )
        if cancel_col.button("취소", width="stretch"):
            st.session_state.pop(_DELETE_MOTOR_KEY, None)
            st.rerun()

    _dialog()


# --- 지표 임계값 -----------------------------------------------------------
with _threshold_tab:
    if not _motors:
        st.info("등록된 모터가 없습니다.")
    else:
        _t_options = [f"{m['motor_id']} · {m['motor_name']}" for m in _motors]
        _t_picked = st.columns(_PICKER_COLUMNS)[0].selectbox(
            "모터", _t_options, key="admin_threshold_pick"
        )
        _t_motor = _motors[_t_options.index(_t_picked)]

        with connection_scope() as conn:
            _rows = list_thresholds(conn, company_id, _t_motor["motor_id"])

        st.caption(
            "판정 규칙: 값 ≥ 고장 → FAULT, ≥ 위험 → DANGER, ≥ 경고 → WARNING, 그 외 정상. "
            "정상 < 경고 < 위험 < 고장 순으로 커져야 저장됩니다."
        )
        st.info(
            "**바꾼 기준은 다음 수집분부터 적용됩니다.** 이미 저장된 판정과 발행된 리포트는 "
            "그대로 둡니다 — 사후에 과거 판정을 뒤집으면 이미 나간 리포트·알림과 어긋나기 "
            f"때문입니다. 이 모터의 수집 주기는 {_t_motor['collection_interval_seconds']}초입니다. "
            "게이지 눈금·차트 임계선처럼 '지금 기준'을 보여주는 표시는 즉시 바뀝니다.",
            icon="🕒",
        )
        _edited = st.data_editor(
            [
                {
                    "지표": r["label"],
                    "정상": r["normal_range"],
                    "경고": r["warning_range"],
                    "위험": r["danger_range"],
                    "고장": r["fault_range"],
                }
                for r in _rows
            ],
            hide_index=True,
            width="stretch",
            disabled=["지표"],
            key=f"admin_thresholds_{_t_motor['motor_id']}",
        )

        if st.button("임계값 저장", type="primary", key="admin_threshold_save"):
            _payload = [
                {
                    "metric_name": _rows[i]["metric_name"],
                    "label": _rows[i]["label"],
                    "normal_range": row["정상"],
                    "warning_range": row["경고"],
                    "danger_range": row["위험"],
                    "fault_range": row["고장"],
                }
                for i, row in enumerate(_edited)
            ]
            _run(
                lambda conn: update_thresholds(
                    conn, company_id, _t_motor["motor_id"], _payload, current_contact_id
                ),
                f"{_t_motor['motor_name']}의 지표 임계값을 저장했습니다. "
                "다음 수집분부터 새 기준으로 판정됩니다.",
            )

        with connection_scope() as conn:
            _history = list_threshold_history(
                conn, company_id, _t_motor["motor_id"], ADMIN_THRESHOLD_HISTORY_LIMIT
            )
        st.markdown("**변경 이력**")
        if not _history:
            st.caption("이 모터의 임계값을 아직 바꾼 적이 없습니다.")
        else:
            st.dataframe(
                [
                    {
                        "변경 일시": format_display(parse_utc(h["created_at"])),
                        "지표": h["label"],
                        "이전 (정상/경고/위험/고장)": " / ".join(
                            "-" if v is None else f"{v:g}" for v in h["before"]
                        ),
                        "변경 (정상/경고/위험/고장)": " / ".join(
                            "-" if v is None else f"{v:g}" for v in h["after"]
                        ),
                        "변경자": h["contact_name"],
                    }
                    for h in _history
                ],
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "임계값은 바꾼 시점 이후 수집분부터 적용됩니다. 과거 전이와 리포트가 "
                "어느 기준으로 판정된 것인지 이 이력으로 확인할 수 있습니다."
            )


_render_motor_delete_dialog()

# 셀렉트박스는 드롭다운 선택만 허용한다 — 목록에 없는 값을 타이핑해 넣을 이유가 없다.
# 모든 위젯이 그려진 뒤에 걸어야 한다(스크립트가 부모 DOM에서 입력을 찾는다).
lock_selectbox_typing(*_LOCKED_SELECT_KEYS)
