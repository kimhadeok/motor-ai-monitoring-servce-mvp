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
  report_pdf      BLOB,                         -- AI 에이전트 생성 PDF 리포트 바이너리 (파일시스템 미사용, DB에 직접 저장)
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
