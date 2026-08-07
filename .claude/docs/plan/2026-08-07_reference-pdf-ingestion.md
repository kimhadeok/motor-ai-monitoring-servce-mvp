# uploads/Reference PDF 3종 → 지식 계층 분리 + 수동 등록 전환

## Context

`uploads/Reference/`에 PDF 3종(총 117페이지)이 커밋돼 있으나 **코드·설정·문서 어디에서도 참조되지 않는다**. 이를 RAG에 등록한다.

현재 RAG는 `data/rag_sources/*.txt` 2개(11청크)를 Chroma `manuals_and_incidents`에 부팅 시 적재하고, 유일한 소비처는 `query_sop_steps(motor_name, metric)` → 리포트 SOP 목록이다. 질의문은 `f"{motor_name} {label} 이상 대응 정비 절차"`로 **도메인 어휘가 전혀 없어** 유사도 검색이 느슨하다.

### 자료 분석 결과 (전문 읽고 추출 품질 측정 완료)

| 파일 | 성격 | 텍스트 | 판정 |
|---|---|---|---|
| Ford 엔진 진동 AI 데이터셋 (39p) | KAIST 가이드북 — Python ML 튜토리얼 | 23,313자 | **전량 제외** |
| AI 기반 예지보전 개발계획서 (34p) | (주)크레오티 — PdM 도메인 지식 본체 | 33,732자 | 핵심 소스 |
| MotorSense 제품소개서 (44p) | 영업 슬라이드 덱, 이미지 525개 | 10,874자 | 선별 채택 |

**측정 1 — 자동 파싱으로는 그래프성 내용을 복원할 수 없다.** 지표→고장모드 매핑, 징후 시간 체인, 보전 분류 트리는 전부 PDF 안에서 **도형**으로 그려져 있다. pymupdf `sort=True` 실측 결과 계층이 소실된 좌표 순서 나열이 되고, pypdf는 한/영이 뒤섞인다(`엔진 진동 데이터셋Ford AI`). → 사전 큐레이션 `.txt` 커밋 방식 확정.

**측정 2 — 그래프DB는 도입하지 않는다.** 그래프성 내용은 실재하나 고장모드 9 + 지표 매핑 17 = **26행**이고 런타임 테이블(motors/telemetry)과 조인할 지점이 없다. SQLite 테이블조차 과설계라 **커밋된 JSON을 직접 읽는다**.

## 원칙 — "실행 시점"이 아니라 "시간 의존성"으로 가른다

MVP는 한 번 등록하면 끝이어야 하지만, 모든 것을 사전 생성할 수는 없다. [seeding.py:519](app/services/seeding.py:519)가 `datetime.now(timezone.utc)` 기준으로 최근 48시간을 채우므로, 데모 데이터를 커밋하면 배포 며칠 뒤 **빈 대시보드**를 보게 된다.

| 자산 | 시간 의존 | 저장 | 등록 | 부팅 시 |
|---|---|---|---|---|
| 고장모드 지식 | 무관 | `data/knowledge/fault_modes.json` (커밋) | 불필요 — 파일이 곧 데이터 | `lru_cache` 1회 로드 |
| RAG 벡터 | 무관 | `data/chroma/` (**커밋으로 전환**) | `scripts/build_knowledge.py` 수동 1회 | **없음 (제거)** |
| 텔레메트리·상태로그 | **의존** | `data/app.db` (gitignore 유지) | — | 생성 (유지, 3.84초) |
| 리포트 HTML | 의존 | DB TEXT | — | **없음 (온디맨드로 전환)** |

`data/chroma/`를 커밋해야 하는 이유: Community Cloud가 초기화하는 것은 **런타임에 쓴 파일**이고, git에 커밋된 파일은 체크아웃으로 들어온다. 현재 `.gitignore:34-39` 주석은 데모 데이터의 노후화 논리를 정적 벡터에까지 잘못 적용하고 있다.

**결과 — 부팅에서 OpenAI API 호출이 0회가 된다.** 현재 부팅은 인제스트 1회 + 리포트 24건의 SOP 조회 24회를 호출한다. 이 계획 후 남는 것은 스키마(0.07초)와 데모 시드(3.84초)뿐이며 둘 다 네트워크를 타지 않는다. 즉 배포본이 API 키 없이도 정상 기동하고, 키가 있으면 리포트 열람 시점에만 사용된다.

## 구현

### 1. 지식 데이터 — `data/knowledge/fault_modes.json` (작성 완료)

고장모드 9종(`BEARING_DEFECT_OUTER/INNER`, `MISALIGNMENT`, `IMBALANCE`, `LOOSENESS`, `LUBRICATION_SHORTAGE`, `OVERHEATING`, `OVERLOAD`, `STATOR_ROTOR_FAULT`) + 지표 매핑 17건. 각 항목에 `source_doc`(출처 PDF·페이지), `lead_time_band`(MotorSense p4 징후 시간 체인), `evidence`(진단 근거 문장)를 담는다.

`metric_fault_map.relevance`가 MotorSense p3의 지표별 예지보전 적합성을 반영한다 — 진동=주지표(1), 온도·소음=보조(2).

### 2. 지식 로더 — `app/rag/knowledge.py` (신규)

- `load_fault_knowledge()` — `@lru_cache`로 JSON 1회 로드. 파일 부재·파싱 실패 시 빈 구조 반환.
- `lookup_fault_modes(metric, limit)` — 메모리 내 필터 + `relevance` 정렬. DB·네트워크 접근 없음.

두 함수 모두 예외를 삼킨다 (CLAUDE.md fallback — 지식이 없어도 앱이 죽지 않아야 한다).

### 3. 큐레이션 텍스트 — `data/rag_sources/` (4개 신규)

기존 청킹(`ingest.py:29` 빈 줄 문단 분할)을 그대로 쓰도록 **문단 1개 = 개념 1개**로 작성. 첫 줄 `#fault=<CODE>` 마커는 인제스트 시 메타데이터로 승격되고 본문에서 제거된다.

| 파일 | 출처 | 내용 |
|---|---|---|
| `pdm_fault_modes.txt` (작성 완료) | PDF2 §3.2, PDF3 p15 | 고장모드 9종별 정비 절차 — **SOP의 실체** |
| `pdm_signal_analysis.txt` | PDF2 p7-13, p19-20 | FFT·특징추출(RMS/Kurtosis/Crest Factor), BPFO·BPFI 공식과 계산 예시(1800RPM → 108/162Hz), 정규화 3기법 비교 |
| `motorsense_incident_cases.txt` | PDF3 p34-38 | 실제 사례 4건 — 벨트 컨베이어 Looseness, 펌프 Harmonic, 다관절 로봇 서보모터, 배관 Leak |
| `maintenance_taxonomy.txt` | PDF3 p2-p4 | 보전 체계(PM/BM/CM/PdM), 징후 시간 체인, 지표별 예지보전 적합성 |

기존 2개 파일은 유지한다.

### 4. `app/rag/ingest.py` 수정

- `_load_chunks()` 반환을 `(chunk_id, text, metadata)`로. `doc_type`은 config의 파일명 매핑에서, `fault_code`는 `#fault=` 마커에서.
- `ingest_rag_sources()`는 그대로 두되 **부팅 경로에서 호출하지 않는다** (수동 스크립트 전용).
- `query_sop_steps()` — 지식 조회로 질의문을 강화하고 `doc_type`으로 필터:

```python
faults = lookup_fault_modes(metric, limit=RAG_FAULT_LOOKUP_LIMIT)
names = " ".join(f["fault_name_ko"] for f in faults)
query_text = f"{motor_name} {label} 이상 {names} 정비 절차"
result = collection.query(query_texts=[query_text], n_results=RAG_TOP_K,
                          where={"doc_type": {"$in": list(RAG_SOP_DOC_TYPES)}})
```

3단 폴백(RAG → 키워드 → 기본 문구)은 유지한다.

### 5. `app/config.py` — RAG 블록(291~296행)에 추가

```python
KNOWLEDGE_DIR = BASE_DIR / "data" / "knowledge"
FAULT_KNOWLEDGE_FILE = "fault_modes.json"
RAG_SOURCE_DOC_TYPES = {          # 파일명 → doc_type
    "manufacturer_manual_sample.txt": "manual",
    "pdm_fault_modes.txt": "manual",
    "past_incident_sample.txt": "incident",
    "motorsense_incident_cases.txt": "incident",
    "pdm_signal_analysis.txt": "methodology",
    "maintenance_taxonomy.txt": "methodology",
}
RAG_SOP_DOC_TYPES = ("manual", "incident")   # SOP 조회 대상 (methodology 제외)
RAG_FAULT_LOOKUP_LIMIT = 3
```

### 6. 수동 등록 스크립트 — `scripts/build_knowledge.py` (신규)

```
uv run python scripts/build_knowledge.py [--force] [--dry-run]
```

- `--dry-run`: 임베딩 없이 청크 수·doc_type 분포·파일별 내역만 출력 (API 키 불필요)
- 실행 시 `ingest_rag_sources(force=True)` 호출 후 청크 수, 소요 시간, `data/chroma/` 용량 출력
- 등록 후 커밋해야 배포에 반영된다는 안내를 마지막에 출력

### 7. 부팅에서 인제스트 제거 — `app/services/bootstrap.py`

95행 `ingest_rag_sources(force=force)` 호출을 제거하고, 대신 기존 컬렉션의 `count()`만 읽어 `summary["rag_chunks"]`에 담는다(임베딩 비용 없음). 벡터 스토어가 비어 있으면 경고 문구를 summary에 넣어 `scripts/build_knowledge.py` 실행을 안내한다.

`scripts/seed_data.py`의 출력도 이에 맞춘다.

### 8. `.gitignore` — `data/chroma/` 커밋 전환

39행 `data/chroma/`를 제거하고, 34-37행 주석을 "시간 기준 데이터만 런타임 생성, 정적 벡터는 커밋" 으로 정정한다.

### 9. 리포트 HTML 온디맨드 전환

**지연 생성 경로는 이미 구현돼 있다** — `get_report()`([service.py:170-182](app/reports/service.py:170))이 `report_html`이 NULL이면 그 자리에서 만들어 저장한다. UI 어디에도 `report_html IS NOT NULL` 조건이 없다([components.py:556](app/ui/components.py:556) 주석이 이미 리포트 유무를 조건으로 쓸 수 없다고 명시).

따라서 전환은 다음 두 가지다.

- `bootstrap.py:100` `generate_missing_report_html(conn)` 호출과 관련 타이밍·import 제거. 부팅에서 임베딩 왕복 24회(약 7초)가 사라진다.
- `service.py:129` docstring 정정 — "건당 렌더 비용이 1ms 미만이라 전건 생성해도 부담이 없다"는 사실과 다르다. Jinja2 렌더는 1ms 미만이지만 같은 함수의 `query_sop_steps`(117행)가 건당 약 0.3초의 임베딩 왕복을 유발한다.

`generate_missing_report_html()` 자체는 남긴다 — `scripts/seed_data.py`에서 `--with-reports` 옵션으로 호출해 로컬에서 전건을 미리 만들 수 있게 한다.

### 10. 리포트에 의심 고장 모드 반영

`build_report_context()`(49행)에 `"suspected_faults": lookup_fault_modes(metric)`를 추가하고 `report_template.html`에 "의심 고장 모드" 섹션(고장명·근거·부품·출처)을 넣는다. `06_report_spec.md` 갱신이 따라붙는다.

## 검증

1. `uv run python scripts/build_knowledge.py --dry-run` — 청크 수·doc_type 분포 확인 (API 키 없이).
2. `uv run python scripts/build_knowledge.py` — 실제 인제스트. 청크 수, 소요 시간, **`data/chroma/` 용량 실측** 후 커밋 타당성 보고.
3. `uv run python scripts/seed_data.py --force` — 부팅 경로에서 RAG 인제스트와 리포트 전건 생성이 빠졌는지, 단계별 타이밍 확인.
4. **콜드 스타트 재측정** — `02_architecture.md` §6.5 표 갱신. 인제스트 0.44초 + 리포트 약 7초가 빠진 값을 실측한다.
5. **리포트 온디맨드 동작 확인** — 부팅 직후 `report_html`이 전부 NULL인 상태에서 리포트 상세를 열어 정상 생성·표시되는지, 두 번째 열람은 캐시로 즉시 뜨는지.
6. **SOP 품질 전/후 비교** — 4개 지표 각각 `query_sop_steps("HYUN-37KW-4P", metric)` 결과를 변경 전후로 나란히 출력.
7. **폴백 검증** — `OPENAI_API_KEY` 없이 부팅해 앱이 뜨고 키워드 폴백이 동작하는지. 지식 조회는 키 없이도 살아 있어야 한다.
8. `data/knowledge/fault_modes.json`을 지운 채 부팅해 앱이 죽지 않는지.
9. **화면 검증(다크 모드)** — 리포트 상세의 "의심 고장 모드" 섹션.

## 문서 반영

- `.claude/docs/plan/2026-08-07_reference-pdf-ingestion.md` (복사 완료 — 이 내용으로 갱신)
- `01_tech_stack.md` — 지식 3계층 분리, 그래프DB 미도입 근거
- `02_architecture.md` §6.1/§6.3/§6.5 — 부팅 시퀀스에서 RAG 인제스트·리포트 전건 생성 제거, 타이밍 재측정
- `06_report_spec.md` — 의심 고장 모드 섹션, 리포트 HTML 생성 시점 변경(진단 시 → 최초 열람 시)
- `remaining_work.md` — 상태 갱신

## 별건 (보고만)

MotorSense p3은 4개 지표를 동등하게 보지 않는다 — 진동=최초 징후(핵심), 온도=주변 기온 영향으로 보조, 소음=주변 설비 소음 혼입, 전류/전압=예지보전이 아니라 **긴급보전** 영역. 현재 `config.py:METRIC_THRESHOLDS`는 4개를 동급으로 취급한다. `relevance`에 차이를 반영하되 임계값 체계 변경은 별도 결정 사안이다.
