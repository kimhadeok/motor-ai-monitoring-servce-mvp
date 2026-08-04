# 05. 화면/UI 명세

> 원본: `.claude/docs/user/화면구성.md`
> 반영: `01_tech_stack.md`(화면 스타일링), `03_state_event_logic.md`(FAULT 수동 복구, 통신 두절), `04_database_schema.md`(테이블 구조)
> 작성: coreagent · 상태: 확정

## 1. 페이지 목록

| # | 페이지 | 접근 조건 |
|---|---|---|
| 1 | 로그인 | 비로그인 상태 진입 |
| 2 | 메인 대시보드 | 로그인 필요 |
| 3 | 모터 상세 | 로그인 필요, 메인에서 모터 클릭 시 진입 |

## 2. 로그인 페이지

- 입력: 이메일(ID) + 비밀번호 (`company_contacts.email`, `password_hash` 대조)
- 부가 검증: 접속 IP가 `company_contacts.allowed_ip`에 값이 있는 경우 해당 IP만 허용 (MAC 주소 체크는 미적용 — §5-1 참고)
- 로그인 시도는 성공/실패 관계없이 `login_logs`에 기록 (성공 시 `contact_id` 채움, 실패 시 NULL 허용)
- 성공 시 메인 대시보드로 이동

## 3. 메인 대시보드

### 3.1 상단 — 회사/현황 정보

| 표시 항목 | 데이터 출처 |
|---|---|
| 회사 정보 | `companies` (로그인한 담당자의 `company_id` 기준) |
| 등록된 모터 수 | `motors` count (해당 company_id) |
| 서비스 시작 일자 | `companies.created_at` |
| 총 운영 일수 | `오늘 - companies.created_at` (일 단위, 보강: 계산식 명시) |
| 상태별 모터 수 (NORMAL 제외) | 각 모터의 **대표 상태**(`03_state_event_logic.md` §2 — 4개 지표 중 최고 심각도) 기준 WARNING/DANGER/FAULT 개수 집계 |

### 3.2 모터별 카드

```
[모터 이미지] --> [API 이미지] --> [AI Agent 아이콘]
   모터 모델명
   [상태 배지: WARNING]
   26/07/01 13:05
```

- 모터 이미지 → API → AI Agent 흐름을 "데이터가 흐르는 것처럼" 애니메이션 표시
  - 구현: `01_tech_stack.md` §2.5에서 확정한 커스텀 CSS 애니메이션 또는 `streamlit-lottie` 사용
- 상태 배지: 모터 대표 상태 + 최근 상태 변경 일시(`motor_status_logs` 최신 `created_at`)
- 상태별 색상 (보강 — report_template.html과 통일된 팔레트 재사용, 아래 §4 참고)
- 카드 클릭 시 모터 상세 페이지로 이동

### 3.3 이벤트 발생 내역 리스트

- 컬럼: 발생 일시, 모터명, 모터 상태, 리포트 버튼(있는 경우)
- 데이터 출처: `motor_status_logs` (모터 대표 상태 기준 전이 이벤트, 최신순)
- 최근 **최대 10개** 표시

**리포트 버튼 규칙 (2026-08-04 확정)**

- **노출 조건**: `new_status`가 **DANGER 또는 FAULT**인 로그. (PDF를 요청 시 생성하는 방식이므로 최초에는 `report_pdf`가 항상 NULL이며, 이를 노출 조건으로 쓸 수 없다.)
- **클릭 시 동작**:
  1. `report_pdf`에 캐시된 값이 있으면 그대로 다운로드 제공
  2. 없으면 저장된 `report_html`로 PDF 생성을 시도 → 성공 시 `report_pdf`에 캐시 후 다운로드 제공
  3. PDF 생성이 불가한 환경이면 저장된 `report_html`을 화면에 표시
- 어느 경로든 파일시스템에 저장하거나 조회하지 않는다 (메모리 내 처리).
- PDF는 `st.download_button`으로 다운로드, HTML은 `st.components.v1.html`로 인앱 표시한다.
- `report_html`은 진단 시점에 항상 생성되므로 **버튼이 보이는데 보여줄 것이 없는 상황은 발생하지 않는다** (`04_database_schema.md` §3.5).

## 4. 모터 상세 페이지

### 4.1 기본 정보

- 등록일자, 모터명, 모델명, 설치 위치, 시리얼 번호 (`motors` 테이블)

### 4.2 지표별 임계값 표시

- 온도/진동/전류/소음 각각 NORMAL/WARNING/DANGER/FAULT 구간을 표로 표시
- 데이터 출처: `motor_thresholds` (`04_database_schema.md` §2에서 신설된 테이블, 지표별로 4행)

### 4.3 FAULT 정비 완료 처리 (신규 — `03_state_event_logic.md` §8-3 반영)

- 모터의 특정 지표가 FAULT이고 아직 관리자 확인 전(§3 참고: 최신 로그가 FAULT이고 `contact_id`가 NULL)인 경우, **"정비 완료 확인"** 버튼 노출
- 버튼 클릭 시:
  1. 로그인한 담당자의 `contact_id`로 `motor_status_logs`에 신규 행 기록 (`trigger_reason`: "관리자 정비완료 확인", `contact_id` 채움)
  2. 이후부터 해당 (모터, 지표)의 자동 상태 판정 재개
- 버튼은 실수 클릭 방지를 위해 확인 다이얼로그(예: `st.dialog` 또는 체크박스+버튼 조합) 동반 권장 (보강)

### 4.4 이벤트 발생 내역 리스트

- 컬럼: 발생 일시, 모터 상태, 리포트 버튼
- 데이터 출처: `motor_status_logs` (해당 모터 전체 지표 이벤트)
- 페이징: 페이지당 20개
- 리포트 버튼의 노출 조건과 클릭 동작은 §3.3과 동일하다 (DANGER/FAULT 로그에 노출, PDF 우선 제공하되 불가 시 HTML 표시)

## 5. 확정 사항 (보강/제안 항목)

### 5-1. 로그인 시 MAC 주소 체크 → IP 체크만 적용 (확정)

MAC 주소는 일반 웹 브라우저 요청에서 서버가 확인할 방법이 없어(HTTP 프로토콜 자체의 구조적 제약) 요구사항에서 제외. `company_contacts.allowed_ip` 기반 IP 체크만 적용 (§2 반영 완료).

### 5-2. 실시간 그래프 자동 갱신 방식 → st.fragment(run_every=...) 적용 (확정)

최초 제안한 `streamlit-autorefresh`는 내부적으로 `st.rerun()`을 호출해 **스크립트 전체를 재실행**하는 방식이라 페이지가 커질수록 갱신마다 불필요하게 느려지는 문제가 있음. 대신 Streamlit 1.33+ 내장 기능인 **`st.fragment(run_every="10s")`**로 확정 — 차트/카드 등 갱신이 필요한 영역만 함수 단위로 분리해 해당 부분만 부분 재실행되도록 함(로그인 체크, DB 조회, 다른 카드 렌더링 등 나머지 페이지는 재실행되지 않음). 별도 패키지 설치 불필요. **`01_tech_stack.md` §2.5에도 반영 완료.**

### 5-3. 상태별 색상 팔레트 통일 (확정)

| 상태 | 색상 | 근거 |
|---|---|---|
| NORMAL | `#16a34a` (녹색) | report_template.html `--success` |
| WARNING | `#d97706` (주황) | report_template.html `--warning` |
| DANGER | `#dc2626` (적색) | report_template.html `--danger` |
| FAULT | `#1e293b` (짙은 회색/정지 표시) | 신규 제안 — "위험(적색)"과 "정지(회색)"를 시각적으로 구분 |

---
승인해주시면 다음 문서(`06_report_spec.md`) 작성을 진행하겠습니다.
