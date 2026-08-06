# 메인 대시보드 재정리 — 모터 그래프 · 모터 현황 2페이지 신설

## Context (왜 이 작업을 하는가)

사용자가 재정리 설계안(`.claude/docs/user/모터 AI - 메인 대시보드 (재정리).pdf`, 2페이지)을 제공했다.
이 PDF는 기존 단일 대시보드를 넘어 **메인 대시보드를 2개의 새 페이지로 확장**하는 설계다.

- **1페이지 [모터 그래프]**: 지표 4열(온도/진동/전류/소음), 각 열에 전체 모터의 지표 그래프를 세로로 나열.
- **2페이지 [모터 현황]**: 라디오 버튼으로 그룹핑 방식(상태별/위치별/확인사항별)을 골라, 그룹 헤더 아래 모터 카드를 가로 10개씩 배치. 카드 클릭 시 상세 페이지로 이동, 상태 색상 등 기존 스타일 유지.

### 확정된 결정 (사용자 Q&A)
1. **기존 대시보드는 그대로 두고 2페이지를 "추가"** 한다. (요약 타일·경고 배너·이벤트 리스트는 기존 `dashboard.py`에 유지)
2. 1페이지 그래프는 **일반 라인차트**.
3. 데이터 규모: **COMP-001 회사에만 모터 200대**로 확장하고 **샘플 텔레메트리/상태 데이터도 생성**. (COMP-002는 현행 10대 유지)

### 기존 확정 사항 대비 바뀌는 점 (먼저 명시)
- 시드가 회사당 10대 고정 → **COMP-001 200대**로 스케일업. `seeding.py`의 하드코딩 `_MOTORS` 리스트를 프로그램 생성으로 보강.
- 메인 페이지가 1개 → **3개(메인 대시보드/모터 그래프/모터 현황) + 상세**. 사이드바를 숨긴 현 구조상 **상단 헤더에 페이지 이동 내비게이션을 추가**해야 함.
- "환경설정에 값 관리"는 별도 설정 UI가 아니라 **`config.py` 중앙화**로 해석(프로젝트 규약: 하드코딩 금지).

---

## ⚠️ 규모에 따른 비용 (정직하게 명시 — 200대는 사용자 명시 요청)

200대는 Streamlit MVP에서 무거운 규모다. 아래는 **추정치**이며, 구현 중 `scripts/screenshot.py`/실행으로 **실측 후 확정**한다.

| 항목 | 위험 | 대응 |
|---|---|---|
| **1P 그래프 렌더** | 200대 × 4지표 = **800개 차트**를 한 번에 그리면 브라우저 프리즈 | **페이지네이션 필수**: 한 화면 N대(config `GRAPH_PAGE_SIZE`, 기본 20대→80차트). prev/next + 범위 표시 |
| **2P 카드 렌더** | 200개 카드 동시 렌더 | 기존 `motor_card`(인라인 SVG·게이지·버튼)는 무거움 → **경량 텍스트 카드**(`status_card`) 신설. PDF 카드도 텍스트형 |
| **조회 비용** | `list_company_motors`는 모터당 서브쿼리 다수 → 200대면 수백 쿼리 | **배치 조회 함수 신설**(모터당 1쿼리 이하). 아래 §3 |
| **시드/부팅 시간** | 현재 20대 ~4.1초. 200대면 텔레메트리 행·전이 계산 급증 | 벌크 190대는 **수집주기 300초**(48h→576행/대≈11만행)로 생성. 라인차트는 어차피 다운샘플하므로 화질 손실 없음 |

---

## 구현 단계

### 0. 이 계획을 저장소에 복제
`.claude/docs/plan/2026-08-06_main-dashboard-graph-status-pages.md`로 이 계획을 복사(CLAUDE.md Planning Workflow 규약). *(플랜 모드에서는 못 만들므로 구현 첫 스텝으로 수행)*

### 1. `app/config.py` — 중앙 설정 추가
- 그룹핑: `GROUPING_MODES`(키·라벨: 상태별/위치별/확인사항별), `DEFAULT_GROUPING_MODE`(기본 "status")
- 그룹 정렬: `STATUS_GROUP_ORDER=["FAULT","DANGER","WARNING","NORMAL"]`, `ISSUE_GROUP_ORDER=["FAULT","DANGER","WARNING"]`(NORMAL 제외)
- 레이아웃: `STATUS_CARDS_PER_ROW=10`, `GRAPH_PAGE_SIZE=20`, `GRAPH_TREND_HOURS`, `GRAPH_TREND_BUCKETS`
- 시드 벌크 파라미터: `SEED_BULK_MOTOR_COMPANY="COMP-001"`, `SEED_BULK_MOTOR_COUNT=200`(기존 큐레이션 10대 포함 총량), `SEED_BULK_INTERVAL_SECONDS=300`, 위치 풀(`SEED_LOCATION_POOL`, 8~12개), 모델 풀, 목표 상태 분포(예: FAULT 3 / DANGER 10 / WARNING 25 / 나머지 NORMAL)

### 2. `app/services/seeding.py` — COMP-001 200대 생성
- 기존 큐레이션 COMP-001 10대(MTR-001~010, 시나리오 포함)는 **보존**(기존 대시보드 데모 유지).
- **190대 프로그램 생성**(예: `MTR-101`~`MTR-290`): 위치 풀·모델 풀에서 배정, 목표 상태 분포에 맞춰 램프 시나리오 자동 생성(기존 `_SCENARIOS`/`_metric_value` 메커니즘 일반화). `SEED_RNG_SEED` 기반 결정론 유지.
- 벌크 모터는 `collection_interval_seconds=300`으로 텔레메트리 생성(행 수 억제). 기존 `_generate_series`/`_insert_telemetry`/`_insert_transitions`/`_seed_notifications` 그대로 재사용.
- 상태 분포가 상태별/확인사항 그룹핑에서 의미 있게 보이도록, 위치 풀은 위치별 그룹핑에서 여러 그룹이 나오도록 구성.

### 3. `app/services/motors.py` — 배치 조회 함수 신설
- `list_company_motor_status(conn, company_id) -> list[dict]`: 모터당 1쿼리 이하로 `motor_id, motor_name, installation_location, model_name, 대표상태, 최신 4지표 값, last_changed_at` 반환. (200대에서 `list_company_motors`의 모터별 서브쿼리 폭증을 회피 — 2P 카드·1P 목록 공용)
- 1P 차트용 시계열: 기존 `get_metric_trend(conn, motor_id, metric, hours, buckets)` 재사용하되, 모터당 4지표를 한 번에 주는 `get_motor_metric_series(conn, motor_id, hours, buckets)` 추가 검토(페이지당 쿼리 수 축소).

### 4. `app/pages/motor_graph.py` (신규) — 1페이지 [모터 그래프]
- 상단: `page_header()` + 페이지 내비 + "[모터 그래프]" 제목 + **페이지네이션 컨트롤**(모터 범위 selectbox 또는 prev/next, "모터 1–20 / 200").
- `st.columns(4)`로 온도/진동/전류/소음 열. 각 열 헤더 아래, 현재 페이지 모터마다 이름 + `st.line_chart`(해당 지표 최근 추이). 데이터는 §3 시계열 함수.
- 회사 격리: `st.session_state["company_id"]` 기준. 빈 회사 안전 처리.

### 5. `app/pages/motor_status.py` (신규) — 2페이지 [모터 현황]
- 상단: 헤더 + 페이지 내비 + `st.radio`로 그룹핑 모드(config `GROUPING_MODES`, 기본 `DEFAULT_GROUPING_MODE`).
- 그룹핑 로직:
  - 상태별: `STATUS_GROUP_ORDER` 순, 각 상태 그룹 헤더(`[FAULT]`…) + 카드.
  - 확인사항별: `ISSUE_GROUP_ORDER`(NORMAL 제외).
  - 위치별: `installation_location`으로 그룹, 헤더에 위치값.
- 카드: **신규 경량 `status_card(motor)`** — 이름+상태배지, 위치, 모델, `온도/진동`·`전류/소음`, "N시간 전 상태변경". 상태 색상은 기존 `status-{status}` CSS 클래스 재사용. 그룹 내 `STATUS_CARDS_PER_ROW`(10) 단위로 `st.columns`. 카드 클릭 → `selected_motor_id` 세팅 후 `st.switch_page(MOTOR_DETAIL_PAGE)` (기존 `motor_card` 패턴 재사용).
- 데이터: §3 `list_company_motor_status()`.

### 6. `app/ui/navigation.py` + `app/ui/components.py` — 내비게이션
- `navigation.py`: 경로 상수 `MOTOR_GRAPH_PAGE`, `MOTOR_STATUS_PAGE` 추가. 로그인 분기 `pages`에 `st.Page` 2개 추가(순서: 메인 대시보드(default)/모터 그래프/모터 현황/모터 상세).
- 사이드바가 숨겨져 있으므로 **`page_header()`에 상단 페이지 이동 내비(버튼 3개, `st.switch_page`)** 추가 → 3개 메인 페이지 간 이동 경로 확보.

### 7. `app/ui/components.py` — 경량 카드
- `status_card(motor: dict) -> None` 신설(§5). `_metric_html` 등 기존 헬퍼는 무거우므로 텍스트 위주로 새로 작성, 색상 클래스만 공유.

### 8. `.claude/docs/generated/05_ui_screens.md` — 스펙 반영
- §3(대시보드) 하위 또는 신규 절로 "모터 그래프 페이지", "모터 현황 페이지(그룹핑 3종)"를 확정 스펙으로 추가(구현 기준 문서 동기화 — 기존 계획들과 동일한 doc-sync 관행).

### 9. 성능 실측 (구현 마지막)
- 데모 데이터 재생성(§ 검증) 후 앱 실행, 1P(페이지당 80차트)·2P(200카드) 렌더 시간과 부팅 시간을 `scripts/screenshot.py`/브라우저로 실측. `GRAPH_PAGE_SIZE` 등 config로 조정.

---

## 수정/신규 파일 요약
- 신규: `app/pages/motor_graph.py`, `app/pages/motor_status.py`
- 수정: `app/config.py`, `app/services/seeding.py`, `app/services/motors.py`, `app/ui/navigation.py`, `app/ui/components.py`, `.claude/docs/generated/05_ui_screens.md`
- 재사용: `page_header`/`status_badge`/`motor_card` 패턴(`components.py`), `get_metric_trend`/`get_representative_status`(`motors.py`), `_generate_series` 등 시드 로직(`seeding.py`), `connection_scope`(`db/connection.py`)

## 검증 (end-to-end)
1. **데모 데이터 재생성**: 부팅 시 완료 마커/락 때문에 기존 `data/`가 있으면 재시드 안 됨 → `data/app.db`와 부트스트랩 마커 삭제 후 재실행(또는 `scripts/seed_data.py`). COMP-001 모터 200대 확인.
2. `uv run streamlit run main.py` → demo1@example.com(COMP-001)로 로그인.
3. 상단 내비로 **모터 그래프** 이동 → 4열 라인차트, 페이지네이션 동작, 200대 순회 확인.
4. **모터 현황** 이동 → 라디오로 상태별/위치별/확인사항별 전환, 그룹 헤더·10열 배치·카드 내용 확인. 카드 클릭 → 상세 페이지 이동 확인.
5. **기존 메인 대시보드**(요약/배너/이벤트)가 그대로 동작하는지 회귀 확인.
6. COMP-002(demo2) 로그인 시 회사 격리(200대 안 보임) 확인.
7. 1P/2P 렌더·부팅 시간 실측치 기록, 필요 시 `GRAPH_PAGE_SIZE`·벌크 수집주기 조정.

## 미해결/추후
- 실제 상태 전이 실시간 감지·자동 갱신은 이 작업 범위 밖(여전히 시드 시점 데이터).
- 200대 라인차트 성능이 목표에 못 미치면 `st.line_chart`→경량 인라인 SVG 스파크라인 대체를 후속 옵션으로 검토.
