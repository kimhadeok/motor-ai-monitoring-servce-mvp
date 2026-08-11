# 시연 완성도 마무리 — 남은 작업 (motor-052~)

## Context

`remaining_work.md`의 미완료 항목 중 **시연 완성도**에 해당하는 것들을 처리하는 작업이다.
사용자 확정: 2번의 MVP 범위는 **2-2(자동 갱신)까지**이며 2-1·2-3은 MVP 제외, 2-2에는
**경량 틱**을 함께 넣는다, 12번은 **오래된 구간만 성기게 저장**하는 방식으로 푼다.

이 계획서의 앞 절반(13·14·11·7·12)은 **이미 구현이 끝나 워킹트리에 있다**(커밋 전).
아래 "완료된 부분"은 무엇이 어떻게 바뀌었는지 기록이고, "남은 작업"이 실제로 할 일이다.

---

## 완료된 부분 (워킹트리, 미커밋)

| 항목 | 변경 | 실측 |
|---|---|---|
| **13** `use_container_width` | 14곳 → `width="stretch"`. [components.py](app/ui/components.py) 9 · [motor_detail.py](app/pages/motor_detail.py) 2 · [login.py](app/pages/login.py) 2 · [charts.py](app/ui/charts.py) 1 | 잔여 0곳, 컴파일 통과. Streamlit 1.60.0에서 5개 위젯 모두 `width` 지원 확인 |
| **14** uv.lock 문서 | [01_tech_stack.md](.claude/docs/generated/01_tech_stack.md) §2.6 — 배포 설치 경로가 `uv.lock`(uv-sync)임을 명시, `requirements.txt`는 폴백. Python 3.14.7 통과 사실 반영 | — |
| **11** 리포트 알림 이력 | [service.py](app/reports/service.py) `_lookup_notification()` 신규 — `(motor_id, created_at)`로 `notification_logs` 조회. 채널 노출, 미발송 시 사실대로. [report_template.html](app/reports/templates/report_template.html) §5 표·타임라인 조건부. `NOTIFICATION_CHANNEL_LABELS`·`NOTIFICATION_SKIPPED_REASON` 신규 상수 | DB 문구 == 리포트 문구 `True`, `KAKAO_ALIMTALK → 카카오 알림톡`. 양쪽 분기 렌더 확인 |
| **7** 대시보드 쿼리 | [motors.py](app/services/motors.py) `list_unconfirmed_fault_metrics()`(배치)·`attach_card_trends()` 신규. `list_company_motors()`에서 trend·`last_changed_at` 제거, [dashboard.py](app/pages/dashboard.py)가 선정 후 추이 채움 | **801회 → 222회**, 0.107초 → 0.009초. 상태 분포·FAULT 판정 동일 |
| **12** 시드 저장 밀도 | [seeding.py](app/services/seeding.py) `_generate_series()` — 걷기는 48h 원래 주기 유지, 저장만 선별(최근 8h 전량 + 전이 행과 직전 행 + 900초 간격). `SEED_DENSE_WINDOW_HOURS`·`SEED_SPARSE_INTERVAL_SECONDS` 신규 상수 | **288,210행 3.80초 → 81,858행 1.95초**. 전이 80건 유지 |

**12번 상수 값의 근거** (210대 시드, 전이는 어느 값에서도 80건):
288,210행 3.80초 → 300초 149,029행 2.88초 → 600초 98,650행 2.04초 →
**900초 81,858행 1.95초** → 1800초 65,067행 1.90초.
300초는 벌크 190대의 수집 주기와 같아 효과가 없고, 900초를 넘기면 생성 루프(1.70초)가 바닥이다.

**시드 시간 분해**: 생성(Python) 1.67초 / INSERT 2.06초(54%) / commit 0.07초.
저장만 줄이므로 생성 1.70초는 남는다 — 이것이 이 방식의 하한이다.

### 문서와 다른 것으로 확인된 사실 (문서에 반영해야 함)

- `remaining_work.md` #11의 주장 ③ "쿨다운으로 억제된 이벤트도 발송한 것처럼 적힌다"는
  **현재 시드에 인스턴스가 0건**이다 — DANGER/FAULT 로그 24건 = 알림 24건. 코드는 거짓을
  적을 수 있는 상태였지만 데모 데이터에 그 사례가 없었다. 방어 분기로서 구현했다.
- `remaining_work.md` #14는 "미착수"로 적혀 있으나 README는 이미 정정돼 있었다.
- 12번의 원인은 모터 대수가 아니라 **짧은 수집 주기 20대**다(전체 행의 62%).

---

## 남은 작업

### A. 자동 갱신 + 경량 틱 (2-2)

- 대시보드의 갱신 대상(요약 타일 · 모터 카드 그리드 · 이벤트 목록)을
  `@st.fragment(run_every=DASHBOARD_REFRESH_INTERVAL_SECONDS)` 함수로 분리한다.
  로그인 체크·헤더·내비게이션은 fragment 밖에 둔다(05 §5-2 확정 근거).
  현재 [dashboard.py](app/pages/dashboard.py)는 모듈 최상위에서 순차 실행하는 스크립트라,
  갱신 영역을 함수로 감싸는 구조 변경이 필요하다.
- **경량 틱** — 신규 `app/services/runtime_tick.py`:
  모터별 마지막 텔레메트리 시각 이후 경과분만큼 행을 이어 붙인다.
  `seeding._metric_value()`/`classify()`를 재사용하되 **상태 전이는 기록하지 않는다**
  (전이 판정은 2-1이며 MVP 범위 밖 — 사용자 확정).
  다중 탭 동시 실행은 `INSERT OR IGNORE`(PK `(time, motor_id)`)로 흡수한다.
- 틱이 붙으면 `DEMO_DATA_MAX_AGE_HOURS`(2h) 재시드가 사실상 걸리지 않게 되므로
  그 상호작용을 확인하고 문서에 적는다.
- 틱 비용을 측정한다 — 10초 간격에 실제로 몇 행이 들어가고 몇 ms가 걸리는지.

### B. 검증

Docker Desktop은 기동돼 있다(사용자가 실행함).

1. **PDF** — `02 §6.6`의 Debian trixie 컨테이너로 MTR-227(FAULT)·MTR-274(DANGER) 렌더.
   11번이 §5에 표 1행(발송 채널)을 추가했으므로 **5페이지 유지 · 머리글 줄바꿈 없음**을 확인.
   5페이지 내용 하단이 601.2pt / 본문 한계 774pt였으므로 여유는 충분할 것으로 보이나 미검증.
   미발송 분기(§5 "발송 없음")도 한 건 렌더해 레이아웃을 확인한다.
2. **화면 (다크 모드)** — 앱을 띄워 재시드가 일어난 뒤:
   - 대시보드 카드 스파크라인이 다시 채워지는지 (**현재 로컬 DB는 어제 시드라 6시간 창이
     비어 추이가 0건이다** — 코드 변경과 무관함을 48h 창으로 확인했으나, 재시드 후 재확인 필요)
   - `width="stretch"` 전환 후 카드·버튼 폭이 동일한지
   - 자동 갱신이 돌 때 숫자·그래프가 실제로 움직이는지
   - 콘솔에서 `use_container_width` deprecation 경고가 사라졌는지
3. **시드 회귀** — 재시드 후 모터 210 · `status_logs` 80 · `notification_logs` 24 유지 확인.
4. **미검증으로 남길 것** — 배포 환경 콜드 부팅 실제 단축폭. 배포 후 Manage app 로그의
   `부트스트랩 완료 | … | N초`로 판정한다(`02 §6.5`). 로컬 -49%가 배포에서 그대로 나오리라
   단정하지 않는다.

### C. 문서 갱신

- **`remaining_work.md`** — 머리말 기준 커밋 정정, 2번 범위 확정(2-2까지 MVP / 2-1·2-3 제외),
  7·11·12·13·14 상태 갱신, 위 "문서와 다른 것으로 확인된 사실" 3건 반영, 진행 로그 추가.
- `01_tech_stack.md` §2.5 — 자동 갱신 구현 반영
- `02_architecture.md` §6.1 — 시드 저장 정책(dense/sparse)과 그 근거, 틱 경로 신설
- `05_ui_screens.md` §3.1/§3.2/§3.3 자동 갱신 적용 범위, §5-2 구현 완료로, §3.2 추이 조회 시점
- `06_report_spec.md` §2.5 — 채널 노출·발송 없음 표기. 타임라인 발송 시각은 리포트 생성
  시각을 쓰고 `notification_logs.created_at`(=전이 시각)은 쓰지 않는 이유를 함께 적는다
- `README.md` — 자동 갱신·시드 정책
- 이 계획서를 `.claude/docs/plan/2026-08-11_demo-polish.md`로 복사

### D. 커밋

**대상·메시지 초안을 제시하고 승인받은 뒤에만** 실행한다(CLAUDE.md Commit Workflow).
제안 단위: `motor-052` 13+14 / `motor-053` 11 / `motor-054` 7 / `motor-055` 12 /
`motor-056` 2-2. 검증이 끝나지 않은 변경은 그 사실을 명시해 사용자가 나눌 수 있게 한다.
