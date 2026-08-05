# 런타임 부트스트랩 완료 + 리포트 UI + 저장소 정리 (4~6단계)

## Context

`.claude/docs/plan/2026-08-04_runtime-seeding-and-report-fallback.md`의 4~6단계를 마무리한다. 그 계획서는 "시드 산출물을 git에 커밋"에서 "앱 부팅 시 런타임 생성"으로 전략을 바꾸고, PDF가 불가한 환경에서도 리포트를 보여줄 수 있도록 HTML을 병행 저장하기로 확정했다. 1~3단계(문서 정합성, 스키마·설정, 로직 이관)는 motor-008에서 완료됐다.

### 착수 전 확인한 실제 상태 (계획서 기록과 다름)

| 항목 | 계획서 기록 | 실제 |
|---|---|---|
| 4단계 | 부분 완료 | `bootstrap.py`만 존재. **`main.py:11`은 여전히 `ensure_schema()` 직접 호출**, `ensure_demo_data()` 참조 0건. 완료 마커 `data/.ingest_done` 없음 → 한 번도 완주한 적 없음 |
| 5단계 | 미착수 | **`get_report()`는 이미 완성**(`app/reports/service.py:154` — PDF 캐시 히트 → PDF 시도 → 실패 시 HTML 폴백 → BLOB 캐시 전부 구현). 남은 것은 UI뿐 |
| 6단계 | 미착수 | `data/` 12파일(2.4MB) 추적 중. `.gitignore:34-36`에 "절대 gitignore하지 말 것"이라는 정반대 주석 잔존 |

### 계획서에 없던 발견 2건

1. **RAG 인제스트가 매번 전량 재임베딩한다.** `ingest_rag_sources()`가 무조건 `reset_collection()`을 호출해(`app/rag/ingest.py:41`) 컬렉션을 지우고 다시 만든다. 계획서 79행이 "부팅 3.8초로 목표 초과, RAG 인제스트가 주원인"이라 적고 "컬렉션이 이미 채워져 있으면 인제스트 생략"을 조정안으로 남겨둔 지점의 실제 원인이다.
2. **5단계 리포트 버튼을 붙일 이벤트 리스트가 없다.** 대시보드는 `st.info` placeholder(`dashboard.py:24-25`)만 있고, 상세 페이지는 전용 섹션조차 없다. 계획서 "이번 범위 밖"에 "대시보드·상세 페이지 실데이터 렌더링"이 있어, 계획서 문자 그대로만 하면 버튼이 갈 곳이 없다.

### 사용자 확정 사항 (2026-08-05)

- **5단계 범위**: 대시보드 이벤트 리스트(05 §3.3)까지 실데이터로 구현. 상세 §4.4는 진입 경로(`selected_motor_id` 세팅)가 없어 보류.
- **RAG 인제스트**: 컬렉션이 이미 채워져 있으면 생략. 원본 변경 시 `--force`로 재인제스트.
- **`.env.example`**: `OPENAI_API_KEY` 하나만 남긴다.

### 목표

`uv run streamlit run main.py` 한 줄로 데모 데이터가 만들어지고, 로그인하면 이벤트 리스트가 보이고, [보고서]를 누르면 Windows에서도 리포트를 볼 수 있는 상태. 그리고 저장소가 이 방식과 일치하도록 정리된 상태.

---

## 0단계 — 계획 문서 저장 (CLAUDE.md Planning Workflow)

이 계획을 `.claude/docs/plan/2026-08-05_bootstrap-report-ui-cleanup.md`로 저장한다. 기존 `2026-08-04_runtime-seeding-and-report-fallback.md`의 "진행 현황" 표(50-59행)도 이번에 확인한 실제 상태로 정정한다 — 4단계가 "부분 완료"로 되어 있으나 `main.py` 미연결·완주 흔적 없음이 실제이고, 5단계는 "미착수"이나 `get_report()`가 이미 완성돼 있다.

---

## 4단계 — 런타임 부트스트랩 완료

### 4-1. RAG 인제스트 생략 로직 (`app/rag/ingest.py`)

`ingest_rag_sources(force: bool = False) -> int`로 시그니처를 바꾼다.

```
chunks = _load_chunks()            # 원본 없으면 0 반환 (기존과 동일)
if not force:
    collection = get_collection(create=True)      # 임베딩 API 호출 없음
    if collection is not None and collection.count() == len(chunks):
        return collection.count()                  # 이미 최신 — 생략
collection = reset_collection()                    # 이하 기존 로직
```

- `collection.count()`는 임베딩을 요구하지 않으므로 생략 판정 자체에 API 비용이 없다.
- 청크 수가 다르면(원본 추가/삭제) 자동으로 재인제스트된다. 청크 수는 같고 내용만 바뀐 경우는 감지하지 못하므로 `--force`를 쓴다.
- `get_collection()`/`reset_collection()`은 이미 API 키 부재 시 `None`을 반환하므로 폴백 경로는 그대로 유지된다.

`bootstrap_demo_data()`의 호출부(`bootstrap.py:94`)를 `ingest_rag_sources(force=force)`로 바꿔 CLI의 `--force`가 RAG까지 전파되게 한다.

### 4-2. `st.cache_resource` 적용 위치 수정 (`app/services/bootstrap.py:109-117`)

현재 `_run()`이 `ensure_demo_data()` 호출마다 새로 정의되는 지역 함수라 캐시 키 안정성이 검증되지 않았다. 모듈 레벨 함수를 1회만 래핑하도록 바꾼다.

```python
_cached_bootstrap = None

def ensure_demo_data() -> dict:
    """Streamlit 진입점용 래퍼 — 프로세스당 1회만 실행한다."""
    global _cached_bootstrap
    import streamlit as st          # CLI에서 streamlit 없이 쓰기 위한 지연 import 유지
    if _cached_bootstrap is None:
        _cached_bootstrap = st.cache_resource(
            show_spinner="시연용 데이터를 준비하는 중입니다…"
        )(bootstrap_demo_data)
    return _cached_bootstrap()
```

### 4-3. 부팅 실패 시 앱이 죽지 않게 (`app/services/bootstrap.py`)

현재 `bootstrap_demo_data()`에는 try/except가 없어 시드·리포트 생성 중 예외가 나면 앱 전체가 크래시한다. CLAUDE.md의 "Streamlit 앱이 크래시하는 것을 방지" 요구사항에 어긋난다.

`bootstrap_demo_data()`의 락 획득 이후 본문을 `try/except Exception`으로 감싸고, 실패 시 `summary["error"] = str(exc)`를 담아 정상 반환한다(마커는 생성하지 않아 다음 실행에서 재시도된다). `_FileLock.__exit__`이 이미 예외 경로에서도 락을 지우므로 데드락은 없다.

### 4-4. `main.py` 연결

```python
from app.services.bootstrap import ensure_demo_data   # ensure_schema import 제거

st.set_page_config(...)
summary = ensure_demo_data()
if summary.get("error"):
    st.warning("시연용 데이터 준비 중 문제가 발생했습니다. 일부 화면이 비어 있을 수 있습니다.")
inject_global_styles()
run()
```

`ensure_demo_data()`가 내부에서 `ensure_schema()`를 호출하므로 기존 직접 호출은 제거한다. 부수 효과로 매 rerun마다 `schema.sql`을 다시 읽고 커넥션을 여는 비용이 사라진다.

---

## 5단계 — 리포트 제공 UI

`get_report()`는 이미 완성돼 있으므로 **서비스 계층 신규 작업은 이벤트 조회 함수 하나뿐**이다.

### 5-1. 이벤트 조회 함수 신설 — `app/services/events.py` (신규)

`motor_status_logs`에는 회사·모터명 컬럼이 없어 `motors` JOIN이 필요하다(`schema.sql:61-76`).

```python
def list_company_events(conn, company_id: str, limit: int) -> list[sqlite3.Row]:
    """회사 소속 모터의 상태 전이 이벤트를 최신순으로 조회 (05 §3.3)."""
```

- `SELECT l.log_id, l.motor_id, m.motor_name, l.metric_name, l.previous_status, l.new_status, l.trigger_reason, l.created_at FROM motor_status_logs l JOIN motors m ON m.motor_id = l.motor_id WHERE m.company_id = ? ORDER BY l.created_at DESC LIMIT ?`
- **`report_html` / `report_pdf`는 SELECT하지 않는다** — 행당 26KB 이상이라 목록 조회에 담으면 안 된다. 버튼 노출은 `new_status`만으로 판정한다.
- `limit` 기본값은 `config.DASHBOARD_EVENT_LIST_LIMIT = 10`을 신설해 사용한다 (CLAUDE.md 중앙화 규약. 05 §3.3의 "최대 10개").

### 5-2. `report_button(log)` — `app/ui/components.py`

`app/reports/service.py`의 기존 `REPORTABLE_STATUSES` 상수를 노출 조건에 재사용한다.

```
log["new_status"] not in REPORTABLE_STATUSES → 아무것도 렌더하지 않음
st.button("보고서", key=f"report-{log_id}") 클릭
  → get_report(log_id) 호출 결과를 st.session_state["report_view"]에 저장 후 st.rerun()
```

렌더는 `st.dialog`(streamlit 1.60.0에서 사용 가능 — 확인함)로 띄운다. 리스트 행 안에서 직접 `st.components.v1.html`을 부르면 표 레이아웃이 무너지기 때문이다.

| `get_report()` 반환 | 다이얼로그 내용 |
|---|---|
| `("pdf", bytes)` | `st.download_button` (`mime="application/pdf"`, 파일명은 `config.REPORT_SESSION_ID_FORMAT` 기반) |
| `("html", str)` | `st.components.v1.html(html, height=..., scrolling=True)` + `.html` 다운로드 버튼 |
| `None` | `st.warning("리포트를 생성할 수 없습니다.")` |

- 05 §3.3 확정대로 파일시스템을 경유하지 않는다(전부 메모리).
- PDF 생성은 건당 ~0.5초이므로 버튼 클릭을 `st.spinner`로 감싼다.
- 다이얼로그 높이·HTML 뷰어 높이는 `config`에 상수로 둔다.

### 5-3. 대시보드 이벤트 리스트 — `app/pages/dashboard.py:24-25`

`st.info` placeholder 한 줄을 실제 리스트로 교체한다.

- `st.session_state["company_id"]`(로그인 시 `start_session()`이 세팅, `auth/session.py:59`)로 `list_company_events()` 호출
- 헤더 행 + 데이터 행을 `st.columns([2, 2, 1.5, 1])` — 발생 일시 / 모터명 / 모터 상태 / 리포트 버튼
- 발생 일시: `config.format_display()` 사용 (`created_at`은 ISO8601 UTC 문자열이므로 `service.py:48`의 `_parse_utc()`와 동일한 파싱이 필요 — 이 함수를 `app/services/events.py`나 공용 위치로 옮겨 재사용한다)
- 모터 상태: 기존 `status_badge()` 재사용
- 이벤트가 0건이면 `st.info("최근 이벤트가 없습니다.")`

**이번에 건드리지 않는 것**: 같은 파일의 상단 `st.metric` 4개(§3.1)와 "모터 현황" 카드(§3.2)는 `"구현 예정"` placeholder 그대로 둔다. 사용자가 확정한 범위 밖이다.

### 5-4. 상세 페이지 §4.4 — 보류

`selected_motor_id`를 세팅하는 코드가 저장소 어디에도 없어 `motor_detail.py`는 항상 warning 분기로 간다. 모터 카드 클릭 이동(§3.2)이 선행돼야 하므로 이번 범위에서 제외한다.

---

## 6단계 — 저장소 정리

### 6-1. `data/` 산출물을 git에서 제거

```bash
git rm --cached data/app.db
git rm -r --cached data/chroma
```

`data/rag_sources/` 2개 파일은 인제스트 원본이므로 **커밋 유지**한다 (`git rm -r --cached data/`를 통째로 실행하면 안 된다).

부수 효과로 계획서 229행이 지적한 고아 Chroma 세그먼트(`771a1ca7-…`, 168KB)도 함께 사라진다. 디스크에서도 `data/chroma/`를 삭제한 뒤 재생성시켜 검증한다.

### 6-2. `.gitignore` 34-36행 주석 블록 교체

현재의 "절대 여기에 추가하지 말 것" 주석을 지우고 다음으로 바꾼다.

```gitignore
# 데모 데이터는 앱 부팅 시 런타임 생성한다 (app/services/bootstrap.py).
# 산출물은 커밋하지 않는다 — 인제스트 원본인 data/rag_sources/ 만 커밋 대상.
data/app.db
data/chroma/
```

`.ingest_done` / `.ingest.lock`은 13-15행에 이미 있고 슬래시 없는 패턴이라 `data/` 하위도 커버한다 — 수정 불필요.

### 6-3. `.env.example`

`OPENAI_API_KEY=` 한 줄만 남긴다. `APP_ENV` / `LOG_LEVEL` / `DB_PATH` / `CHROMA_PERSIST_DIR` 네 개는 `config.py`가 전혀 읽지 않는다(실제로 읽는 환경변수는 `OPENAI_API_KEY` 단 하나, `config.py:50`). 정리 후 `.streamlit/secrets.toml.example`과 내용이 정확히 일치하게 된다.

### 6-4. `README.md`

| 위치 | 현재 | 변경 |
|---|---|---|
| L23 제목 | "시연용 데이터 생성 (최초 1회, 로컬에서만 실행)" | "시연용 데이터 (앱 부팅 시 자동 생성)" |
| L25 | "배포 전 로컬에서 시드 스크립트를 1회 실행하고 그 결과물을 git에 커밋" | 부팅 시 `ensure_demo_data()`가 자동 생성. 항상 "지금 기준 최근 48시간" |
| L27-31 | `uv run python scripts/seed_data.py` 필수 절차 | `scripts/seed_data.py --force`를 **선택적 수동 재생성 도구**로 재서술 |
| L33 | 시드 스크립트 문맥의 WeasyPrint 경고 | Windows에서는 [보고서]가 **HTML로 표시**된다는 사용자 관점 설명으로 교체 |
| L35-38 | `git add data/app.db data/chroma/` 블록 | **삭제** |
| L40 | "`.gitignore`에 추가하지 마세요" 경고 | **삭제** |
| L53 | "data/ … (git 커밋 대상)" | "data/ # 런타임 생성 (git 제외). rag_sources/ 만 커밋" |
| L60 | 현재 범위 서술 | 부트스트랩·리포트 UI까지 반영 |

`data/rag_sources/`, `app/services/bootstrap.py`, `.ingest_done`/`.ingest.lock`은 README에 언급이 전혀 없으므로 구조 설명에 추가한다.

### 6-5. `packages.txt` — 이번 범위 밖

계획서 233-235행 결정 유지. 실제 Community Cloud 배포로 PDF 생성이 확인된 뒤에 정리한다.

---

## 문서 동기화

`.claude/docs/generated/`는 구현의 단일 소스 오브 트루스이므로, 코드가 문서와 어긋나면 문서를 갱신한다.

- **`02_architecture.md` §6 부트스트랩 절** — 4-1의 "컬렉션이 이미 채워져 있으면 인제스트 생략" 동작과 4-3의 실패 시 폴백을 반영한다. 확정 문서에 없는 새 동작이므로 반드시 기재한다.
- **`05_ui_screens.md` §3.3** — 이미 확정 서술이 구현과 일치하므로 수정 불필요. 다만 다이얼로그로 표시한다는 점만 보강한다.

---

## 검증

계획서 239-254행의 로컬 검증 항목을 수행한다. 배포 항목(8~11)은 Community Cloud 배포가 선행돼야 하므로 이번 범위 밖이다.

**사전 준비**: 기존 `data/app.db`와 `data/chroma/`를 삭제하고 시작한다. 현재 디스크의 `app.db`는 motor-007 시점의 옛 데이터(6시간 구간)이고 `_has_demo_data()`가 True를 반환해 재시드를 건너뛰기 때문이다.

1. `uv run streamlit run main.py` → 스피너 후 로그인 화면. `summary["timings"]`를 콘솔에 찍어 **실측 부팅 시간을 기록**한다 (목표 ~3초. 계획서 79행의 3.8초 대비 RAG 생략이 얼마나 줄이는지 확인).
2. `data/app.db`, `data/chroma/`, `data/.ingest_done`이 새로 생성되는지 확인.
3. **재기동** → 2회차 부팅에서 시드와 RAG가 모두 생략되고 훨씬 빨라지는지 확인 (4-1 검증).
4. `demo1@example.com` / `demo2@example.com` (`demo1234!`) **양쪽 모두** 로그인 → 각자 이벤트 리스트가 채워져 보이는지 확인.
5. DANGER/FAULT 행에서 [보고서] 클릭 → **다이얼로그에 HTML 리포트가 표시**되고 앱이 죽지 않는지 확인. NORMAL/WARNING 행에는 버튼이 없어야 한다.
6. 데이터 품질 쿼리:
   ```sql
   SELECT motor_id, new_status, COUNT(*) FROM motor_status_logs GROUP BY 1,2;
   SELECT MIN(created_at), MAX(created_at) FROM motor_telemetry;              -- 48시간 구간
   SELECT COUNT(*) FROM motor_status_logs WHERE report_html IS NOT NULL;      -- DANGER/FAULT 건수와 일치
   ```
7. Chroma 차원 확인: `data/chroma/chroma.sqlite3`에 `SELECT dimension FROM collections;` → **1536**.
8. `OPENAI_API_KEY`를 비우고 재기동 → 앱이 죽지 않고 RAG 없이 기동, [보고서]도 정상 동작하는지 확인 (폴백 검증).
9. **동시 진입 테스트**: 별도 스크립트에서 두 프로세스가 동시에 `bootstrap_demo_data()`를 호출하게 하고, 한쪽이 `skipped_concurrent=True`로 빠지며 DB가 깨지지 않는지 확인.
10. `git status` → `data/app.db`, `data/chroma/`가 추적 목록에서 빠지고 `data/rag_sources/`는 남아 있는지 확인.

---

## 이번 범위 밖

- 상세 페이지 §4.4 이벤트 리스트, 모터 카드 클릭 → `selected_motor_id` 연결 (5-4)
- 대시보드 §3.1 상단 요약, §3.2 모터 카드 실데이터
- `packages.txt` 정리 (배포 검증 후)
- **Python 3.14 배포 리스크** — `requires-python = ">=3.14"`이고 `runtime.txt`가 없다. Community Cloud가 3.14를 미지원이면 핀 목록 전체를 3.13에서 다시 resolve해야 한다. PDF보다 먼저 막힐 수 있는 지점이라 배포 착수 전 별도 확인이 필요하다.
- LangGraph 진단 에이전트 (현재 `app/services/diagnosis.py`의 규칙 기반 템플릿이 그 자리를 잡고 있음)
- 런타임 상태 전이 감지, 연결 두절 판정, 48시간 보관 배치, 알림 발송

### 알려진 한계 (기록만)

로컬에서 며칠 뒤 앱을 다시 켜면 `_has_demo_data()`가 True를 반환해 재시드하지 않으므로 데이터가 노후화된다. `scripts/seed_data.py --force`로 갱신한다. 배포 환경은 파일시스템이 초기화되므로 해당하지 않는다.
