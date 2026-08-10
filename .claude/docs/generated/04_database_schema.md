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

MVP 실행 방식: 별도 스케줄러(APScheduler, `02_architecture.md` §3 참고) 잡으로 1일 1회 실행. 정식 서비스 단계에서 필요 시 별도 아카이브 테이블/파일로 이관 검토.

---

승인해주시면 다음 문서(`05_ui_screens.md`) 작성을 진행하겠습니다.
