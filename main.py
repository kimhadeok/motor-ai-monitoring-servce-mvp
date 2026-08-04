"""진입점. 스키마 초기화 + 전역 스타일 + 로그인 상태에 따른 페이지 라우팅."""

import streamlit as st

from app.db.init_db import ensure_schema
from app.ui.navigation import run
from app.ui.styles import inject_global_styles

st.set_page_config(page_title="모터 AI 모니터링 서비스", layout="wide")

ensure_schema()
inject_global_styles()
run()
