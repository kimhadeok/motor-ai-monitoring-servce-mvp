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
| Altair (Vega-Lite) | 모터 그래프 시계열 차트 — `st.altair_chart` (온도/진동/전류/소음). 라인+포인트 마커+상태 임계선. *(Plotly는 의존성에 있으나 현재 미사용 — 그래프는 Altair로 구현)* |
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

### 2.3.1 지식 저장소 3계층 분리 (2026-08-07 확정)

`uploads/Reference/`의 참고 자료(PDF 3종, 117페이지)를 인제스트하면서 지식의 성격에 따라 저장소를 나눴다.

| 계층 | 저장소 | 내용 | 조회 |
|---|---|---|---|
| 관계형 | `data/knowledge/fault_modes.json` (커밋) | 지표 → 고장모드 → 부품, 징후 시간대 | 메모리 내 필터 (`app/rag/knowledge.py`, `lru_cache`) |
| 서술형 | `data/chroma/` (커밋) | 정비 절차, 실제 고장 사례, 신호 분석 방법론 | 벡터 검색 |
| 제외 | — | Ford 데이터셋 가이드북의 Python 튜토리얼 부분, 제품소개서의 고객 레퍼런스·회사 연혁 | — |

**그래프DB를 도입하지 않은 이유.** 자료에 그래프 형태의 내용(지표→고장모드→조치 매핑, 보전 분류 트리, 징후 시간 체인)이 실재하지만 고장모드 9건 + 지표 매핑 17건으로 **총 26행**이고, 조회 깊이가 최대 2홉이며, 런타임 테이블(`motors`/`motor_telemetry`)과 조인할 지점이 없다. SQLite 테이블조차 과설계라 커밋된 JSON을 직접 읽는다. 그래프DB는 가변 깊이 순회에서 값어치가 나오는데 이 데이터에는 그런 질의가 없다.

**자동 파싱을 쓰지 않고 수작업 큐레이션한 이유.** 위 그래프성 내용은 PDF 안에서 전부 **도형**으로 그려져 있다. pymupdf(`sort=True`)로 추출하면 계층이 소실된 좌표 순서 나열이 되고, pypdf는 한/영이 뒤섞인다(`엔진 진동 데이터셋Ford AI`). 제품소개서는 44페이지에 텍스트가 10,874자뿐이고 임베딩 이미지가 525개다. 따라서 `data/rag_sources/*.txt`로 정제해 커밋하며, 각 문단에 출처 PDF와 페이지를 남긴다.

**인제스트 시점 (2026-08-07 확정).** 원본이 시간에 무관한 정적 텍스트이므로 **부팅 시 인제스트하지 않는다.** `scripts/build_knowledge.py`로 수동 1회 실행하고 산출물 `data/chroma/`(44청크, 1.3MB)를 커밋한다. Community Cloud가 초기화하는 것은 런타임에 쓴 파일이고 커밋된 파일은 체크아웃으로 들어오므로 배포본이 그대로 사용한다.

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
| `st.html` | `<style>` 블록 주입 (전역 CSS) | **확정 — 이 컴포넌트만 DOMPurify 허용 목록에 `<style>`을 명시적으로 추가한다.** `st.markdown` 경로는 `<style>` 처리가 보장되지 않는다 |
| `st.iframe` | 리포트 HTML 인앱 표시 | 확정 — HTML 문자열을 넘기면 `srcdoc`으로 렌더해 파일시스템을 경유하지 않는다. `st.components.v1.html`은 2026-06-01자로 제거가 예고돼 사용하지 않는다 |
| `streamlit-extras` | 배지, 카드, 스타일 메트릭 등 UI 컴포넌트 모음 | 선택 — 커뮤니티 패키지, 개발 속도 향상 목적 |
| `streamlit-lottie` | 모터→API→AI Agent 흐름의 매끄러운 애니메이션 효과 | 선택 — GIF보다 가볍고 반복 재생 안정적 |
| `st.fragment(run_every=...)` | 실시간 그래프/상태 자동 갱신 (10/20/30초 주기) | 확정 — `05_ui_screens.md` §5-2. Streamlit 1.33+ 내장 기능, 추가 패키지 불필요. 지정 함수(차트/카드 영역)만 부분 재실행되어 전체 스크립트 리런보다 가볍고 빠름 |

MVP 기준: `streamlit-extras`, `streamlit-lottie`는 선택 적용(개발 중 필요 시 추가)하고, 실시간 갱신은 `st.fragment(run_every=...)`로 확정 적용 (전체 리런 방식인 `streamlit-autorefresh`는 채택하지 않음 — 성능상 불리). 컬러 코딩 등 핵심 요구사항은 커스텀 CSS로 우선 구현.

**흐름 애니메이션은 `streamlit-lottie` 대신 커스텀 CSS 키프레임으로 확정** (`05_ui_screens.md` §3.2). Lottie는 애니메이션 JSON을 외부에서 받아와야 해 오프라인·CSP 제약이 있는 반면, CSS 키프레임은 추가 의존성과 네트워크 요청이 전혀 없다.

### 2.5-1 화면 검증 도구 (2026-08-05 추가)

| 기술 | 용도 | 비고 |
|---|---|---|
| `playwright` (dev 의존성) | 실행 중인 앱을 헤드리스 Chromium으로 열어 **화면을 캡처**. `scripts/screenshot.py` | dev 전용이라 배포용 `requirements.txt`(`--no-dev` export)에는 포함되지 않는다 |

**필요한 이유**: Streamlit의 `AppTest`는 어떤 위젯이 만들어졌고 어떤 HTML/CSS 문자열이 나갔는지만 검증한다. **레이아웃 붕괴, 색 대비, 요소 겹침 같은 렌더 결과는 보지 못한다.** 실제로 이 공백 때문에 화면이 깨진 채 전달된 사례가 반복됐다.

```bash
uv run streamlit run main.py --server.port 8501 --server.headless true   # 앱 먼저 실행
uv run python scripts/screenshot.py --out <디렉터리> --theme dark --detail
```

- 로그인 → 대시보드 → 상세까지 실제로 클릭하며 진행하고 단계별로 캡처한다.
- 테마는 `prefers-color-scheme` 에뮬레이션(`color_scheme`)으로 바꾼다. Streamlit 기본값이 "Use system setting"이라 저장된 선택이 없으면 이 값을 따른다. **localStorage 키를 직접 조작하는 방식은 키 이름이 내부 구현이라 버전에 따라 깨진다** (실제로 시도했다가 실패했다).

**한계**: 헤드리스 Chromium은 실제 브라우저와 폰트 렌더링이 달라 글자 줄바꿈·잘림이 완전히 같지 않다. 레이아웃 붕괴와 색 문제는 잡히지만 **최종 확인은 실제 브라우저가 기준**이다.

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
