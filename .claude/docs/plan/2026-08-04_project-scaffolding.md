# 모터 AI 모니터링 서비스 MVP — 프로젝트 스캐폴딩

## Context

`.claude/docs/generated/`의 6개 확정 문서(01~06)에 대한 정합성 검토가 끝나고, 이번 대화에서 다음 아키텍처 결정이 추가로 확정됨:

- **배포 타겟**: Streamlit Community Cloud(공개 무료 호스팅). 특별한 요구사항이 없는 한 앞으로 이 환경 기준으로 개발.
- **의존성 관리**: `uv` (pyproject.toml + uv.lock), 배포용 `requirements.txt`는 uv에서 export해 별도 유지.
- **데이터 영속성 전략**: Streamlit Community Cloud는 재배포/재시작 시 로컬 파일시스템이 초기화될 수 있음 → 런타임 관리자 페이지 없이, **배포 전 로컬 1회성 시드 스크립트**로 시연용 데이터(SQLite DB, ChromaDB persist 디렉터리, PDF 바이너리 포함)를 만들어 **git에 커밋**하는 방식으로 대응. 재배포돼도 커밋된 시드 상태로 복원됨.
- **PDF 리포트 저장 방식**: 파일시스템에 저장하지 않고 `motor_status_logs`에 BLOB 컬럼(`report_pdf`)을 추가해 PDF 바이너리를 DB에 직접 저장. [보고서] 버튼 클릭 시 그 BLOB을 메모리에서 읽어 즉시 다운로드/표시. 기존 `agent_diagnosis`(PDF URL, TEXT) 컬럼을 대체(rename+retype) — "PDF를 가리키는 참조값"이라는 동일 목적을 유지하되 형태만 URL→바이너리로 바뀌는 것이므로 별도 컬럼을 추가하지 않음.

지금까지 저장소엔 소스 코드가 전혀 없음(문서만 존재). 이번 작업의 목적은 "전체 기능 구현"이 아니라 **폴더 구조 + 문서 정합성 반영 + 최소 실행 가능한 뼈대 + 시연용 시드 데이터 생성**까지다. 실제 AI 에이전트(LangGraph 진단 로직)와 대시보드 실데이터 렌더링 등은 이후 별도 작업.

## 참고 컨벤션 (메모리에 저장됨)
- 구현 시 `.claude/docs/generated/`만 참고, `.claude/docs/user/`는 참고하지 않음.
- 계획 승인 후 이 계획을 `D:\projects\motor-ai-monitoring-servce-mvp\.claude\docs\plan\`에도 저장 (CLAUDE.md 컨벤션).

---

## 1단계 — 생성 문서 정합성 반영 (report_pdf 변경)

이미 확정된 `04`/`05`/`06` 문서에 이번 결정(PDF BLOB 저장)을 반영:

- **`04_database_schema.md` §3.5**: `agent_diagnosis TEXT` (PDF URL) → `report_pdf BLOB` (PDF 바이너리, 파일시스템 미사용)로 변경. §2 관계 요약 등 다른 곳에서 `agent_diagnosis`를 언급하는 부분이 있으면 함께 정정.
- **`06_report_spec.md` §1**: "PDF 파일 저장 후 URL을 `motor_status_logs.agent_diagnosis`에 기록" → "PDF 바이너리를 `motor_status_logs.report_pdf`(BLOB)에 직접 저장 (파일시스템 미사용)"으로 수정.
- **`05_ui_screens.md` §3.3, §4.4**: "`agent_diagnosis`(PDF URL) 값이 있는 로그에만 노출" → "`report_pdf`(BLOB) 값이 NULL이 아닌 로그에만 노출, 클릭 시 메모리에서 즉시 다운로드 제공"으로 수정.

## 2단계 — 프로젝트 스캐폴딩

### 폴더 구조

```
motor-ai-monitoring-servce-mvp/
├── main.py                          # 진입점: pysqlite3 우회 패치 + ensure_schema() + st.navigation 부팅
├── pyproject.toml                   # uv 프로젝트 정의
├── requirements.txt                 # `uv export`로 생성, Streamlit Cloud 배포용
├── packages.txt                     # WeasyPrint용 apt 패키지 (Streamlit Cloud 전용)
├── .env.example
├── README.md                        # 실행/배포/시딩 안내
├── .streamlit/
│   ├── config.toml                  # 테마(브랜드 컬러)
│   └── secrets.toml.example         # st.secrets 템플릿 (실 파일은 gitignore)
├── app/
│   ├── config.py                    # 중앙 설정값 (아래 목록)
│   ├── prompts.py                   # LLM 프롬프트 문자열 전용 (빈 placeholder, 이후 작업)
│   ├── db/
│   │   ├── schema.sql                # 04 DDL 전문 (report_pdf 반영본)
│   │   ├── connection.py             # sqlite3 커넥션 헬퍼
│   │   └── init_db.py                # ensure_schema() — CREATE TABLE IF NOT EXISTS, idempotent
│   ├── rag/
│   │   └── chroma_client.py          # pysqlite3 우회 패치(try/except) + PersistentClient 팩토리
│   ├── auth/
│   │   └── session.py                # login() 검증, login_logs 기록, session_state 헬퍼
│   ├── services/                     # 이후 비즈니스 로직 (빈 placeholder)
│   ├── agents/                       # 이후 LangChain/LangGraph 에이전트 (빈 placeholder)
│   ├── reports/
│   │   ├── templates/report_template.html  # 06_report_template_sample.html 기반 Jinja2 바인딩
│   │   └── generator.py              # render_report_pdf(context) -> bytes (메모리 내 렌더, 디스크 미기록)
│   ├── ui/
│   │   ├── navigation.py             # st.navigation/st.Page — 로그인 여부에 따라 노출 페이지 분기
│   │   ├── styles.py                 # 상태별 색상 커스텀 CSS 삽입
│   │   └── components.py             # status_badge(), motor_card() 등 (최소 스텁)
│   └── pages/
│       ├── login.py                  # 로그인 폼 → auth.session.login() → 성공 시 dashboard로 전환
│       ├── dashboard.py              # 레이아웃 뼈대 + "구현 예정" placeholder
│       └── motor_detail.py           # 레이아웃 뼈대 + placeholder
├── data/
│   ├── app.db                        # 시드 스크립트 산출물 — git에 커밋 (gitignore 대상 아님)
│   ├── chroma/                       # Chroma persist 디렉터리 — git에 커밋 (gitignore 대상 아님)
│   └── rag_sources/                  # 시드용 원본 텍스트 placeholder 1~2개
└── scripts/
    └── seed_data.py                  # 1회성 로컬 시딩 스크립트 (아래 순서)
```

`st.navigation`/`st.Page`을 쓰는 이유: 로그인 전엔 대시보드/상세 페이지가 노출되면 안 되는데(`05_ui_screens.md` §1), 이 방식은 `session_state.authenticated` 값에 따라 페이지 목록 자체를 동적으로 구성할 수 있어 요구사항에 정확히 맞음.

### `pyproject.toml` 의존성 (버전 핀 없이 패키지명만)

```
streamlit, plotly, jinja2, weasyprint, langchain, langchain-openai, langgraph,
chromadb, pysqlite3-binary, openai, python-dotenv, bcrypt, apscheduler, pandas
```
선택 그룹: `streamlit-extras`, `streamlit-lottie` (01_tech_stack.md — "선택 적용")

`requires-python = ">=3.14"` (CLAUDE.md 요구사항). ⚠️ Streamlit Community Cloud가 실제 배포 시점에 3.14를 지원하는지는 배포 시 별도 확인 필요 — 미지원이면 `runtime.txt`로 조정.

### `packages.txt`
```
libpango-1.0-0
libpangocairo-1.0-0
libcairo2
libgdk-pixbuf2.0-0
libffi-dev
shared-mime-info
fonts-noto-cjk
```
`fonts-noto-cjk`는 리포트가 전부 한글이라 필수 — 기본 컨테이너 이미지엔 한글 글리프 폰트가 없어 PDF 한글이 깨짐.

### `app/config.py` — 중앙화 설정값 (CLAUDE.md 필수 요구사항)

문서 확정값: `DB_RETENTION_HOURS=48`, `SHORT_TERM_BUFFER_HOURS=2`, `LONG_TERM_TREND_HOURS=6`, `COOLDOWN_HOURS=1`, `MISSED_CYCLES_THRESHOLD=3`, `STATUS_COLORS`(NORMAL `#16a34a`/WARNING `#d97706`/DANGER `#dc2626`/FAULT `#1e293b`), `STATUS_BG_COLORS`, `LLM_ROUTER_MODEL="gpt-4o-mini"`, `LLM_REASONING_MODEL="gpt-4o"`, `NOTIFICATION_CHANNELS`, `REPORT_SESSION_ID_FORMAT`, `ALLOWED_COLLECTION_INTERVALS_SECONDS=(10,20,30)`, `REPORT_TEMPLATE_FILENAME`.

문서 미명시 MVP 제안값(주석으로 "제안값" 명시): `DASHBOARD_REFRESH_INTERVAL_SECONDS=10`, `RETENTION_BATCH_CRON_HOUR=3`, `EMBEDDING_MODEL="text-embedding-3-small"`.

값 조회 우선순위: `st.secrets` → `os.getenv`(로컬은 `python-dotenv`로 `.env` 로드) — Streamlit Community Cloud는 `.env`를 읽지 않고 대시보드 Secrets UI(TOML)를 쓰므로.

### `.gitignore` 추가 (기존 항목 유지)
```
.streamlit/secrets.toml
*.db-wal
*.db-shm
```
⚠️ **주의**: `data/app.db`, `data/chroma/`는 절대 gitignore하지 않음 — 이 프로젝트의 영속성 전략상 의도적으로 커밋해야 하는 파일들.

## 3단계 — 시드 스크립트 (`scripts/seed_data.py`)

1. 기존 `data/app.db` 삭제 후 `ensure_schema()`로 재생성 (idempotent 재실행).
2. `companies`(데모 1~2개), `company_contacts`(bcrypt 해시, 데모 계정 콘솔 출력) 시드.
3. `motors`(회사당 3~5개, 10/20/30초 랜덤 배정), `motor_thresholds`(지표별 4단계 구간) 시드.
4. `motor_telemetry` 합성 데이터 생성 — 최소 1개 모터는 WARNING→DANGER/FAULT 전이가 보이도록 이상치 구간 포함, 임계값 기반 `*_status` 계산.
5. 상태 전이 지점을 스캔해 `motor_status_logs` 이벤트 생성 (`trigger_reason`에 "급변(단계 스킵)" 등 03 §4.2 규칙 반영).
6. `data/rag_sources/*.txt`를 임베딩 후 `data/chroma/`에 인제스트.
7. DANGER/FAULT 로그별로: 데모 진단 텍스트 생성 → RAG 검색으로 SOP 텍스트 조회 → `render_report_pdf()`로 메모리에서 PDF 생성 → `report_pdf` BLOB에 저장.
8. `notification_logs`, `login_logs` 데모 행 삽입.
9. 완료 후 건수 요약 출력 + "`git add data/app.db data/chroma/`" 안내 메시지.

## 검증 방법

1. `uv sync` → `uv run streamlit run main.py` 실행 시 에러 없이 로그인 화면이 뜨는지 확인.
2. `main.py` 최초 실행 시 `data/app.db`(없다면)에 스키마가 실제로 생성되는지 확인 (`sqlite3 data/app.db ".tables"`).
3. `OPENAI_API_KEY`를 `.env`에 설정한 뒤 `uv run python scripts/seed_data.py` 실행 → 콘솔 요약과 함께 `data/app.db`, `data/chroma/`가 생성되는지 확인.
4. 시드된 데모 계정으로 로그인 화면에서 로그인 시도 → 성공적으로 dashboard placeholder 페이지로 전환되는지 확인.
5. `uv export --format requirements-txt > requirements.txt` 실행 결과가 정상 생성되는지 확인 (Streamlit Cloud 배포용).
