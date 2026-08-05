"""로그인 페이지. 05_ui_screens.md §2.

고객이 서비스를 처음(그리고 로그인 전에는 유일하게) 마주하는 화면이라, 인증 폼만 두지 않고
어떤 서비스인지와 무엇을 해주는지를 함께 보여준다.
"""

import streamlit as st

from app.auth.session import login, start_session
from app.config import (
    DEMO_ACCOUNT_PASSWORD,
    SERVICE_HIGHLIGHTS,
    SERVICE_ICON,
    SERVICE_NAME,
    SERVICE_TAGLINE,
)
from app.db.connection import connection_scope
from app.services.company import list_demo_accounts

# 대시보드 기준의 wide 레이아웃이라 그대로 두면 폼이 화면 전체 폭으로 늘어진다.
_left, _center, _right = st.columns([1, 2, 1])

with _center:
    st.markdown(
        f'<div class="login-hero">'
        f'<div class="icon">{SERVICE_ICON}</div>'
        f'<h1>{SERVICE_NAME}</h1>'
        f'<p class="tagline">{SERVICE_TAGLINE}</p>'
        f"</div>",
        unsafe_allow_html=True,
    )

    with st.form("login_form"):
        email = st.text_input("이메일", placeholder="name@company.com")
        password = st.text_input("비밀번호", type="password", placeholder="••••••••")
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
        with connection_scope() as conn:
            accounts = list_demo_accounts(conn)
        if not accounts:
            st.caption("아직 준비된 계정이 없습니다.")
        else:
            st.caption(f"비밀번호는 모두 `{DEMO_ACCOUNT_PASSWORD}` 입니다.")
            for account in accounts:
                st.markdown(
                    f"- `{account['email']}` — {account['company_name']} "
                    f"{account['contact_name']}"
                )

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
