"""진입점. 데모 데이터 부트스트랩 + 전역 스타일 + 로그인 상태에 따른 페이지 라우팅."""

import streamlit as st

from app.logging_setup import configure_logging
from app.services.bootstrap import ensure_demo_data
from app.ui.navigation import run
from app.ui.styles import inject_global_styles

st.set_page_config(page_title="모터 AI 모니터링 서비스", layout="wide")

# 부트스트랩보다 먼저 — 부팅 요약이 첫 로그다 (02_architecture.md §6.5).
# 배포 환경에서 앱 내부 상태를 볼 통로는 Manage app 로그뿐이다.
configure_logging()

# 스키마 보장 → (필요 시) 데모 시드 → RAG 적재 확인까지 프로세스당 1회.
# RAG 인제스트와 리포트 HTML 생성은 부팅에 없다 (02_architecture.md §6.1).
_bootstrap = ensure_demo_data()
if _bootstrap.get("error"):
    st.warning("시연용 데이터 준비 중 문제가 발생했습니다. 일부 화면이 비어 있을 수 있습니다.")

inject_global_styles()
run()
