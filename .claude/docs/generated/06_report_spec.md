# 06. 리포트(PDF) 생성 명세

> 원본: `.claude/docs/report_template.html`
> 반영: `01_tech_stack.md`(Jinja2/WeasyPrint), `03_state_event_logic.md`(DANGER/FAULT 자동 리포트 생성), `04_database_schema.md`(테이블 구조)
> 작성: coreagent · 상태: 확정

## 1. 렌더링 파이프라인

```
DANGER/FAULT 이벤트 발생 (03_state_event_logic.md)
  → AI 에이전트 진단 결과(텍스트/수치) 생성
  → Jinja2로 report_template.html에 데이터 바인딩
  → WeasyPrint로 HTML → PDF 변환
  → PDF 파일 저장 후 URL을 motor_status_logs.agent_diagnosis에 기록
  → notification_logs로 담당자에게 다운로드 링크 포함 알림 발송
```

## 2. 섹션별 명세 및 MVP 데이터 매핑

원본 `report_template.html`은 특정 장애 사례(베어링 외륜 손상)를 가정한 **목업 데이터**로 채워져 있음. 아래는 각 섹션을 실제 MVP 데이터 소스에 매핑한 것.

### 2.1 헤더 / 메타 정보

| 템플릿 항목 | MVP 데이터 소스 |
|---|---|
| 상태 배지 (CRITICAL 등) | 이벤트를 유발한 상태 (`DANGER` 또는 `FAULT`) |
| 대상 설비 ID / 설치 위치 | `motors.motor_id`, `motors.installation_location` |
| 모터 규격/모델 | `motors.model_name` |
| 정격 속도/전압 | **리포트에서 제외 (확정)** — `motors` 스키마 확장하지 않음 |
| 이벤트 감지 시각 | `motor_status_logs.created_at` (해당 전이 로그) |
| 에이전트 세션 ID | `motor_{motor_id}_{날짜}_{시각}` 형식으로 확정 (예: `motor_MTR-001_20260803_171000`) |

### 2.2 센서 측정 데이터 표 (원본 §1)

원본 목업은 5개 세부 항목(베어링 하우징 온도, 진동속도 RMS, 진동가속도 Peak, 3상 전류 불평형률, 음향 FFT Peak)을 예시로 보여주나, `motor_telemetry`(04)에는 **온도/진동/전류/소음 4개 원시 값만** 존재. **MVP 범위 축소 제안**: 4개 항목 표로 단순화.

| 측정 항목 | 현재 측정값 | 정상 기준 범위 | 상태 평가 |
|---|---|---|---|
| 온도 | `motor_telemetry.temperature` | `motor_thresholds`(temperature) | `temp_status` |
| 진동 | `motor_telemetry.vibration` | `motor_thresholds`(vibration) | `vib_status` |
| 전류 | `motor_telemetry.current` | `motor_thresholds`(current) | `current_status` |
| 소음 | `motor_telemetry.sound` | `motor_thresholds`(sound) | `sound_status` |

값은 이벤트 발생 시점(`motor_status_logs.created_at`)의 `motor_telemetry` 레코드 기준.

### 2.3 AI 진단 및 근본 원인 분석 (원본 §2)

| 템플릿 항목 | MVP 데이터 소스 |
|---|---|
| 추론 엔진 분석 결과 요약 (주요 원인/연쇄 영향/방치 시 예상 결과) | AI 에이전트(LangChain/LangGraph, `02_architecture.md` §2.4)의 장애 원인 추론 툴 출력 텍스트 |
| 진단 신뢰도(%) + 진행바 | **리포트에서 제외 (확정)** — LLM에 confidence 출력을 요구하는 추가 설계 없이 진단 텍스트만 표시 |
| 진단 모델명 표시 | 고정 텍스트로 대체 제안: "GPT-4o 기반 진단 에이전트" (`01_tech_stack.md` 모델과 일치) |

### 2.4 정비 가이드(SOP) & 부품 정보 (원본 §3)

| 템플릿 항목 | MVP 데이터 소스 |
|---|---|
| 정비 조치 절차 (SOP 리스트) | RAG 대응 매뉴얼 조회 툴 출력 (`02_architecture.md` §2.4, ChromaDB 검색 결과) |
| 자재 창고 예비 부품 재고 현황 (CMMS 연동) | **MVP 범위 밖 — 제외 확정**. CMMS 연동 시스템이 `01_tech_stack.md`에 없음 |

### 2.5 자동 대응 및 통보 이력 (원본 §4)

| 템플릿 항목 | MVP 데이터 소스 |
|---|---|
| 이상 감지 / AI 분석 완료 타임스탬프 | `motor_status_logs.created_at`(이상 감지) + 리포트 생성 완료 시각(PDF 저장 시점, 확정) — 에이전트 시작/종료 시각 별도 기록은 생략 |
| 자동 인터락(PLC 정지 제어) | **MVP 범위 밖 — 제외 확정**. PLC 연동 시스템 없음 (`01_tech_stack.md`) |
| 긴급 알림 발송 + ERP/CMMS 자재 예약(WO 생성) | 알림 부분만 유지: `notification_logs` 발송 이력. ERP/CMMS 자재 예약은 **MVP 범위 밖 — 제외 확정** |
| 수신 담당자 / 발송 문구 | `notification_logs.contact_id`(→ `company_contacts.contact_name`), `notification_logs.message_content` |

## 3. MVP 리포트 섹션 구성 (최종 제안)

위 매핑을 반영해 MVP 리포트는 원본의 5개 섹션 중 **CMMS 부품 재고, PLC 자동 인터락, ERP 자재 예약**을 제외한 아래 구성으로 축소 제안:

1. 헤더/메타 정보
2. 센서 측정 데이터 (4개 지표)
3. AI 진단 및 근본 원인 분석 (신뢰도 게이지 제외, 텍스트 위주)
4. 정비 가이드(SOP) — RAG 매뉴얼 기반 (부품 재고 제외)
5. 자동 대응 이력 — 이상감지/AI분석/알림발송만 (PLC 인터락 제외)

## 4. 확정 사항 (coreagent 제안대로 확정)

1. **정격 속도/전압 등 모터 스펙**: 리포트에서 제외. `motors` 테이블 확장하지 않음.
2. **에이전트 세션 ID 채번 규칙**: `motor_{motor_id}_{날짜}_{시각}` 형식으로 확정.
3. **AI 진단 신뢰도(%) 표시**: 제외. 진단 텍스트만 표시.
4. **§3 MVP 리포트 섹션 구성**: CMMS 부품 재고 / PLC 자동 인터락 / ERP 자재 예약 제외 확정.
5. **에이전트 분석 소요 시간 기록**: 별도 컬럼(`agent_started_at`/`agent_completed_at`) 추가하지 않고, 리포트 생성 완료 시각만 표시하는 것으로 확정 — `04_database_schema.md` 스키마 변경 없음.

---
6개 문서(`01_tech_stack.md` ~ `06_report_spec.md`) 모두 확정되었습니다. 계획된 문서 생성 작업이 마무리되었습니다.
