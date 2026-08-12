# 04. 데이터베이스 설계 명세 (SQLite / MVP)

> 원본: `.claude/docs/user/테이블 설계.md`
> 반영: `01_tech_stack.md`(SQLite 확정), `03_state_event_logic.md`(지표별 임계값, 쿨다운, FAULT 수동 복구, 통신 두절)
> 작성: coreagent · 상태: 확정

## 1. MVP 적용 시 타입 매핑

원본은 PostgreSQL/TimescaleDB 스타일 표기(`TIMESTAMPTZ`, `Hypertable`, `BIGSERIAL`)를 사용하나, `01_tech_stack.md`에서 **SQLite**로 확정했으므로 아래 규칙으로 변환:

| 원본 표기                      | SQLite 적용                                              | 비고                                                                     |
| ------------------------------ | -------------------------------------------------------- | ------------------------------------------------------------------------ |
| `TIMESTAMPTZ`                | `TEXT` (ISO8601 UTC, 예: `2026-08-03T07:15:37.163Z`) | SQLite에 날짜 전용 타입 없음. 문자열 정렬로 시간 비교 가능               |
| `Hypertable`                 | 미적용 — 일반 테이블 + 복합 인덱스                      | `03_state_event_logic.md` §6에서 확정한 대로 쿼리 시점 조회 방식 사용 |
| `BIGSERIAL` / `VARCHAR(n)` | `INTEGER PRIMARY KEY AUTOINCREMENT` / `TEXT`         | SQLite는 동적 타입 — 길이 제약 대신 애플리케이션 레벨 검증              |
| `BOOLEAN`                    | `INTEGER` (0/1)                                        | SQLite 네이티브 BOOLEAN 없음                                             |

## 2. 보강 — motors 테이블 임계값 구조 변경 (중요)

**문제**: 원본 `motors` 테이블은 `normal_range/warning_range/danger_range/fault_range` **단일 세트**만 갖고 있음. 그러나 `motor_telemetry`는 온도/진동/전류/소음 **4개 지표를 각각** 다른 단위(°C, mm/s, A, dB)로 측정하고 개별 상태(`temp_status` 등)를 판정함 — 단일 임계값 세트로는 4개 지표를 판정할 수 없음. 이는 원본 설계의 누락으로 판단되어 보강함.

**해결**: 임계값을 모터 테이블에서 분리해 지표별 임계값 테이블 신설.

```sql
CREATE TABLE motor_thresholds (
  motor_id      TEXT NOT NULL REFERENCES motors(motor_id),
  metric_name   TEXT NOT NULL CHECK (metric_name IN ('temperature','vibration','current','sound')),
  normal_range  REAL,   -- normal_range <= 값 < warning_range
  warning_range REAL,   -- warning_range <= 값 < danger_range
  danger_range  REAL,   -- danger_range <= 값 < fault_range
  fault_range   REAL,   -- 값 >= fault_range
  PRIMARY KEY (motor_id, metric_name)
);
```

`motors` 테이블에서는 `normal_range` 등 4개 컬럼을 제거함 (§3 DDL에 반영).

### 2.1 이 테이블이 실제 판정에 쓰인다 (2026-08-11 정정)

**2026-08-11까지 이 테이블은 표시용으로만 쓰이고 있었다.** 상태 판정·카드 게이지·차트 임계선·진단 근거·런타임 틱은 전부 `config.METRIC_THRESHOLDS` **전역 하드코딩**을 읽었고, `motor_thresholds`를 읽는 곳은 모터 상세의 임계값 표와 리포트 참고표 두 군데뿐이었다.

그래서 관리자 페이지(05 §6)에서 임계값을 바꾸면 **같은 리포트 한 장 안에 서로 다른 기준이 찍혔다** — 센서 카드 "정상 기준 ≤ 60 °C"(전역값)와 임계값 표 "정상 구간 < 50"(DB값)이 동시에. 실측으로 재현해 확인했다.

지금은 `services/motors.get_metric_thresholds()`(단건) / `list_company_metric_thresholds()`(회사 배치)가 유일한 출처이고, 판정·표시가 모두 이 값을 본다. `config.METRIC_THRESHOLDS`는 **모터 등록 시 채워 넣는 기본값**이자 행이 없을 때의 폴백일 뿐이다.

### 2.2 임계값을 바꾸면 언제부터 적용되나 (2026-08-11 확정)

| 대상 | 규칙 | 근거 |
|---|---|---|
| 과거 전이 로그·발행된 리포트 | **불변** | 발행된 문서다. 사후에 기준을 바꿔 과거 판정을 뒤집으면 이미 나간 리포트·알림과 어긋나고, 사고 조사에서 "그때는 왜 FAULT가 아니었나"를 설명할 수 없다 |
| 저장된 계측 행의 `*_status` | **불변** | 그 시각 그 기준으로 판정한 사실이라 역시 기록이다 |
| 새로 수집되는 행 | **새 기준으로 판정** | 판정은 수집 시점에 한 번 — 이 원칙을 과거·현재에 똑같이 적용한다 |
| 화면의 기준선 표시 | **즉시 새 값** | 게이지 눈금·차트 임계선·리포트 참고표·센서 카드 "정상 기준"은 판정이 아니라 "지금 기준이 무엇인가"라서 옛 값을 보여줄 이유가 없다 |

즉 **바꾼 기준은 다음 수집분부터 적용된다.** 반영 지연은 최대 1수집주기(10~300초)이며, 관리자 화면이 그 사실과 해당 모터의 수집 주기를 함께 안내한다.

실측(2026-08-11): 온도 26.6 °C·NORMAL인 10초 주기 모터의 경고 임계를 24.6으로 낮췄을 때 — 변경 직후 최신 행은 `NORMAL` 유지, 12초 뒤 틱이 넣은 새 행은 `WARNING`, 과거 행과 전이 로그 80건은 그대로.

**런타임 틱도 함께 고쳐야 했다.** 틱은 "상태를 바꾸지 않는다"는 규칙으로 값을 구간 안에 묶는데, 그 구간을 **저장된 status**에서 뽑고 있었다. 임계값을 낮추면 값을 옛 상태의 구간으로 끌어내려 낡은 판정을 억지로 유지시킨다 — 데이터를 조작해 설정 변경을 무력화하는 셈이다. 지금은 값을 **현재 임계로 다시 분류한** 구간에서 흔들리게 한다(`services/runtime_tick.py`).

## 3. 테이블 정의 (SQLite DDL)

### 3.1 companies

```sql
CREATE TABLE companies (
  company_id   TEXT PRIMARY KEY,               -- 예: COMP-001
  company_name TEXT NOT NULL,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

### 3.2 company_contacts

```sql
CREATE TABLE company_contacts (
  contact_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id    TEXT NOT NULL REFERENCES companies(company_id),
  contact_name  TEXT NOT NULL,
  phone_number  TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,           -- 로그인 ID
  password_hash TEXT NOT NULL,
  is_primary    INTEGER NOT NULL DEFAULT 0,     -- 0/1
  allowed_ip    TEXT,                           -- NULL이면 IP 제한 없음
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

### 3.3 motors

```sql
CREATE TABLE motors (
  motor_id               TEXT PRIMARY KEY,      -- 예: MTR-001
  company_id             TEXT NOT NULL REFERENCES companies(company_id),
  motor_name             TEXT NOT NULL,
  installation_location  TEXT NOT NULL,
  model_name             TEXT NOT NULL,
  serial_number          TEXT UNIQUE,
  collection_interval_seconds INTEGER NOT NULL DEFAULT 20,  -- 보강: 10/20/30초. §4.4 통신 두절 판정 기준
  created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
  -- normal_range 등 임계값 4종은 motor_thresholds 테이블로 분리 (§2)
);
```

### 3.4 motor_telemetry (시계열)

```sql
CREATE TABLE motor_telemetry (
  time            TEXT NOT NULL,                -- ISO8601, 수집 시점
  motor_id        TEXT NOT NULL REFERENCES motors(motor_id),
  company_id      TEXT NOT NULL REFERENCES companies(company_id),
  temperature     REAL NOT NULL,
  temp_status     TEXT NOT NULL,                -- NORMAL/WARNING/DANGER/FAULT
  vibration       REAL NOT NULL,
  vib_status      TEXT NOT NULL,
  current         REAL NOT NULL,
  current_status  TEXT NOT NULL,
  sound           REAL NOT NULL,
  sound_status    TEXT NOT NULL,
  PRIMARY KEY (time, motor_id)
);

-- 슬라이딩 윈도우 조회(단기 2h/장기 6h) 최적화 (03_state_event_logic.md §6)
CREATE INDEX idx_motor_telemetry_motor_time ON motor_telemetry (motor_id, time DESC);
```

> 보관 범위(48시간, `02_architecture.md` §4)를 넘는 데이터는 배치로 삭제/아카이브 (§5-3 참고).

### 3.5 motor_status_logs (상태 변화 및 이벤트 로그)

```sql
CREATE TABLE motor_status_logs (
  log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  motor_id        TEXT NOT NULL REFERENCES motors(motor_id),
  metric_name     TEXT NOT NULL CHECK (
                    metric_name IN ('temperature','vibration','current','sound','connectivity')
                    -- 'connectivity' = 보강, 통신 두절 이벤트 (03_state_event_logic.md §4.4)
                  ),
  previous_status TEXT NOT NULL,                -- NORMAL/WARNING/DANGER/FAULT (connectivity는 OK/NO_DATA)
  new_status      TEXT NOT NULL,
  trigger_reason  TEXT,                         -- 예: "진동 임계치 초과", "급변(단계 스킵)", "센서 점검 권장"
  report_html     TEXT,                         -- 리포트 HTML 원문 (최초 열람 시 생성·저장 — 2026-08-07 변경)
  report_pdf      BLOB,                         -- 리포트 PDF 바이너리 (요청 시 생성 후 캐시, 파일시스템 미사용 — 2026-08-04 확정)
  contact_id      INTEGER REFERENCES company_contacts(contact_id),  -- 보강: 관리자 수동 조치자(정비완료 확인 등)
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_motor_status_logs_lookup ON motor_status_logs (motor_id, metric_name, created_at DESC);
```

**리포트 컬럼 2종 운용 (2026-08-04 확정)**

| 컬럼            | 타입 | 생성 시점                          | 비고                                                  |
| --------------- | ---- | ---------------------------------- | ----------------------------------------------------- |
| `report_html` | TEXT | DANGER/FAULT 로그의 **최초 열람 시** (2026-08-07 변경) | Jinja2 렌더는 순수 Python이라 환경과 무관하게 성공. 종전에는 진단 시점에 전건 생성했으나 RAG 임베딩 왕복이 콜드 스타트를 지배해 온디맨드로 옮겼고, 2026-08-10에 진단 LLM 호출까지 이 경로에 들어왔다 — `06_report_spec.md` §3 |
| `report_pdf`  | BLOB | 사용자가 리포트를 요청할 때        | WeasyPrint 성공 시 저장해 캐시. 이후 요청은 즉시 응답 |

`report_html`을 BLOB이 아닌 **TEXT**로 두는 이유: HTML은 UTF-8 텍스트이고 렌더 함수가 `str`을 반환하므로 encode/decode 변환이 불필요하며, `sqlite3` CLI로 내용을 직접 확인할 수 있다. 반면 PDF는 바이너리이므로 BLOB이 맞다.

PDF 생성이 불가한 환경(네이티브 라이브러리 미설치)에서는 `report_pdf`가 계속 NULL로 남고 저장된 `report_html`이 대신 제공된다 — `05_ui_screens.md` §3.3.

**이벤트 목록 조회는 `motor_telemetry`를 함께 읽는다 (2026-08-07).** 화면의 "값 변화" 열(`05_ui_screens.md` §3.3)이 계측값을 요구하는데 `motor_status_logs`에는 값이 없다. `services/events.py`가 두 가지를 덧붙여 조회한다.

- **이벤트 시점 값**: `LEFT JOIN motor_telemetry t ON t.motor_id = l.motor_id AND t.time = l.created_at` — 상태 로그와 계측 행이 같은 시각을 공유하는 구조(`03_state_event_logic.md`)를 이용한다. 짝이 없으면 NULL이 되고 화면은 있는 값만 보여준다.
- **직전 값**: `l.created_at`보다 앞선 가장 최근 계측 행을 상관 서브쿼리로 가져온다. `idx_motor_telemetry_motor_time`(motor_id, time DESC)을 타므로 목록 크기(대시보드 10건 / 상세 20건)에서 부담이 없다.
- `metric_name`이 행마다 다르므로 `CASE l.metric_name WHEN 'temperature' THEN t.temperature …`로 컬럼을 고른다. `connectivity`는 대응 컬럼이 없어 NULL이다.

### 3.6 login_logs

```sql
CREATE TABLE login_logs (
  log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  contact_id  INTEGER REFERENCES company_contacts(contact_id),  -- 실패 시 NULL 허용
  ip_address  TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

### 3.7 notification_logs

```sql
CREATE TABLE notification_logs (
  notification_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  motor_id             TEXT NOT NULL REFERENCES motors(motor_id),
  contact_id           INTEGER NOT NULL REFERENCES company_contacts(contact_id),
  channel_type         TEXT NOT NULL CHECK (channel_type IN ('KAKAO_ALIMTALK','SMS','EMAIL')),
  external_message_id  TEXT,
  title                TEXT,
  message_content      TEXT NOT NULL,
  created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

> **MVP에서 이 테이블은 "적재"까지만이다 (2026-08-10 확정).** 실제 채널 발송(KAKAO/SMS/EMAIL 어댑터, 발신번호 등록, 실패 재시도)은 정식 서비스 개발 시 적용한다. MVP는 시연을 위해 시드가 DANGER/FAULT 전이에 쿨다운을 적용해 샘플 행을 만든다. `external_message_id`는 실제 발송이 없으므로 채워지지 않는다.
>
> **한 번의 알림은 채널마다 한 행이다 (2026-08-12 사용자 확정).** 문자가 기본 채널이고 이메일이 함께 나간다 — **이메일만 단독으로 발송되지 않는다**(`config.NOTIFICATION_DEFAULT_CHANNELS`). 같은 이벤트의 행들은 `created_at`을 공유하며, 리포트 §5가 그 쌍을 한 이벤트로 묶어 채널을 모두 표기한다(`06 §2.5`).
>
> - 실측(2026-08-12): **통보 이벤트 24건 · 발송 기록 48행** (SMS 24 · EMAIL 24). 이벤트 수는 이전과 같고 채널당 행이 생겼다.
> - 종전(~2026-08-11)에는 세 채널 중 하나를 무작위로 골라 **이벤트당 1행**이었다(24행 — KAKAO 11 · SMS 8 · EMAIL 5). 그래서 리포트가 "이메일로만 통보했다"고 적는 경우가 생겼는데, 실제 발송 방식과 어긋난다.
> - 카카오 알림톡은 채널 상수와 리포트 표기 순서에 남아 있지만 **시드는 발행하지 않는다.** 기록이 생기면 리포트에 자동으로 함께 나온다.

### 3.9 motor_threshold_history (2026-08-11 신설)

```sql
CREATE TABLE motor_threshold_history (
  history_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  motor_id          TEXT NOT NULL REFERENCES motors(motor_id),
  metric_name       TEXT NOT NULL CHECK (
                      metric_name IN ('temperature','vibration','current','sound')
                    ),
  previous_normal   REAL,   -- 바꾸기 직전 값
  previous_warning  REAL,
  previous_danger   REAL,
  previous_fault    REAL,
  normal_range      REAL,   -- 바꾼 값
  warning_range     REAL,
  danger_range      REAL,
  fault_range       REAL,
  contact_id        INTEGER REFERENCES company_contacts(contact_id),  -- 담당자 삭제 시 NULL
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_motor_threshold_history_lookup
  ON motor_threshold_history (motor_id, created_at DESC);
```

**왜 필요한가.** 임계값을 바꾸면 **그 시점 이후 수집분부터** 새 기준으로 판정되고 과거 판정·리포트는 그대로 남는다(§2.2). 그러면 나중에 이력을 볼 때 **"이 전이는 어느 기준으로 판정된 것인가"**에 답할 수 없다. 사고 조사에서 그 질문에 답하지 못하면 리포트를 근거 문서로 쓸 수 없다.

**값이 실제로 달라진 지표만 남긴다** — 저장 버튼을 눌렀다는 사실은 이력이 아니다. `services/admin.update_thresholds()`가 변경 전 값과 대조해 기록하고 바뀐 지표 수를 반환한다. 관리자 화면이 최근 `ADMIN_THRESHOLD_HISTORY_LIMIT`(20)건을 보여준다.

모터를 삭제하면 이 이력도 함께 지운다(`PRAGMA foreign_keys = ON`이라 순서상 자식 먼저).

## 4. 관계 요약

```
companies 1─N company_contacts
companies 1─N motors
motors    1─N motor_thresholds   (모터당 지표 4행: temperature/vibration/current/sound)
motors    1─N motor_telemetry
motors    1─N motor_status_logs
motors    1─N notification_logs
company_contacts 1─N login_logs
company_contacts 1─N notification_logs
company_contacts 1─N motor_status_logs (관리자 수동 조치 시)
motors    1─N motor_threshold_history   (임계값 변경 이력, §3.9)
company_contacts 1─N motor_threshold_history (변경자)
```

### 4.1 DB에 두지 않는 데이터 (2026-08-07 확정)

**참조 지식(고장 모드 ↔ 지표 매핑)은 테이블로 만들지 않는다.** `uploads/Reference/` PDF에서 큐레이션한 "지표 이상 → 의심 고장모드 → 부품/조치" 매핑이며, `data/knowledge/fault_modes.json`에 커밋하고 `app/rag/knowledge.py`가 직접 읽는다.

근거는 세 가지다.

- **규모**: 고장모드 9건 + 지표 매핑 17건 = 총 26행. 시간에 무관한 정적 데이터이고 전부 저장소에 커밋된다.
- **조인 지점 없음**: 조회 입력은 지표명 하나뿐이고 `motors`·`motor_telemetry` 등 런타임 테이블과 조인할 일이 없다. 두 정적 테이블 사이의 조인은 JSON에서 필터·정렬로 끝난다.
- **수명주기 불일치**: `data/app.db`는 데모 데이터가 실행 시각 기준이라 부팅마다 재생성된다(`02_architecture.md` §6.1). 정적 지식을 여기 두면 부팅마다 시드하는 비용만 붙는다.

같은 이유로 그래프DB도 도입하지 않는다 — 근거는 `01_tech_stack.md` §2.3.1. RAG 벡터는 `data/chroma/`(ChromaDB)가 담당하며 역시 DB 밖이다.

## 5. 보강 항목 (확정)

5개 항목 모두 coreagent 제안대로 확정 — §3 DDL에 반영 완료:

1. **motor_thresholds 신설 (§2)**: 원본 설계 누락 보강 — 지표별(온도/진동/전류/소음) 임계값 분리.
2. **motors.collection_interval_seconds 추가 (§3.3)**: 통신 두절 판정(§4.4, 연속 3주기 미수신) 계산에 사용.
3. **motor_status_logs.contact_id 추가 (§3.5)**: FAULT 수동 복구("정비 완료" 확인) 처리자 기록.
4. **motor_status_logs.metric_name에 'connectivity' 값 추가 (§3.5)**: 통신 두절 이벤트를 별도 테이블 없이 기존 로그 테이블에 통합 기록.
5. **48시간 초과 데이터 삭제 정책**: 매일 1회 배치로 48시간 초과 `motor_telemetry` 행 삭제. 아래 쿼리로 구현:

```sql
DELETE FROM motor_telemetry
WHERE time < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-48 hours');
```

> **이 배치는 MVP 범위 밖이다 (2026-08-10 확정).** 정식 서비스 개발 시 적용한다. MVP에서 문제가 되지 않는 이유는 데모 DB가 부팅 때 만들어지고 낡으면 통째로 재생성되기 때문이다(`02_architecture.md` §6.1, `DEMO_DATA_MAX_AGE_HOURS`) — 48시간을 넘겨 쌓이는 구간 자체가 생기지 않는다. `apscheduler` 의존성과 `RETENTION_BATCH_CRON_HOUR` 상수는 정식 서비스를 위해 남겨 둔다. 위 쿼리는 그때 쓸 설계다.

MVP 실행 방식: 별도 스케줄러(APScheduler, `02_architecture.md` §3 참고) 잡으로 1일 1회 실행. 정식 서비스 단계에서 필요 시 별도 아카이브 테이블/파일로 이관 검토.

---

승인해주시면 다음 문서(`05_ui_screens.md`) 작성을 진행하겠습니다.
