"""로그인 페이지. 05_ui_screens.md §2.

고객이 서비스를 처음(그리고 로그인 전에는 유일하게) 마주하는 화면이라, 인증 폼만 두지 않고
어떤 서비스인지와 무엇을 해주는지를 함께 보여준다.
"""

import streamlit as st

from app.auth.session import login, start_session
from app.config import (
    DEMO_ACCOUNT_PASSWORD,
    PREFILL_DEMO_CREDENTIALS,
    SERVICE_HIGHLIGHTS,
    SERVICE_ICON,
    SERVICE_NAME,
    SERVICE_TAGLINE,
)
from app.db.connection import connection_scope
from app.services.company import list_demo_accounts

_EMAIL_KEY = "login_email"
_PASSWORD_KEY = "login_password"
_PENDING_KEY = "login_prefill_request"

with connection_scope() as conn:
    _accounts = list_demo_accounts(conn)


def _fill(email: str) -> None:
    st.session_state[_EMAIL_KEY] = email
    st.session_state[_PASSWORD_KEY] = DEMO_ACCOUNT_PASSWORD


# 폼 위젯이 만들어지기 전에 채워야 한다 — Streamlit은 위젯 생성 이후 그 key의
# session_state 변경을 막는다. 아래 [채우기] 버튼은 요청만 남기고 리런한다.
_requested = st.session_state.pop(_PENDING_KEY, None)
if _requested:
    _fill(_requested)
# 시연·개발 중 매번 계정을 입력하지 않도록 첫 진입에만 기본값을 채운다.
# 이후에는 사용자가 지운 값을 다시 되살리지 않는다.
elif PREFILL_DEMO_CREDENTIALS and _accounts and _EMAIL_KEY not in st.session_state:
    _fill(_accounts[0]["email"])

# 대시보드 기준의 wide 레이아웃이라 그대로 두면 폼이 화면 전체 폭으로 늘어진다.
_left, _center, _right = st.columns([1, 2, 1])

with _center:
    st.markdown(
        f'<div class="login-hero">'
        f'<div class="icon">{SERVICE_ICON}</div>'
        f"<h1>{SERVICE_NAME}</h1>"
        f'<p class="tagline">{SERVICE_TAGLINE}</p>'
        f"</div>",
        unsafe_allow_html=True,
    )

    with st.form("login_form"):
        email = st.text_input("이메일", key=_EMAIL_KEY, placeholder="name@company.com")
        password = st.text_input(
            "비밀번호", key=_PASSWORD_KEY, type="password", placeholder="••••••••"
        )
        submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)

    if submitted:
        # 스캐폴딩 단계: 실제 배포 시 프록시/헤더 기반 클라이언트 IP 추출 로직으로 대체 필요
        client_ip = st.context.headers.get("X-Forwarded-For", "127.0.0.1")
        result = login(email=email, password=password, ip_address=client_ip)
        if result.success:
            start_session(result)
            st.rerun()
        else:
            st.error(result.error)

    with st.expander("시연용 계정 보기"):
        if not _accounts:
            st.caption("아직 준비된 계정이 없습니다.")
        else:
            st.caption(f"비밀번호는 모두 `{DEMO_ACCOUNT_PASSWORD}` 입니다.")
            for account in _accounts:
                info_col, action_col = st.columns([3, 1], vertical_alignment="center")
                info_col.markdown(
                    f"`{account['email']}`  \n"
                    f"{account['company_name']} {account['contact_name']}"
                )
                # 계정을 오갈 때 다시 타이핑하지 않도록 폼에 바로 채워준다.
                # 여기서 위젯 key를 직접 바꿀 수 없어(위젯이 이미 생성됨) 요청만 남긴다.
                if action_col.button(
                    "채우기", key=f"fill-{account['email']}", use_container_width=True
                ):
                    st.session_state[_PENDING_KEY] = account["email"]
                    st.rerun()

    st.markdown(
        '<div class="login-highlights">'
        + "".join(
            f'<div class="item"><span class="icon">{icon}</span>'
            f'<span class="title">{title}</span>'
            f'<span class="desc">{desc}</span></div>'
            for icon, title, desc in SERVICE_HIGHLIGHTS
        )
        + "</div>",
        unsafe_allow_html=True,
    )
