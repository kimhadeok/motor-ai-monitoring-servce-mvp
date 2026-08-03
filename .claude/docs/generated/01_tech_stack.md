# 01. 기술 스택 및 개발 환경

> 원본: `.claude/docs/서비스 및 개발 환경.md`
> 작성: coreagent · 상태: 확정 (MVP 기준)

## 1. 개발 언어

| 구분 | 사용 언어 |
|---|---|
| 백엔드 / 로직 / AI 에이전트 | Python |
| 프론트엔드 마크업/스타일/스크립트 | HTML5, CSS, JavaScript |

## 2. 레이어별 기술 스택

### 2.1 프론트엔드 (MVP)

| 기술 | 용도 |
|---|---|
| Streamlit | 웹 대시보드 UI 프레임워크 |
| Plotly | 실시간 시계열 차트 (온도/진동/전류/소음) |
| Jinja2 | 리포트 HTML 템플릿 렌더링 |
| WeasyPrint | HTML → PDF 변환 |
| Pango, Cairo, GLib | WeasyPrint의 렌더링 의존 라이브러리 (PDF 생성 시 폰트/레이아웃 처리) |

### 2.2 AI 에이전트 & 오케스트레이션

| 기술 | 용도 |
|---|---|
| LangChain | LLM 호출, 도구(Tool) 정의 및 실행 |
| LangGraph | 에이전트 실행 흐름(상태 그래프) 오케스트레이션 |

### 2.3 데이터베이스

| 기술 | 용도 |
|---|---|
| ChromaDB | Vector DB — RAG 지식베이스(제조사 매뉴얼, 과거 장애 이력) 검색 |
| SQLite | 관계형/시계열 데이터 저장 (companies, motors, motor_telemetry 등) — MVP 기준 확정 |

### 2.4 LLM 모델

| 역할 | 모델 |
|---|---|
| 라우터 (의도 판단/경량 처리) | GPT-4o-mini |
| 추론 (진단/RCA 등 핵심 분석) | GPT-4o |
| 비고 | MVP 기준 확정. 정식 서비스 단계에서 모델 재검토 가능 |

### 2.5 화면 스타일링 (보강)

`화면구성.md` 원본에는 상태별 컬러 코딩, 모터 이미지 → API → AI Agent 흐름의 애니메이션 효과, 카드/배지형 상태 표시 등 커스텀 디자인 요구사항이 있으나 원본 기술 스택 문서에는 이를 구현할 패키지가 누락되어 있어 보강함.

| 기술 | 용도 | 비고 |
|---|---|---|
| 커스텀 CSS (`st.markdown(unsafe_allow_html=True)`) | 상태별 컬러 코딩, 배지/카드 스타일 | 추가 패키지 불필요 |
| `st.components.v1.html` | 커스텀 HTML/CSS/JS 삽입 (흐름 애니메이션 등) | Streamlit 내장 기능, 추가 패키지 불필요 |
| `streamlit-extras` | 배지, 카드, 스타일 메트릭 등 UI 컴포넌트 모음 | 선택 — 커뮤니티 패키지, 개발 속도 향상 목적 |
| `streamlit-lottie` | 모터→API→AI Agent 흐름의 매끄러운 애니메이션 효과 | 선택 — GIF보다 가볍고 반복 재생 안정적 |
| `st.fragment(run_every=...)` | 실시간 그래프/상태 자동 갱신 (10/20/30초 주기) | 확정 — `05_ui_screens.md` §5-2. Streamlit 1.33+ 내장 기능, 추가 패키지 불필요. 지정 함수(차트/카드 영역)만 부분 재실행되어 전체 스크립트 리런보다 가볍고 빠름 |

MVP 기준: `streamlit-extras`, `streamlit-lottie`는 선택 적용(개발 중 필요 시 추가)하고, 실시간 갱신은 `st.fragment(run_every=...)`로 확정 적용 (전체 리런 방식인 `streamlit-autorefresh`는 채택하지 않음 — 성능상 불리). 컬러 코딩 등 핵심 요구사항은 커스텀 CSS로 우선 구현.

## 3. MVP 범위 관련 참고

본 프로젝트는 `.claude/docs/`의 원본 문서(전체 서비스 기준 초안)를 **MVP 범위로 축소 적용**함:

- **관계형 DB**: `테이블 설계.md`의 `motor_telemetry` 테이블은 `TIMESTAMPTZ` PK + `Hypertable`(TimescaleDB 개념)로 표기되어 있으나, MVP 단계에서는 **SQLite**를 기준으로 함. `Hypertable`은 적용하지 않으며, 시계열 데이터는 일반 테이블 + 인덱스로 구현. (→ `04_database_schema.md`에 반영)
- **LLM 모델**: 라우터 GPT-4o-mini / 추론 GPT-4o로 확정 적용. 추가 검토 없이 이 값을 기준으로 진행.

---
승인해주시면 다음 문서(`02_architecture.md`) 작성을 진행하겠습니다.
