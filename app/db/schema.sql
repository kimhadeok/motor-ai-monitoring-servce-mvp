-- .claude/docs/generated/04_database_schema.md 기준 DDL 전문
-- (report_pdf BLOB 반영본, 2026-08-04 확정)

CREATE TABLE IF NOT EXISTS companies (
  company_id   TEXT PRIMARY KEY,               -- 예: COMP-001
  company_name TEXT NOT NULL,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS company_contacts (
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

CREATE TABLE IF NOT EXISTS motors (
  motor_id               TEXT PRIMARY KEY,      -- 예: MTR-001
  company_id             TEXT NOT NULL REFERENCES companies(company_id),
  motor_name             TEXT NOT NULL,
  installation_location  TEXT NOT NULL,
  model_name             TEXT NOT NULL,
  serial_number          TEXT UNIQUE,
  collection_interval_seconds INTEGER NOT NULL DEFAULT 20,  -- 10/20/30초
  -- 수명 관리 (2026-08-13 추가, 04 §3.3). 두 값이 한 쌍으로 쓰인다 —
  -- 구동일자부터 지금까지의 가동시간을 설계 수명과 견줘 잔여 수명을 본다.
  -- created_at(모니터링 서비스 등록일)과 operation_started_at(실제 가동 시작일)은 다르다.
  -- 설비는 서비스 도입 전부터 돌고 있으므로 구동일자가 등록일보다 앞선다.
  -- NULL을 허용한다 — 관리자 화면에서 입력할 수 있게 되기 전에 등록된 모터와
  -- 마이그레이션으로 컬럼만 붙은 기존 행이 있다. 읽는 쪽이 NULL을 전제한다(04 §3.3).
  lifespan_hours         INTEGER,               -- 설계 수명(시간)
  operation_started_at   TEXT,                  -- ISO8601, 실제 가동 시작일
  created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
  -- normal_range 등 임계값 4종은 motor_thresholds 테이블로 분리
);

CREATE TABLE IF NOT EXISTS motor_thresholds (
  motor_id      TEXT NOT NULL REFERENCES motors(motor_id),
  metric_name   TEXT NOT NULL CHECK (metric_name IN ('temperature','vibration','current','sound')),
  normal_range  REAL,   -- normal_range <= 값 < warning_range
  warning_range REAL,   -- warning_range <= 값 < danger_range
  danger_range  REAL,   -- danger_range <= 값 < fault_range
  fault_range   REAL,   -- 값 >= fault_range
  PRIMARY KEY (motor_id, metric_name)
);

CREATE TABLE IF NOT EXISTS motor_telemetry (
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

CREATE INDEX IF NOT EXISTS idx_motor_telemetry_motor_time ON motor_telemetry (motor_id, time DESC);

CREATE TABLE IF NOT EXISTS motor_status_logs (
  log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  motor_id        TEXT NOT NULL REFERENCES motors(motor_id),
  metric_name     TEXT NOT NULL CHECK (
                    metric_name IN ('temperature','vibration','current','sound','connectivity')
                  ),
  previous_status TEXT NOT NULL,                -- NORMAL/WARNING/DANGER/FAULT (connectivity는 OK/NO_DATA)
  new_status      TEXT NOT NULL,
  trigger_reason  TEXT,                         -- 예: "진동 임계치 초과", "급변(단계 스킵)", "센서 점검 권장"
  report_html     TEXT,                         -- 리포트 HTML 원문. 진단 시 항상 생성 (Jinja2는 순수 Python이라 환경 무관 성공)
  report_pdf      BLOB,                         -- 리포트 PDF 바이너리. 요청 시 생성 후 캐시 (WeasyPrint 불가 환경에선 NULL 유지)
  contact_id      INTEGER REFERENCES company_contacts(contact_id),  -- 관리자 수동 조치자(정비완료 확인 등)
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_motor_status_logs_lookup ON motor_status_logs (motor_id, metric_name, created_at DESC);

CREATE TABLE IF NOT EXISTS login_logs (
  log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  contact_id  INTEGER REFERENCES company_contacts(contact_id),  -- 실패 시 NULL 허용
  ip_address  TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS notification_logs (
  notification_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  motor_id             TEXT NOT NULL REFERENCES motors(motor_id),
  contact_id           INTEGER NOT NULL REFERENCES company_contacts(contact_id),
  channel_type         TEXT NOT NULL CHECK (channel_type IN ('KAKAO_ALIMTALK','SMS','EMAIL')),
  external_message_id  TEXT,
  title                TEXT,
  message_content      TEXT NOT NULL,
  created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- 임계값 변경 이력 (2026-08-11 추가, 04 §3.9).
-- 임계값을 바꾸면 **그 시점 이후 수집분부터** 새 기준으로 판정된다(과거 판정·리포트는 불변).
-- 그래서 "이 전이는 어느 기준으로 판정된 것인가"를 나중에 답하려면 변경 시점 기록이 필요하다.
-- 사고 조사에서 "그때 기준은 무엇이었나"에 답하지 못하면 리포트를 근거로 쓸 수 없다.
CREATE TABLE IF NOT EXISTS motor_threshold_history (
  history_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  motor_id          TEXT NOT NULL REFERENCES motors(motor_id),
  metric_name       TEXT NOT NULL CHECK (
                      metric_name IN ('temperature','vibration','current','sound')
                    ),
  -- 바꾸기 직전 값. 최초 등록분은 NULL이 아니라 기본값이 들어간다(관리자 화면에서만 기록).
  previous_normal   REAL,
  previous_warning  REAL,
  previous_danger   REAL,
  previous_fault    REAL,
  normal_range      REAL,
  warning_range     REAL,
  danger_range      REAL,
  fault_range       REAL,
  contact_id        INTEGER REFERENCES company_contacts(contact_id),  -- 담당자 삭제 시 NULL
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_motor_threshold_history_lookup
  ON motor_threshold_history (motor_id, created_at DESC);

-- 참조 지식(고장 모드 ↔ 지표 매핑)은 여기 두지 않는다. 시간에 무관한 정적 데이터라
-- data/knowledge/fault_modes.json에 커밋하고 app/rag/knowledge.py가 직접 읽는다.
-- 런타임 테이블과 조인할 일이 없어 DB에 넣으면 부팅 시드 비용만 붙는다 (2026-08-07 확정).
