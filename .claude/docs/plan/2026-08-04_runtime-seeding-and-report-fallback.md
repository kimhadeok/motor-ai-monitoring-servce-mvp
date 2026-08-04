# 런타임 시드 전환 + 리포트 HTML 폴백

## Context

스캐폴딩(motor-005~007) 완료 후 점검에서, 커밋된 시연 데이터의 `report_pdf`가 **16건 전부 NULL**임을 확인했다. 원인은 개발 PC(Windows)에 WeasyPrint가 요구하는 네이티브 라이브러리(Pango/GLib)가 없어 시드 중 PDF 생성이 전량 실패한 것.

이 문제를 파고들면서 현행 "로컬에서 시드 → 산출물을 git에 커밋" 전략 자체에 문제가 더 있다는 것이 드러났다:

1. **ChromaDB 기본 임베딩이 로컬 모델을 쓴다.** `collection.add(documents=...)`로 텍스트를 넘기면 ChromaDB가 내장 `all-MiniLM-L6-v2`(ONNX)를 쓰는데, 이 모델은 패키지에 포함돼 있지 않고 **첫 사용 시 83MB를 내려받는다**(캐시 총 167MB). Community Cloud는 재시작마다 파일시스템이 초기화되므로 깨어날 때마다 이 비용을 낸다. **벡터를 미리 커밋해도 못 피한다** — 검색 시 질의문을 임베딩해야 하므로 같은 모델이 필요하기 때문.
2. **커밋된 벡터가 `config.EMBEDDING_MODEL` 선언과 불일치.** 실제 dimension은 384(MiniLM)이고 선언은 `text-embedding-3-small`(1536)이다.
3. **시드 데이터가 시간이 지나면 비어간다.** telemetry가 시드 실행 시점 기준 최근 6시간만 생성되는데, 2h 버퍼·6h 트렌드·48h 보관 윈도우는 "지금" 기준 상대 시간이다. 커밋 며칠 뒤 배포하면 최근 구간이 전부 빈다.

### 실측 근거

| 항목 | 측정값 |
|---|---|
| OpenAI 임베딩 — 연결 수립 | 0.59s (cold start 1회) |
| OpenAI 임베딩 — 11청크 배치 | 평균 0.60s (1,140 토큰) |
| OpenAI 임베딩 — 검색 질의 1건 | 평균 0.23s |
| MiniLM — cold start | 83MB 다운로드 + 압축 해제 → 20~60s |
| MiniLM — warm 검색 | 0.12s (로컬 CPU 기준) |
| HTML 렌더 1건 | **0.0ms** (16건 총 1ms), 26KB |
| PDF 렌더 1건 | ~0.5s (16건 총 ~8s) |

임베딩을 OpenAI로 옮기면 cold start가 **20~60초 → 약 1.2초**로 줄고, 메모리 수백 MB와 디스크 167MB가 해방된다. 검색은 0.1초 느려지지만 RAG는 DANGER/FAULT 발생 시 SOP 조회에만 쓰여 체감되지 않는다. 비용은 인제스트 1회 $0.00002 수준.

### 목표

시드 산출물을 커밋하는 대신 **앱 부팅 시 배포 환경에서 생성**하고, PDF는 필요 시점에 만들되 **어느 환경에서도 반드시 보여줄 것이 있도록 HTML을 함께 보관**한다. 결과적으로 Windows 개발 환경과 Streamlit 배포 환경을 모두 만족시킨다.

---

## 기존 확정 사항 중 변경되는 것

이 계획은 이전 계획서(`2026-08-04_project-scaffolding.md`)의 결정 일부를 뒤집는다. **승인 전 이 절을 먼저 확인할 것.**

| 항목 | 기존 | 변경 |
|---|---|---|
| 시드 전략 | 로컬 1회 실행 → `data/app.db`·`data/chroma/` git 커밋 | **앱 부팅 시 런타임 생성**. `data/`를 git에서 제거하고 gitignore |
| 임베딩 | ChromaDB 기본 MiniLM (384차원) | **OpenAI `text-embedding-3-small`** (1536차원) — `config.EMBEDDING_MODEL` 선언대로 |
| 리포트 저장 | `report_pdf BLOB` 단독 | `report_pdf BLOB` + **`report_html TEXT`** 병행 |
| 리포트 버튼 노출 조건 | `report_pdf IS NOT NULL` | **DANGER/FAULT 로그면 노출** (PDF는 클릭 시 생성) |

`.gitignore`에 이미 있는 `.ingest_done` / `.ingest.lock` 항목은 이 런타임 부트스트랩에서 실제로 사용하게 된다.

---

## 1단계 — 확정 문서 정합성 반영

`.claude/docs/generated/`는 구현의 단일 소스 오브 트루스이므로, 아래 결정이 코드보다 먼저 문서에 반영되어야 한다. **6개 문서 전부가 대상이다.**

### 1-1. `01_tech_stack.md` — 임베딩 모델 신규 확정 + 배포 환경 신설

현재 §2.3은 `ChromaDB | Vector DB — RAG 지식베이스 검색`만 기술하고 **임베딩 모델이 어디에도 명시돼 있지 않다.** §2.4에 LLM(GPT-4o-mini / GPT-4o)은 확정돼 있는데 임베딩만 공백이며, `app/config.py`의 `EMBEDDING_MODEL`이 "문서 미확정 — MVP 제안값" 주석을 달고 있던 이유가 이것이다.

- **§2.4 LLM 모델 표에 임베딩 행 추가** — `임베딩 (RAG 인제스트/검색) | text-embedding-3-small`. 선정 근거(로컬 ONNX 모델 83MB 다운로드 회피, 메모리·cold start 절감, OpenAI 단일 프로바이더 유지)를 비고에 기재.
- **§2.3에 ChromaDB 임베딩 방식 명시** — 기본 내장 임베딩 함수(all-MiniLM-L6-v2, 384차원)를 쓰지 않고 OpenAI 임베딩 함수(1536차원)를 주입한다는 점.
- **배포 환경 절 신설** — Streamlit Community Cloud, `uv`(pyproject + uv.lock, 배포용 requirements.txt export), `packages.txt`(WeasyPrint 네이티브 의존). 현재 이 내용이 확정 문서에 전혀 없고 plan 문서에만 존재한다.

### 1-2. `02_architecture.md` — 데모 데이터 부트스트랩 절 신설 + 리포트 생성 시점 정정

- **부트스트랩 절 신설** — Community Cloud는 재배포/재시작 시 파일시스템이 초기화되므로, 데모 데이터(SQLite·Chroma·리포트 HTML)를 **앱 부팅 시 런타임 생성**한다. 산출물은 git에 커밋하지 않는다. 현재 이 전략은 확정 문서 어디에도 없고 plan 문서에만 있으므로 **정정이 아니라 신설**이다.
- **§2.3 상태 전이 표 정정** — `FAULT` 행의 "AI 에이전트 즉시 가동 → 리포트 생성 → 알림 발송"에서 리포트 생성이 무엇을 뜻하는지 새 흐름에 맞춘다(진단 시 HTML 생성·저장, PDF는 요청 시 생성 후 캐시).
- §2.2 RAG 지식베이스 서술에 **RAG 조회 실패 시 키워드 매칭 폴백**을 명시 (CLAUDE.md fallback 요구사항).

### 1-3. `03_state_event_logic.md` §4.1 — 도착 상태별 처리 표 정정

현재 표가 새 흐름과 어긋난다:

| 행 | 현재 서술 | 정정 방향 |
|---|---|---|
| DANGER | "… 결합 진단 → **PDF 리포트 생성** → 담당자 알림 발송" | 진단 결과로 **리포트 HTML을 생성·저장**하고, PDF는 사용자가 리포트를 요청할 때 생성해 캐시 |
| FAULT | "… 에이전트 가동 → **리포트 생성** → SMS/이메일 알림" | 동일하게 정정 |

WARNING / NORMAL 행은 변경 없음.

### 1-4. `04_database_schema.md` §3.5 — `report_html` 컬럼 추가

`motor_status_logs`에 `report_html TEXT` 추가. 용도(PDF 생성 불가 환경 폴백 및 로컬 확인용)와 **BLOB이 아닌 TEXT를 쓰는 이유**(HTML은 UTF-8 텍스트이며 `render_report_html()`이 `str`을 반환 → encode/decode 불필요, sqlite3 CLI로 직접 확인 가능)를 주석으로 기재. §2 관계 요약에 `report_pdf`가 언급된 곳이 있으면 함께 갱신.

### 1-5. `05_ui_screens.md` §3.3, §4.4 — 버튼 노출 조건 및 동작 변경

- **노출 조건**: `report_pdf`(BLOB)가 NULL이 아닌 로그 → **`new_status`가 DANGER/FAULT인 로그**. (지연 생성으로 바뀌어 최초에는 `report_pdf`가 항상 NULL이므로 기존 조건은 성립하지 않는다.)
- **동작**: "다운로드" 단일 동작 → **PDF 생성 성공 시 다운로드 / 실패 시 저장된 HTML 표시** 두 갈래.
- §4.4(line 77)는 현재 리포트 버튼을 컬럼으로만 나열하고 §3.3에 있는 상세 규칙이 없다. 이번에 동일 규칙을 함께 기재한다.

### 1-6. `06_report_spec.md` — 파이프라인 및 SOP 출처 갱신

- **§1 파이프라인**: 진단 → Jinja2 렌더 → **HTML을 `report_html`에 저장** → (요청 시) WeasyPrint → `report_pdf` BLOB 캐시 → 알림. 기존 "메모리에서 바로 DB 기록" 서술을 이 흐름으로 교체.
- **§4 SOP 절(line 58, 77)**: "RAG 대응 매뉴얼 조회 툴 출력(ChromaDB 검색 결과)" 서술에 **RAG 이용 불가 시 키워드 매칭 폴백** 경로를 덧붙인다.

### 대상 아님

- `.claude/docs/user/` — 원본 초안이며 CLAUDE.md·README상 개발 시 참고 대상이 아니므로 수정하지 않는다.
- `03_state_event_logic.md` §5 쿨다운 규칙 — 문서는 이미 올바르며, **코드(시더)가 이를 따르지 않고 있던 것**이다. 3단계에서 코드를 문서에 맞춘다.

## 2단계 — 스키마 및 설정 중앙화

### `app/db/schema.sql`

```sql
report_pdf   BLOB,   -- AI 에이전트 생성 PDF 바이너리 (요청 시 생성 후 캐시)
report_html  TEXT,   -- 렌더된 HTML 원문 (PDF 불가 환경 폴백, 부팅 시 전건 생성)
```

DB가 런타임에 새로 생성되므로 `ALTER TABLE` 마이그레이션은 불필요하다.

### `app/config.py` 로 이관 (CLAUDE.md 중앙화 규약)

현재 `scripts/seed_data.py`에 하드코딩된 값들을 옮긴다:

- `THRESHOLDS` — 지표별 4구간 임계값 (`seed_data.py:40-45`). 런타임 분류기도 같은 값을 쓰게 된다
- `METRIC_LABELS` / `METRIC_UNITS` — 대시보드·상세·리포트가 공유하는 한글 라벨/단위 (`:36-37`)
- `CHROMA_COLLECTION_NAME = "manuals_and_incidents"` — 현재 두 함수 세 곳에 리터럴 반복
- `DEMO_ACCOUNT_PASSWORD` — 데모 계정 공통 비밀번호 (`:98`)
- `SEED_RNG_SEED = 20260804` — 재현성 유지용
- `BOOTSTRAP_MARKER_FILENAME = ".ingest_done"`, `BOOTSTRAP_LOCK_FILENAME = ".ingest.lock"`

기존 `DISPLAY_TIMEZONE`을 실제로 사용하도록 `zoneinfo` 기반 변환 헬퍼를 두고, `seed_data.py:68`의 `timedelta(hours=9)` 하드코딩을 대체한다. 심각도 비교도 `STATUS_LEVELS.index(...)` 대신 기존 `STATUS_SEVERITY_RANK`를 쓴다.

## 3단계 — 로직을 `app/` 으로 이관 + 시드 데이터 품질 개선

현재 `scripts/seed_data.py`(515줄)에만 있는 로직을 런타임에서 호출할 수 있도록 옮긴다. 지금 비어 있는 `app/services/`에 들어갈 첫 코드다.

| 새 위치 | 이관 대상 |
|---|---|
| `app/services/seeding.py` | `seed_companies`, `seed_contacts`, `seed_motors`, `generate_telemetry`, `scan_transitions_and_log`, `seed_login_logs`, `classify`, `baseline_value` |
| `app/services/diagnosis.py` | `build_diagnosis_text`, `build_notification_message` — 이후 LangGraph 진단 에이전트로 대체될 자리 |
| `app/rag/ingest.py` | `ingest_rag_sources`, `query_sop_steps` |
| `app/reports/service.py` | context 조립(`generate_reports_and_notifications`의 context 부분), `ensure_report_html()`, `get_report()` |
| `scripts/seed_data.py` | **얇은 CLI 진입점만 유지** — 로컬에서 수동으로 데이터를 다시 만들고 싶을 때 쓰는 용도 |

### 데이터 품질 수정 (점검에서 확인된 문제)

1. **이벤트 편중** — 현재 상태 로그 87건이 **전부 MTR-001**이다. `generate_telemetry`가 `idx == 0`만 시나리오 모터로 잡고, `baseline_value()`가 `uniform(normal, warning*0.7)`을 반환해 나머지 5대는 구조적으로 WARNING에 도달할 수 없다. COMP-002(demo2) 계정은 이벤트가 하나도 없는 빈 대시보드를 본다.
   → **회사별로 최소 1대씩** 이상 시나리오를 배정한다.
2. **FAULT 부재** — 램프 상한이 82°C인데 fault 임계는 90°C라 FAULT가 한 건도 없다. FAULT 배지·색상·수동 정비완료 경로(03 §3)가 전혀 시연되지 않는다.
   → 최소 1대는 FAULT까지 도달시킨다.
3. **상태 플래핑** — MTR-001 단독으로 WARNING 44 / NORMAL 27 / DANGER 16 = 87건. 노이즈가 임계선을 반복 교차할 때마다 로그가 쌓인다. `config.COOLDOWN_HOURS=1`과 02 §"핑퐁 방지 / 1 전이 = 1 이벤트" 규칙이 시더에 전혀 반영돼 있지 않아 **시드 데이터가 확정 문서의 이벤트 규칙과 모순**된다.
   → `scan_transitions_and_log`에 쿨다운/히스테리시스를 적용한다.
4. **생성 구간** — 6시간 → **48시간**(`DB_RETENTION_HOURS`). 런타임 생성이므로 항상 "지금 기준 최근 48시간"이 되어 노후화 문제가 자동 해소된다.
5. 진행 번호 중복 출력(`[2/9]`, `[8/9]` 각 2회), `build_diagnosis_text()`의 미사용 `motor` 인자, `status_col` 항등 매핑 정리.

### 임베딩 전환

`app/rag/chroma_client.py`에 `embedding_function`을 배선한다 — `chromadb.utils.embedding_functions.OpenAIEmbeddingFunction`에 `config.OPENAI_API_KEY`와 `config.EMBEDDING_MODEL`을 전달. `ingest_rag_sources`와 `query_sop_steps` 양쪽이 동일한 함수를 쓰도록 컬렉션 생성 지점을 한 곳으로 모은다(현재 세 곳에서 각자 `get_or_create_collection`을 호출).

`OPENAI_API_KEY`가 없거나 API 호출이 실패하면 **RAG 없이 기동**하고 SOP 조회는 키워드 매칭으로 폴백한다 (CLAUDE.md fallback 요구사항).

## 4단계 — 런타임 부트스트랩

`app/services/bootstrap.py`에 `ensure_demo_data()`를 만들고 `main.py`에서 호출한다.

```
ensure_schema()
  → 데이터가 이미 있으면 skip (재실행 안전)
  → 데모 데이터 시드                      ~2s
  → RAG 인제스트 (OpenAI 임베딩)          ~1.2s
  → DANGER/FAULT 로그 전건 HTML 생성      ~1ms
```

- `@st.cache_resource`로 프로세스당 1회 실행을 보장한다.
- 파일 락(`.ingest.lock`) + 완료 마커(`.ingest_done`)로 동시 진입을 막는다. `reset_database()`가 `DB_PATH.unlink()`를 하므로, 한 세션이 DB를 지우는 동안 다른 세션이 읽는 상황을 반드시 차단해야 한다.
- 부팅 총 소요 목표: **~3초**.

`main.py`의 기존 `ensure_schema()` 직접 호출은 이 함수로 흡수한다 (현재는 매 rerun마다 `schema.sql`을 다시 읽고 커넥션을 연다).

## 5단계 — 리포트 제공 UI

`app/reports/service.py`:

```
get_report(log_id) -> ("pdf", bytes) | ("html", str)
    PDF 생성 시도
      성공 → report_pdf BLOB에 캐시 후 반환 (두 번째 호출부터 즉시)
      실패 → 저장된 report_html 반환
```

`app/ui/components.py`에 `report_button(log)`를 추가하고 대시보드 이벤트 리스트(05 §3.3)와 상세 이벤트 리스트(05 §4.4)에서 사용한다.

- PDF → `st.download_button`
- HTML → `st.components.v1.html()` 인앱 표시 (또는 `.html` 다운로드)

동작 결과:

| 환경 | 결과 |
|---|---|
| Streamlit Community Cloud | 클릭 → PDF 생성 성공 → 다운로드 (~0.5s), 이후 캐시로 즉시 |
| Windows 로컬 | 클릭 → WeasyPrint 실패 → HTML 즉시 표시 |

## 6단계 — 정리

1. **`data/`를 git에서 제거** — `git rm --cached data/app.db data/chroma/`, `.gitignore`에 `data/app.db`, `data/chroma/` 추가. 기존의 "절대 gitignore하지 말 것" 주석을 런타임 생성 방식으로 바뀌었다는 설명으로 교체. `data/rag_sources/`는 인제스트 원본이므로 **커밋 유지**.
   - 부수 효과: 점검에서 발견된 **고아 Chroma 세그먼트**(`771a1ca7-…`, `chroma.sqlite3`에 미등록인데 164KB가 커밋돼 있음)도 함께 사라진다.
2. `.env.example`에서 실제로 읽지 않는 `DB_PATH` / `CHROMA_PERSIST_DIR` / `APP_ENV` / `LOG_LEVEL` 안내를 정리하거나 `config.py`에 배선한다.
3. `README.md` 갱신 — 시드 절차가 "배포 전 로컬 1회 실행 + 커밋"에서 "앱 부팅 시 자동 생성"으로 바뀐 점, Windows에서 리포트가 HTML로 표시되는 점, `scripts/seed_data.py`는 선택적 수동 재생성 도구라는 점.

### `packages.txt` 관련 (선택, 배포 검증 후)

WeasyPrint는 53버전(2021)에서 Cairo·GDK-PixBuf 의존을 제거했으므로 현재 69버전에는 `libcairo2`, `libgdk-pixbuf2.0-0`이 불필요할 가능성이 높다. 다만 **배포가 깨지는 것보다 apt 패키지 몇 개가 남는 편이 안전**하므로, 실제 Community Cloud 배포로 PDF 생성이 확인된 뒤에 정리한다.

---

## 검증 방법

**로컬 (Windows)**

1. `uv run streamlit run main.py` → 콘솔에 부팅 시드 로그가 뜨고 **3초 내외**에 로그인 화면 표시.
2. `data/app.db`, `data/chroma/`가 새로 생성되는지 확인.
3. `demo1@example.com` / `demo2@example.com` (`demo1234!`) **양쪽 모두** 로그인 → 각자 이벤트가 보이는 대시보드 확인 (편중 문제 해소 확인).
4. 이벤트 리스트에서 [보고서] 클릭 → **HTML이 표시**되고 앱이 죽지 않는지 확인.
5. 쿼리로 데이터 품질 확인:
   ```sql
   SELECT motor_id, new_status, COUNT(*) FROM motor_status_logs GROUP BY 1,2;   -- 두 회사에 분포, FAULT 존재, 전이 수가 쿨다운 반영 수준으로 감소
   SELECT MIN(time), MAX(time) FROM motor_telemetry;                            -- 48시간 구간
   SELECT COUNT(*) FROM motor_status_logs WHERE report_html IS NOT NULL;        -- DANGER/FAULT 건수와 일치
   ```
6. Chroma 차원 확인: `SELECT dimension FROM collections;` → **1536**.
7. `OPENAI_API_KEY`를 비우고 재기동 → 앱이 죽지 않고 RAG 없이 기동되는지 확인 (폴백 검증).

**배포 (Streamlit Community Cloud)**

8. 배포 후 첫 접속까지의 시간 측정 — 목표 3초 내외.
9. [보고서] 클릭 → **PDF가 다운로드**되고 한글이 깨지지 않는지(두부 문자 없음) 확인.
10. 같은 버튼 재클릭 → BLOB 캐시로 즉시 응답하는지 확인.
11. 앱을 sleep 시킨 뒤 다시 깨워서 부팅 시간이 유지되는지 확인 (MiniLM 다운로드가 사라졌는지 검증).

---

## 이번 범위 밖

- **Python 3.14 배포 리스크** — `requires-python = ">=3.14"`이고 `uv.lock`·`requirements.txt`가 3.14 기준으로 전량 핀돼 있다. Community Cloud가 3.14를 미지원이면 `runtime.txt`로 낮춰야 하는데, 그 경우 현재 핀 목록이 3.13에서 그대로 resolve된다는 보장이 없다. **PDF보다 먼저 막힐 수 있는 지점**이므로 배포 착수 전 별도 확인이 필요하다.
- 대시보드·상세 페이지 실데이터 렌더링 (현재 `"구현 예정"` placeholder)
- LangGraph 진단 에이전트 — 3단계에서 만드는 `app/services/diagnosis.py`가 그 자리를 잡아둔다
- 런타임 상태 전이 감지, 연결 두절 판정, 48시간 보관 배치, 알림 발송
- `motor_card()` → `selected_motor_id` 연결 (현재 상세 페이지가 UI 경로로 도달 불가)
