# 계획 — LangGraph 진단 에이전트 (remaining_work #1)

> **상태: 완료 (2026-08-10)**. (B)는 2026-08-07에, (A)·(C)는 2026-08-10에 구현됐다.
> 구현 결과와 실측은 `.claude/docs/plan/2026-08-10_langgraph-diagnosis-agent-impl.md`,
> 스펙 반영은 `01 §2.4` / `02 §2.4.1` / `06 §2.3`을 본다. 이 문서는 **결정 근거 기록**으로 남긴다.
>
> 확정: (A) 최소 LangGraph 그래프 (B) 온디맨드 생성+캐시(부팅 대량생성 제거) (C) 섹션=요약·원인·연쇄영향·방치결과.
>
> 아래 "확인 필요"의 A/B/C는 모두 승인됐고, 2026-08-10에 두 가지가 추가로 확정됐다 —
> **폴백 시 진단 모델 라벨 전환**, **진단 결과 DB 미저장**(스키마 변경 없음).

## Context (왜)
현재 진단 텍스트는 `app/services/diagnosis.py`의 **규칙 기반 템플릿**(`build_diagnosis_text`)이 만든다.
이를 **LangGraph 기반 진단 에이전트**로 대체해 실제 AI 진단을 제공한다. 사용자 확정:
- **구조화 출력** (원인 / 연쇄 영향 / 방치 시 결과 … 섹션 분리)
- **리포트 전용** 통합 (추후 별도 진단 화면이 나올 수 있으므로, 에이전트 출력은 템플릿과 분리된 재사용 가능한 구조체로 둔다)

## ⚠️ 핵심 리스크 (실측) 와 대응
`generate_missing_report_html()`가 **부팅 시 DANGER/FAULT 로그 전건에 리포트를 생성**한다. 현재
DB에 그 로그가 **24건** → 진단이 LLM 호출로 바뀌면 **콜드 부팅에 24회 API 호출**(수 분 지연·비용·행 위험).
→ **대응: 부팅 대량 생성을 제거하고, 리포트 최초 열람 시 1건만 LLM 생성 후 캐시**(`get_report`의 지연 생성
경로가 이미 존재). 최초 열람만 수초 지연(스피너), 이후 캐시 즉시 응답.

## 설계

### 1. 출력 스키마 (템플릿과 분리, 재사용 가능)
`app/agents/schema.py` — Pydantic `DiagnosisResult` (06_report_spec §5 매핑):
- `summary`(한 줄 요약), `cause`(원인), `chained_effects`(연쇄 영향, list[str]), `if_ignored`(방치 시 결과)
- 향후 진단 화면도 이 구조체를 그대로 소비.

### 2. 에이전트 (LangGraph)
`app/agents/diagnosis_agent.py` — 최소 그래프(확장 가능):
- `prepare` → `diagnose`(LLM 구조화 출력) → `finalize`(검증·폴백)
- 모델: `LLM_REASONING_MODEL`(gpt-4o) via `langchain-openai`, structured output(`with_structured_output(DiagnosisResult)`)
- 입력: `DiagnosisContext`(모터명·모델·위치·트리거 지표/값/상태·전 지표 판독·임계값·trigger_reason) — `build_report_context`가 이미 모으는 값 재사용.
- 최소 그래프로 두되, 이후 RAG 검색 노드·자기검증 노드 추가 여지를 남긴다.

### 3. 프롬프트 분리 (CLAUDE.md 제약)
`app/prompts.py` — system/user 프롬프트 문자열을 비즈니스 코드와 분리해 여기 채운다(현재 스텁).

### 4. 폴백 (CLAUDE.md fallback — 앱이 죽지 않게)
- `OPENAI_API_KEY` 없음 / LLM 오류 / 타임아웃 → **규칙 기반**(`diagnosis.py` 로직 재사용)을 `DiagnosisResult`로 매핑해 반환. 데모(키 없음)에서도 리포트가 항상 생성된다.
- 타임아웃·재시도 횟수는 config로.

### 5. 통합 (리포트 전용)
- `app/reports/service.py` `build_report_context`: `diagnosis_text = build_diagnosis_text(...)` 자리를
  에이전트 호출 → `DiagnosisResult` → 템플릿 컨텍스트(원인/연쇄영향/방치결과 필드)로 매핑.
- `report_template.html`: 단일 `{{ diagnosis_text }}` 블록을 **섹션(원인/연쇄 영향/방치 시 결과/요약)** 으로 렌더.
- `bootstrap.py`: `generate_missing_report_html` 부팅 호출 **제거**(지연 생성에 위임). 함수는 수동 재생성용으로 남길 수 있음.

### 6. config
- LLM 타임아웃/재시도, 진단 LLM 사용 on/off 플래그(키 없거나 오프라인 데모 대비), 기존 `DIAGNOSIS_MODEL_LABEL` 유지.

## 수정/신규 파일
- 신규: `app/agents/schema.py`, `app/agents/diagnosis_agent.py`
- 수정: `app/prompts.py`, `app/services/diagnosis.py`(규칙 기반을 폴백 함수로 정리), `app/reports/service.py`, `app/reports/templates/report_template.html`, `app/services/bootstrap.py`, `app/config.py`
- 스펙 동기화: `06_report_spec.md`(구조화 출력·온디맨드 생성), `01/02`(에이전트 구현 반영), `remaining_work.md`(#1 진행/완료)

## 검증
1. 키 있음: FAULT 모터 리포트 열람 → 구조화 진단(원인/연쇄영향/방치결과)이 섹션으로 렌더. 최초 열람 지연(스피너) 실측.
2. 키 없음/실패 강제: 규칙 기반 폴백으로 리포트 정상 생성(크래시 없음).
3. 부팅: 24회 LLM 호출이 사라져 콜드 부팅이 빨라짐(실측).
4. 다크 모드에서 리포트 다이얼로그 확인.

## 확인 필요 (승인 전)
- (A) 에이전트: **최소 LangGraph 그래프**(권장, 스펙 라벨 부합·확장 여지) vs 단순 LangChain 체인.
- (B) 부팅 대량 생성 **제거 → 온디맨드 생성**(권장). 최초 열람 수초 지연 트레이드오프 수용 여부.
- (C) 섹션 구성: **요약 / 원인 / 연쇄 영향 / 방치 시 결과** (06 스펙 기준). 추가/변경 의견.
