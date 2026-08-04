"""메인 대시보드. 05_ui_screens.md §3. 스캐폴딩 단계: 레이아웃 뼈대만 — 실데이터 연동은 이후 작업."""

import streamlit as st

from app.auth.session import end_session

st.title("메인 대시보드")

with st.sidebar:
    st.write(f"담당자: {st.session_state.get('contact_name', '')}")
    if st.button("로그아웃"):
        end_session()
        st.rerun()

col1, col2, col3, col4 = st.columns(4)
col1.metric("등록된 모터 수", "구현 예정")
col2.metric("서비스 시작 일자", "구현 예정")
col3.metric("총 운영 일수", "구현 예정")
col4.metric("주의 이상 모터 수", "구현 예정")

st.subheader("모터 현황")
st.info("모터별 카드 UI 구현 예정 (05_ui_screens.md §3.2)")

st.subheader("이벤트 발생 내역")
st.info("motor_status_logs 기반 이벤트 리스트 구현 예정 (05_ui_screens.md §3.3)")
