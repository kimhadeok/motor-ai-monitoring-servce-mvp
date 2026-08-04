"""로그인 페이지. 05_ui_screens.md §2."""

import streamlit as st

from app.auth.session import login, start_session

st.title("로그인")

with st.form("login_form"):
    email = st.text_input("이메일")
    password = st.text_input("비밀번호", type="password")
    submitted = st.form_submit_button("로그인")

if submitted:
    # 스캐폴딩 단계: 실제 배포 시 프록시/헤더 기반 클라이언트 IP 추출 로직으로 대체 필요
    client_ip = st.context.headers.get("X-Forwarded-For", "127.0.0.1")
    result = login(email=email, password=password, ip_address=client_ip)
    if result.success:
        start_session(result)
        st.rerun()
    else:
        st.error(result.error)
