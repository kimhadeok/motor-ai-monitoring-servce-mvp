# 01. 기술 스택 및 개발 환경

> 원본: `.claude/docs/user/서비스 및 개발 환경.md`
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

**리포트 HTML/PDF 2단 구성 (2026-08-04 확정)**: Jinja2 렌더(HTML)는 순수 Python이라 어떤 환경에서도 성공하지만, WeasyPrint(PDF)는 위 네이티브 라이브러리가 설치된 환경에서만 동작한다. 따라서 리포트는 **HTML을 항상 생성·저장**하고 **PDF는 요청 시 생성**하되, PDF 생성이 불가한 환경에서는 저장된 HTML을 대신 제공한다(`06_report_spec.md` §1). 이로써 네이티브 의존이 없는 개발 환경(Windows 등)과 배포 환경을 모두 만족시킨다.

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

**ChromaDB 임베딩 함수 (2026-08-04 확정)**: ChromaDB 기본 내장 임베딩 함수(`all-MiniLM-L6-v2`, ONNX, 384차원)를 **사용하지 않고**, OpenAI 임베딩 함수(§2.4, 1536차원)를 명시적으로 주입한다.

기본 내장 함수는 첫 사용 시 ONNX 모델을 인터넷에서 내려받아 로컬에 캐시하는데(압축본 83MB, 캐시 총 167MB), 배포 환경인 Streamlit Community Cloud는 재시작 시 파일시스템이 초기화되므로 **앱이 깨어날 때마다 이 다운로드가 반복**된다. 벡터를 미리 만들어 배포해도 회피할 수 없다 — 검색 시 질의문을 임베딩해야 하므로 동일 모델이 필요하기 때문. 실측상 cold start가 20~60초 발생하고 ONNX 런타임 메모리도 수백 MB를 점유한다.

### 2.4 LLM 모델

| 역할 | 모델 |
|---|---|
| 라우터 (의도 판단/경량 처리) | GPT-4o-mini |
| 추론 (진단/RCA 등 핵심 분석) | GPT-4o |
| 임베딩 (RAG 인제스트/검색) | text-embedding-3-small (1536차원) |
| 비고 | MVP 기준 확정. 정식 서비스 단계에서 모델 재검토 가능 |

**임베딩 모델 선정 근거 (2026-08-04 확정)**: 로컬 ONNX 모델 다운로드(83MB)와 수백 MB 메모리 점유를 회피해 cold start를 20~60초에서 약 1.2초로 단축하고, LLM과 동일한 OpenAI 단일 프로바이더를 유지하기 위함. 실측 기준 인제스트 11청크 배치 0.60초(1,140 토큰), 검색 질의 1건 0.23초이며 비용은 인제스트 1회당 $0.00002 수준. 네트워크 의존이 생기므로 **API 호출 실패 시 키워드 매칭으로 폴백**한다(`02_architecture.md` §2.2).

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

### 2.6 배포 환경 및 의존성 관리 (2026-08-04 확정)

| 항목 | 확정 |
|---|---|
| 배포 타겟 | **Streamlit Community Cloud** (공개 무료 호스팅) |
| 의존성 관리 | **uv** (`pyproject.toml` + `uv.lock`) |
| 배포용 의존성 파일 | `requirements.txt` — `uv export --format requirements-txt --no-dev --no-hashes`로 생성해 커밋. uv/pyproject 변경 시마다 재실행 |
| OS 패키지 | `packages.txt` — WeasyPrint 네이티브 의존(Pango 등) 및 한글 폰트(`fonts-noto-cjk`) apt 설치용. Community Cloud가 빌드 시 자동 적용 |
| 시크릿 | 대시보드 Secrets UI(TOML). 로컬은 `.env`(python-dotenv). 조회 우선순위는 `st.secrets` → `os.getenv` |

**한글 폰트**: 리포트가 전문 한글이므로 `fonts-noto-cjk`가 필수다. 기본 컨테이너 이미지에는 한글 글리프 폰트가 없어 PDF의 한글이 깨진다. 리포트 템플릿의 `font-family`도 `Noto Sans CJK KR`을 우선 지정해, 개발 환경(Windows·맑은 고딕)과 배포 환경의 서체가 어긋나지 않도록 한다.

**데이터 영속성 제약**: Community Cloud는 재배포/재시작 시 로컬 파일시스템이 초기화된다. 이 제약에 대한 대응(데모 데이터 런타임 부트스트랩)은 `02_architecture.md` §6에서 확정한다.

**Python 버전**: `pyproject.toml`은 `requires-python = ">=3.14"`이나, Community Cloud의 지원 버전은 배포 시점에 별도 확인이 필요하다. 미지원 시 `runtime.txt`로 버전을 지정하고 `uv lock`/`export`를 재실행한다.

## 3. MVP 범위 관련 참고

본 프로젝트는 `.claude/docs/user/`의 원본 문서(전체 서비스 기준 초안)를 **MVP 범위로 축소 적용**함:

- **관계형 DB**: `테이블 설계.md`의 `motor_telemetry` 테이블은 `TIMESTAMPTZ` PK + `Hypertable`(TimescaleDB 개념)로 표기되어 있으나, MVP 단계에서는 **SQLite**를 기준으로 함. `Hypertable`은 적용하지 않으며, 시계열 데이터는 일반 테이블 + 인덱스로 구현. (→ `04_database_schema.md`에 반영)
- **LLM 모델**: 라우터 GPT-4o-mini / 추론 GPT-4o로 확정 적용. 추가 검토 없이 이 값을 기준으로 진행.

---
승인해주시면 다음 문서(`02_architecture.md`) 작성을 진행하겠습니다.
