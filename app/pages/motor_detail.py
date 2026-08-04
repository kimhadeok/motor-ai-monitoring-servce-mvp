"""모터 상세 페이지. 05_ui_screens.md §4. 스캐폴딩 단계: 레이아웃 뼈대만."""

import streamlit as st

motor_id = st.session_state.get("selected_motor_id")

st.title("모터 상세")

if not motor_id:
    st.warning("메인 대시보드에서 모터를 먼저 선택해주세요.")
else:
    st.subheader(f"모터 ID: {motor_id}")
    st.info("기본 정보 / 지표별 임계값 / 정비 완료 처리 / 이벤트 리스트 구현 예정 (05_ui_screens.md §4)")
