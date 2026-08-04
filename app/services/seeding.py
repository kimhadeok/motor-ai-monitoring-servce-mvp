"""시연용 데모 데이터 생성.

02_architecture.md §6 확정에 따라 앱 부팅 시 런타임 실행된다. 생성 시점의 현재 시각을
기준으로 최근 48시간(`DB_RETENTION_HOURS`)을 채우므로, 데이터가 노후화되지 않는다.

상태 전이 규칙은 03_state_event_logic.md를 따른다:
- 전이 감지는 (motor_id, metric_name) 단위 (§5)
- 임계선 근처 흔들림은 연속 N회 확정 조건으로 억제 (02 §2.3 핑퐁 방지)
- FAULT는 수치가 낮아져도 자동 회복하지 않음 (§4.3) — 담당자 수동 확인 필요
- 쿨다운은 로그가 아니라 에이전트/알림에만 적용 (§5)
"""

import random
from datetime import datetime, timedelta, timezone

import bcrypt

from app.config import (
    COOLDOWN_HOURS,
    DEMO_ACCOUNT_PASSWORD,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_THRESHOLDS,
    NOTIFICATION_CHANNELS,
    SEED_RNG_SEED,
    SEED_TELEMETRY_HOURS,
    STATUS_LEVELS,
    STATUS_SEVERITY_RANK,
    TRANSITION_CONFIRM_SAMPLES,
)
from app.services.diagnosis import build_notification_message, build_notification_title

_COMPANIES = [
    ("COMP-001", "(주)한국모터스"),
    ("COMP-002", "대한중공업(주)"),
]

_CONTACTS = [
    ("COMP-001", "김철수", "010-1234-5678", "demo1@example.com"),
    ("COMP-002", "이영희", "010-9876-5432", "demo2@example.com"),
]

# (motor_id, company_id, 모터명, 설치 위치, 모델명, 수집주기 초)
_MOTORS = [
    ("MTR-001", "COMP-001", "2호기 메인 송풍기", "제1공장 지하 1층 기계실", "HYUN-37KW-4P", 10),
    ("MTR-002", "COMP-001", "1호기 냉각펌프", "제1공장 1층 펌프실", "HYUN-15KW-4P", 20),
    ("MTR-003", "COMP-001", "컨베이어 구동모터", "제1공장 생산라인 A", "HYUN-22KW-6P", 30),
    ("MTR-004", "COMP-002", "3호기 배기 송풍기", "제2공장 2층 기계실", "HYUN-37KW-4P", 10),
    ("MTR-005", "COMP-002", "2호기 냉각펌프", "제2공장 1층 펌프실", "HYUN-15KW-4P", 20),
    ("MTR-006", "COMP-002", "포장라인 구동모터", "제2공장 생산라인 B", "HYUN-22KW-6P", 30),
]

# 이상 시나리오. ratio는 48시간 창에서의 진행 비율(0.0=48시간 전, 1.0=현재).
# 두 회사 모두 이벤트가 발생하도록 배치하고, FAULT·급변(단계 스킵)·회복을 각각 포함시킨다.
_SCENARIOS: dict[str, dict[str, dict]] = {
    # COMP-001 — 베어링 윤활 부족: 온도·진동 동반 완만 상승 (NORMAL→WARNING→DANGER, 단계적 악화)
    "MTR-001": {
        "temperature": {"start": 0.75, "end": 1.00, "from": 58.0, "to": 82.0, "noise": 0.5},
        "vibration": {"start": 0.75, "end": 1.00, "from": 2.1, "to": 3.7, "noise": 0.05},
    },
    # COMP-001 — 소음 일시 상승 후 회복 (WARNING → NORMAL)
    "MTR-003": {
        "sound": {"start": 0.45, "end": 0.56, "from": 78.0, "to": 79.5, "noise": 0.4},
    },
    # COMP-002 — 과부하: 전류가 정상에서 곧바로 DANGER로 급변한 뒤 FAULT 도달
    "MTR-004": {
        "current": {"start": 0.90, "end": 1.00, "from": 19.5, "to": 23.5, "noise": 0.25},
    },
    # COMP-002 — 온도 일시 상승 후 회복 (WARNING → NORMAL)
    "MTR-006": {
        "temperature": {"start": 0.30, "end": 0.42, "from": 63.0, "to": 64.5, "noise": 0.4},
    },
}

_STATUS_COLUMN = {
    "temperature": "temp_status",
    "vibration": "vib_status",
    "current": "current_status",
    "sound": "sound_status",
}


def classify(metric: str, value: float) -> str:
    """임계값 4구간 기준 상태 판정 (03_state_event_logic.md §1)."""
    _, warning, danger, fault = METRIC_THRESHOLDS[metric]
    if value >= fault:
        return "FAULT"
    if value >= danger:
        return "DANGER"
    if value >= warning:
        return "WARNING"
    return "NORMAL"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _transition_reason(metric: str, previous: str, new: str) -> str:
    """03_state_event_logic.md §4.2 케이스별 trigger_reason."""
    previous_rank = STATUS_SEVERITY_RANK[previous]
    new_rank = STATUS_SEVERITY_RANK[new]

    if new_rank > previous_rank:
        if new_rank - previous_rank > 1:
            return "급변(단계 스킵)"
        return f"{METRIC_LABELS[metric]} 임계치 초과"
    if previous_rank - new_rank > 1:
        return "스킵 회복 — 센서 점검 권장"
    return "회복"


def _seed_companies(conn) -> list[str]:
    conn.executemany("INSERT INTO companies (company_id, company_name) VALUES (?, ?)", _COMPANIES)
    return [c[0] for c in _COMPANIES]


def _seed_contacts(conn) -> list[dict]:
    password_hash = bcrypt.hashpw(DEMO_ACCOUNT_PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )
    created = []
    for company_id, name, phone, email in _CONTACTS:
        cursor = conn.execute(
            "INSERT INTO company_contacts "
            "(company_id, contact_name, phone_number, email, password_hash, is_primary, allowed_ip) "
            "VALUES (?, ?, ?, ?, ?, 1, NULL)",
            (company_id, name, phone, email, password_hash),
        )
        created.append(
            {
                "contact_id": cursor.lastrowid,
                "company_id": company_id,
                "contact_name": name,
                "phone_number": phone,
                "email": email,
            }
        )
    return created


def _seed_motors(conn) -> list[dict]:
    motors = []
    for motor_id, company_id, name, location, model, interval in _MOTORS:
        conn.execute(
            "INSERT INTO motors (motor_id, company_id, motor_name, installation_location, "
            "model_name, serial_number, collection_interval_seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (motor_id, company_id, name, location, model, f"SN-{motor_id}", interval),
        )
        for metric in METRIC_NAMES:
            normal, warning, danger, fault = METRIC_THRESHOLDS[metric]
            conn.execute(
                "INSERT INTO motor_thresholds (motor_id, metric_name, normal_range, "
                "warning_range, danger_range, fault_range) VALUES (?, ?, ?, ?, ?, ?)",
                (motor_id, metric, normal, warning, danger, fault),
            )
        motors.append(
            {
                "motor_id": motor_id,
                "company_id": company_id,
                "motor_name": name,
                "installation_location": location,
                "model_name": model,
                "collection_interval_seconds": interval,
            }
        )
    return motors


def _baseline(metric: str, rng: random.Random) -> float:
    """평상시 기준값 — WARNING 임계의 70% 이하로 잡아 노이즈만으로는 전이가 생기지 않게 한다."""
    normal, warning, _, _ = METRIC_THRESHOLDS[metric]
    return round(rng.uniform(normal, warning * 0.7), 1)


def _metric_value(motor_id: str, metric: str, ratio: float, baseline: float, rng: random.Random) -> float:
    """해당 시점의 지표값. 시나리오 구간이면 램프값, 아니면 기준값 + 소폭 노이즈."""
    scenario = _SCENARIOS.get(motor_id, {}).get(metric)
    if scenario and scenario["start"] <= ratio <= scenario["end"]:
        span = scenario["end"] - scenario["start"]
        progress = (ratio - scenario["start"]) / span if span else 1.0
        value = scenario["from"] + progress * (scenario["to"] - scenario["from"])
        value += rng.uniform(-scenario["noise"], scenario["noise"])
    else:
        noise = 0.1 if metric == "vibration" else 0.5
        value = baseline + rng.uniform(-noise, noise)
    return round(max(value, 0.0), 2)


def _generate_series(motor: dict, now: datetime, rng: random.Random) -> tuple[list[tuple], list[dict]]:
    """텔레메트리 행과 확정된 상태 전이를 한 번의 패스로 생성한다."""
    interval = motor["collection_interval_seconds"]
    window_start = now - timedelta(hours=SEED_TELEMETRY_HOURS)
    total_seconds = (now - window_start).total_seconds()
    baselines = {metric: _baseline(metric, rng) for metric in METRIC_NAMES}

    rows: list[tuple] = []
    transitions: list[dict] = []
    confirmed = {metric: "NORMAL" for metric in METRIC_NAMES}
    pending = {metric: None for metric in METRIC_NAMES}
    pending_count = {metric: 0 for metric in METRIC_NAMES}

    current_time = window_start
    while current_time <= now:
        ratio = (current_time - window_start).total_seconds() / total_seconds
        timestamp = _iso(current_time)

        values = {m: _metric_value(motor["motor_id"], m, ratio, baselines[m], rng) for m in METRIC_NAMES}
        statuses = {m: classify(m, values[m]) for m in METRIC_NAMES}

        rows.append(
            (
                timestamp,
                motor["motor_id"],
                motor["company_id"],
                values["temperature"],
                statuses["temperature"],
                values["vibration"],
                statuses["vibration"],
                values["current"],
                statuses["current"],
                values["sound"],
                statuses["sound"],
            )
        )

        for metric in METRIC_NAMES:
            observed = statuses[metric]
            if observed == confirmed[metric]:
                pending[metric] = None
                pending_count[metric] = 0
                continue

            # FAULT는 수치가 낮아져도 자동 회복하지 않는다 (03 §4.3 — 담당자 수동 확인 필요)
            if confirmed[metric] == "FAULT" and STATUS_SEVERITY_RANK[observed] < 3:
                continue

            if observed == pending[metric]:
                pending_count[metric] += 1
            else:
                pending[metric] = observed
                pending_count[metric] = 1

            if pending_count[metric] >= TRANSITION_CONFIRM_SAMPLES:
                transitions.append(
                    {
                        "motor": motor,
                        "metric_name": metric,
                        "previous_status": confirmed[metric],
                        "new_status": observed,
                        "trigger_reason": _transition_reason(metric, confirmed[metric], observed),
                        "created_at": timestamp,
                        "value": values[metric],
                    }
                )
                confirmed[metric] = observed
                pending[metric] = None
                pending_count[metric] = 0

        current_time += timedelta(seconds=interval)

    return rows, transitions


def _insert_telemetry(conn, rows: list[tuple]) -> None:
    conn.executemany(
        "INSERT INTO motor_telemetry (time, motor_id, company_id, temperature, temp_status, "
        "vibration, vib_status, current, current_status, sound, sound_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def _insert_transitions(conn, transitions: list[dict]) -> None:
    """전이는 쿨다운과 무관하게 전건 적재한다 (03 §5 — 로그는 트렌드 데이터라 손실 방지)."""
    for transition in transitions:
        cursor = conn.execute(
            "INSERT INTO motor_status_logs (motor_id, metric_name, previous_status, "
            "new_status, trigger_reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                transition["motor"]["motor_id"],
                transition["metric_name"],
                transition["previous_status"],
                transition["new_status"],
                transition["trigger_reason"],
                transition["created_at"],
            ),
        )
        transition["log_id"] = cursor.lastrowid


def _seed_notifications(conn, transitions: list[dict], contacts_by_company: dict, rng: random.Random) -> int:
    """DANGER/FAULT 전이에 알림을 발행하되 (motor_id, metric_name) 단위 쿨다운을 적용한다.

    03_state_event_logic.md §5 확정: 쿨다운 중에는 에이전트 재가동과 알림 발송만 차단하고
    로그는 계속 적재한다. 따라서 쿨다운은 이 함수에만 걸린다.
    """
    cooldown = timedelta(hours=COOLDOWN_HOURS)
    last_fired: dict[tuple[str, str], datetime] = {}
    count = 0

    for transition in sorted(transitions, key=lambda t: t["created_at"]):
        if transition["new_status"] not in ("DANGER", "FAULT"):
            continue

        motor = transition["motor"]
        key = (motor["motor_id"], transition["metric_name"])
        event_time = datetime.strptime(transition["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )

        previous = last_fired.get(key)
        if previous is not None and event_time - previous < cooldown:
            transition["cooldown_blocked"] = True
            continue
        last_fired[key] = event_time

        contact = contacts_by_company[motor["company_id"]]
        message = build_notification_message(
            motor["motor_id"], transition["new_status"], transition["trigger_reason"]
        )
        conn.execute(
            "INSERT INTO notification_logs (motor_id, contact_id, channel_type, title, "
            "message_content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                motor["motor_id"],
                contact["contact_id"],
                rng.choice(NOTIFICATION_CHANNELS),
                build_notification_title(motor["motor_id"], transition["new_status"]),
                message,
                transition["created_at"],
            ),
        )
        transition["notified"] = True
        count += 1

    return count


def _seed_login_logs(conn, contacts: list[dict], now: datetime) -> None:
    for contact in contacts:
        conn.execute(
            "INSERT INTO login_logs (contact_id, ip_address, created_at) VALUES (?, ?, ?)",
            (contact["contact_id"], "127.0.0.1", _iso(now - timedelta(days=1))),
        )


def seed_demo_data(conn) -> dict:
    """데모 데이터 전체를 생성하고 요약을 반환한다. 호출측에서 commit한다."""
    rng = random.Random(SEED_RNG_SEED)
    now = datetime.now(timezone.utc)

    _seed_companies(conn)
    contacts = _seed_contacts(conn)
    contacts_by_company = {c["company_id"]: c for c in contacts}
    motors = _seed_motors(conn)

    telemetry_count = 0
    all_transitions: list[dict] = []
    for motor in motors:
        rows, transitions = _generate_series(motor, now, rng)
        _insert_telemetry(conn, rows)
        telemetry_count += len(rows)
        all_transitions.extend(transitions)

    all_transitions.sort(key=lambda t: t["created_at"])
    _insert_transitions(conn, all_transitions)
    notification_count = _seed_notifications(conn, all_transitions, contacts_by_company, rng)
    _seed_login_logs(conn, contacts, now)

    return {
        "companies": len(_COMPANIES),
        "contacts": len(contacts),
        "motors": len(motors),
        "telemetry": telemetry_count,
        "status_logs": len(all_transitions),
        "notifications": notification_count,
        "demo_password": DEMO_ACCOUNT_PASSWORD,
        "demo_emails": [c["email"] for c in contacts],
    }
