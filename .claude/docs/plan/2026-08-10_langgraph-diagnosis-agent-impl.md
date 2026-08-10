# 계획 — LangGraph 진단 에이전트 구현 (remaining_work #1)

> **상태: 구현 완료 (2026-08-10).** 계획 대비 실제 결과는 문서 끝 "실행 결과"를 본다.

## Context (왜)

리포트 섹션 2 "AI 진단"의 문장은 현재 `app/services/diagnosis.py`의 **규칙 기반 템플릿**
(`build_diagnosis_text`)이 만든다. 리포트에는 "진단 모델: GPT-4o 기반 진단 에이전트"라고
적혀 있지만 실제로 LLM은 한 번도 호출되지 않는다 — 시연에서 "AI 진단"을 보여줄 수 없다.

`.claude/docs/plan/2026-08-06_langgraph-diagnosis-agent.md`에서 (A) 최소 LangGraph 그래프,
(B) 온디맨드 생성, (C) 섹션 = 요약·원인·연쇄영향·방치결과가 확정됐고, **(B)는 2026-08-07에
선행 완료**(부팅 전건 생성 제거, 8.80초 절감)됐다. 이번 작업은 남은 **(A)와 (C)**다.

목표: 측정된 근거(`build_diagnosis_facts`)를 grounding으로 삼아 LangGraph 에이전트가
구조화 진단을 생성하고, 실패하면 규칙 기반으로 폴백해 **어떤 환경에서도 리포트가 나온다.**

---

## 사전 실측 (이번 세션에서 측정)

| 항목 | 실측값 | 비고 |
|---|---|---|
| `langgraph` + `langchain_openai` import | **3.17초**(콜드) / 1.21초(웜) | 프로세스당 1회 |
| gpt-4o `with_structured_output` 1회 호출 | **3.69초** | 실제 진단 프롬프트 형태로 측정 |
| 기존 SOP RAG 왕복 | 약 0.3초 | 이미 존재 |
| **첫 리포트 열람 총 대기** | **약 5~8초** | 프로세스 최초 1회, 이후 `report_html` 캐시로 즉시 |
| 부팅 경로 LLM 호출 | **0회 유지** | (B) 선행 완료 덕분 |

로컬 `OPENAI_API_KEY` 설정 확인됨(길이 167) — 성공 경로·폴백 경로 모두 로컬 검증 가능.

**시험 호출에서 확인한 문제**: 측정 근거를 프롬프트에 넣어줘도 모델이 수치를 인용하지 않고
"온도가 급격히 상승하여 냉각 문제" 같은 일반론으로 답했다. 이는 `06_report_spec.md §2.3`이
지적한 "측정하지 않은 것을 단언하는 진단" 문제의 재발이므로 프롬프트·검증에서 막는다.

## 확정된 결정 (2026-08-10)

- **폴백 시 모델 라벨 전환**: LLM 성공 → `"GPT-4o 기반 진단 에이전트"`,
  폴백 → `"규칙 기반 진단 (LLM 미사용)"`. 생성하지 않은 모델명을 적으면 담당자에게
  거짓 근거를 주는 것이므로 표기를 실제 경로와 일치시킨다.
- **진단 결과는 DB에 따로 저장하지 않는다**: 기존 `report_html` 캐시만 사용. 스키마 변경 없음.
  (데모 DB는 2시간마다 재생성되므로 향후 진단 화면을 만들 때 컬럼을 추가하면 된다.)

---

## 구현 순서

사용자가 지정한 재개 순서를 따른다. **6단계(`bootstrap.py`)는 이미 완료된 상태**임을 확인했다
— `app/services/bootstrap.py`에 `generate_missing_report_html` 호출이 없다(2026-08-07 제거).
대신 그 자리에서 `scripts/seed_data.py --with-reports`의 비용 변화를 처리한다.

### 1. `app/config.py` — 진단 LLM 설정 추가

`LLM_REASONING_MODEL`(345행) 인접 블록에 추가. 하드코딩 금지(CLAUDE.md 제약):

- `DIAGNOSIS_LLM_ENABLED = True` — 오프라인 시연용 강제 오프 스위치
- `DIAGNOSIS_LLM_TIMEOUT_SECONDS` (실측 3.69초 기준 여유를 둔 값)
- `DIAGNOSIS_LLM_MAX_RETRIES`
- `DIAGNOSIS_LLM_TEMPERATURE = 0` — 같은 이벤트에 같은 진단이 나와야 담당자가 신뢰한다
- `DIAGNOSIS_MODEL_LABEL`(348행, 기존 유지) + `DIAGNOSIS_FALLBACK_MODEL_LABEL` 신규
- `DIAGNOSIS_MAX_CHAINED_EFFECTS` — 연쇄 영향 항목 수 상한(리포트 3페이지 높이 보호)

### 2. `app/agents/schema.py` (신규)

Pydantic 모델. 템플릿과 분리해 향후 진단 화면이 그대로 소비할 수 있게 한다.

- `DiagnosisResult`: `summary`(한 줄 요약) / `cause`(주요 원인) /
  `chained_effects: list[str]`(연쇄 영향) / `if_ignored`(방치 시 예상 결과)
  + `source: Literal["llm", "rule"]` — 리포트 모델 라벨을 이 값으로 고른다
  각 필드에 `Field(description=...)`를 달아 structured output 스키마 자체가 지시가 되게 한다.
- `DiagnosisContext`: 에이전트 입력. `build_diagnosis_facts()`가 이미 모으는 값
  (지표·값·임계값·단기/장기 추세·동반 이상 지표·지표 특성·여유 시간대)에
  모터명/모델/위치/상태/`trigger_reason`/의심 고장 모드를 더한 dict-like 구조체.
  `lookup_fault_modes(metric)` 결과(`app/rag/knowledge.py:62`)를 재사용한다 — 새로 조회하지 않는다.

### 3. `app/prompts.py` — 프롬프트 문자열 (현재 4줄 스텁)

`DIAGNOSIS_SYSTEM_PROMPT` + `DIAGNOSIS_USER_TEMPLATE`. 실측에서 드러난 일반론 답변을 막는
제약을 명시한다:

- 주어진 측정 근거 **외의 사실을 추가하지 않는다**
- 원인·연쇄 영향 서술에 **측정값(수치·단위·시간창)을 반드시 인용**한다
- 측정되지 않은 항목(추세 데이터 부족 등)은 **서술하지 않는다**
- 한국어 존댓말, 담당 정비 인력 대상, 각 필드 1~3문장

### 4. `app/agents/diagnosis_agent.py` (신규) — 최소 LangGraph 그래프

`prepare` → `diagnose` → `finalize` 3노드. 확장 여지(RAG 검색 노드·자기검증 노드)를 남긴다.

- **모듈 top-level에서 langgraph/langchain을 import 하지 않는다.** 3.17초 콜드 import가
  Streamlit 부팅에 붙으면 현재 4.43초 콜드 스타트가 무너진다. `app/reports/generator.py:35`가
  WeasyPrint에 쓰는 것과 같은 **함수 내부 지연 import** 패턴을 따른다.
- 컴파일된 그래프는 모듈 전역에 1회 캐시(`bootstrap.py:154`의 `_cached_bootstrap` 패턴과 동일한
  "프로세스당 1회" 방식). Streamlit 위젯 컨텍스트 밖에서도 호출되므로 `st.cache_resource`는 쓰지 않는다.
- `diagnose`: `ChatOpenAI(model=LLM_REASONING_MODEL, temperature=0, timeout=..., max_retries=...)`
  `.with_structured_output(DiagnosisResult)`
- `finalize`: **검증·폴백 게이트.** 필드 누락, 트리거 지표의 측정값 미인용,
  `chained_effects` 개수 초과를 확인하고 실패 시 규칙 기반 결과로 교체한다.
- 공개 함수 `run_diagnosis(context) -> DiagnosisResult` 하나. 키 부재·예외·타임아웃을
  전부 여기서 잡아 폴백을 반환한다 — 리포트 생성은 절대 예외를 올리지 않는다.

### 5. `app/services/diagnosis.py` — 규칙 기반을 폴백 함수로 정리

`build_diagnosis_facts()`는 그대로 둔다(에이전트의 grounding이다).
`build_diagnosis_text()`의 3단 문자열 생성 로직을 재사용해
`build_rule_based_result(status, facts) -> DiagnosisResult`를 추가한다. 기존 문장 품질
(측정한 것만 서술, `_OUTLOOK_BY_LEAD_TIME` 연동)을 그대로 물려받는다.
`build_diagnosis_text()`는 이 함수 위의 얇은 래퍼로 남겨 하위 호환을 유지한다.

### 6. `app/reports/service.py` — 통합 (단일 지점)

`build_report_context()`의 `"diagnosis_text": build_diagnosis_text(status, facts)`(138행)를
교체한다:

- `facts` → `DiagnosisContext` 조립 → `run_diagnosis()` → `DiagnosisResult`
- 컨텍스트 키를 `diagnosis_summary` / `diagnosis_cause` / `diagnosis_chained_effects` /
  `diagnosis_if_ignored`로 분리
- `diagnosis_model_label`을 `result.source`에 따라 고른다 (확정 결정)
- 이미 조회 중인 `lookup_fault_modes(metric)`(143행) 결과를 에이전트 입력으로 **재사용**해
  중복 조회를 만들지 않는다

### 7. `app/reports/templates/report_template.html` — 4섹션 렌더

468행의 단일 `{{ diagnosis_text }}` 블록을 요약/원인/연쇄 영향/방치 시 결과 4개 소섹션으로
교체한다. `[측정 근거]` 칩 블록(470~493행)과 `severity-row`는 그대로 둔다.
페이지 3의 실측 여유는 451px(`06 §3.1`)이므로 4섹션 확장을 흡수한다 —
`@media print`의 `break-inside: avoid`가 이미 걸려 있어 페이지 밀림은 없다.

### 8. `scripts/seed_data.py` — `--with-reports` 비용 경고

부팅 경로는 이미 안전하지만, 이 수동 플래그는 DANGER/FAULT 로그 전건(현재 24건)에
리포트를 만든다. 진단이 LLM으로 바뀌면 **건당 약 3.7초 × 24건 ≈ 90초**가 된다.
실행 전 대상 건수와 예상 소요를 출력해 사용자가 알고 기다리게 한다(스키마·동작 변경 없음).

### 9. UI 대기 문구

`app/ui/components.py:642`의 `st.spinner("리포트를 준비하는 중입니다…")`를 AI 진단이
도는 것을 알리는 문구로 바꾼다. 5~8초 동안 무엇을 기다리는지 모르는 것이 대기 자체보다 나쁘다.

### 10. 문서 동시 갱신 (코드 변경과 같은 커밋)

- `01_tech_stack.md §2.4` / `02_architecture.md §2.4` — 에이전트 실제 구현 반영
- `06_report_spec.md §2.3` — 구조화 4섹션, 폴백 시 모델 라벨 전환, 실측 지연 기록
- `.claude/docs/plan/2026-08-06_langgraph-diagnosis-agent.md` — 상태를 완료로 갱신
- `.claude/docs/plan/remaining_work.md` — #1 체크·상태 완료, 진행 로그 추가
- `README.md` — 프로젝트 구조에 `app/agents/` 추가, 첫 리포트 열람 지연 안내
- 이 계획서를 `.claude/docs/plan/2026-08-10_langgraph-diagnosis-agent-impl.md`로 저장 (CLAUDE.md)

---

## 검증 (다크 모드로 수행)

템플릿·진단을 바꿔도 **이미 저장된 `report_html`에는 반영되지 않는다**(`06 §3.1`).
검증 전 `UPDATE motor_status_logs SET report_html = NULL, report_pdf = NULL`로 초기화한다.

1. **성공 경로**: 앱 기동 → FAULT 모터 이벤트의 "보고서" 클릭 → 리포트 3페이지에
   요약/원인/연쇄 영향/방치 시 결과 4섹션이 렌더되고, 본문이 **해당 모터의 실제 측정값을
   인용**하는지 확인. 첫 열람 지연을 **실측**해 예측치(5~8초)와 비교.
2. **캐시**: 같은 리포트 재열람이 즉시(1초 미만) 응답하는지 실측.
3. **폴백 경로**: `DIAGNOSIS_LLM_ENABLED=False`로 강제 → 리포트가 정상 생성되고
   모델 라벨이 "규칙 기반 진단 (LLM 미사용)"으로 바뀌는지 확인. 키를 빈 값으로 두고도 동일 확인.
4. **부팅 무영향**: 콜드 스타트 시간을 재서 기존 4.43초 실측치가 유지되는지 확인
   (지연 import가 제대로 걸렸는지의 실질 검증).
5. 다크 모드에서 리포트 다이얼로그 표시 확인.

PDF 실제 출력은 로컬에 WeasyPrint 네이티브 라이브러리가 없어 **검증 불가** — HTML 폴백
경로로 확인하고, PDF는 `remaining_work #5`(배포 검증)에 남긴다.

## 신규/수정 파일

- 신규: `app/agents/schema.py`, `app/agents/diagnosis_agent.py`
- 수정: `app/config.py`, `app/prompts.py`, `app/services/diagnosis.py`,
  `app/reports/service.py`, `app/reports/templates/report_template.html`,
  `app/ui/components.py`, `scripts/seed_data.py`
- 문서: `01`, `02`, `06`, `remaining_work.md`, `2026-08-06_langgraph-diagnosis-agent.md`,
  `README.md`, 신규 계획서 1건
- **변경 없음**: `app/services/bootstrap.py`(이미 (B) 완료), `app/db/schema.sql`(저장 안 함)

---

## 실행 결과 (2026-08-10)

### 실측 (헤드리스 검증)

| 경로 | 실측 | 예측 대비 |
|---|---|---|
| 리포트 최초 생성 (프로세스 첫 회) | **8.53초** | 예측 5~8초 — 상단을 약간 초과 |
| 리포트 생성 (2건째, import 웜) | **4.12초** | 예측대로 |
| 폴백 (`DIAGNOSIS_LLM_ENABLED=false`) | 2.52초 | SOP 벡터 검색만 남음 |
| 폴백 (키 없음) | 0.37초 | SOP도 키워드 폴백, 4단계 유지 |
| 앱 진입 경로 import | 1.33초 | `langgraph`·`langchain_openai` **미로드 확인** |

`langgraph`가 앱 진입 경로 import 후 `sys.modules`에 없고 리포트 생성 후에 나타나는 것을
직접 확인했다 — 지연 import가 실제로 걸렸다는 실질 증거다.

### 진단 품질 (근거 대조)

FAULT 2건에 대해 LLM 출력이 제공한 근거 안에 있는지 대조했다.

- MTR-227(소음 95.12dB): "기계적 느슨함", "베어링 외륜/내륜 결함", "진동 지표로 교차 확인"
  → 전부 `fault_modes.json`의 sound 매핑과 evidence에 존재.
- MTR-233(온도 90.36°C): "냉각팬이나 필터"
  → `과열` 고장모드의 `typical_part`("냉각팬, 필터")와 일치.

수치 인용도 두 건 모두 통과했다(현재값·임계값·추세 시작/끝을 문장 안에 인용).
계획 단계 시험 호출에서 나왔던 일반론("냉각 문제로 보입니다"류 단독 서술)은 재현되지 않았다.

### 계획에서 달라진 점

1. **`build_diagnosis_text()`를 남기지 않고 제거했다.** 계획은 하위 호환용 얇은 래퍼로
   두는 것이었으나, 교체 후 호출처가 하나도 남지 않아 죽은 코드가 된다.
   `build_rule_based_result()` 하나로 정리했다.
2. **`--reset-reports` 플래그를 추가했다.** 템플릿·진단을 바꾼 뒤 저장된 `report_html`을
   비우는 일이 이제 상시 필요한데, README가 안내하던 수동 SQL 한 줄은
   `connection_scope`의 commit 경로를 타지 않아 실제로 반영되지 않는다.
3. **`count_missing_reports()`를 분리했다.** `--with-reports`가 시작 전에 건수와 예상
   소요를 알리려면 생성 전에 세어야 한다.
4. **연쇄 영향 개수 초과는 폴백 사유로 삼지 않고 잘라낸다.** 내용이 정확한 진단을
   개수 때문에 통째로 버리는 것보다 상한까지 싣는 편이 담당자에게 낫다.

### 미검증

- **PDF 실제 출력** — 로컬 Windows에 WeasyPrint 네이티브 라이브러리가 없다. HTML 폴백
  경로로만 확인했다. `remaining_work #5`(배포 검증)에 남는다.
- **배포 환경에서의 진단 지연** — Streamlit Community Cloud의 콜드 import·네트워크
  왕복은 로컬과 다를 수 있다. 위 실측은 전부 로컬 값이다.
