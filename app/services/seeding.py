"""시연용 데모 데이터 생성.

02_architecture.md §6 확정에 따라 앱 부팅 시 런타임 실행된다. 생성 시점의 현재 시각을
기준으로 최근 48시간(`DB_RETENTION_HOURS`)을 채우므로, 데이터가 노후화되지 않는다.

상태 전이 규칙은 03_state_event_logic.md를 따른다:
- 전이 감지는 (motor_id, metric_name) 단위 (§5)
- 임계선 근처 흔들림은 연속 N회 확정 조건으로 억제 (02 §2.3 핑퐁 방지)
- FAULT는 수치가 낮아져도 자동 회복하지 않음 (§4.3) — 담당자 수동 확인 필요
- 쿨다운은 로그가 아니라 에이전트/알림에만 적용 (§5)
"""

import math
import random
from datetime import datetime, timedelta, timezone

import bcrypt

from app.config import (
    COOLDOWN_HOURS,
    DEMO_ACCOUNT_PASSWORD,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_THRESHOLDS,
    NOTIFICATION_DEFAULT_CHANNELS,
    SEED_BULK_COMPANY,
    SEED_BULK_FAULT_INTERVAL_SECONDS,
    SEED_BULK_INTERVAL_SECONDS,
    SEED_BULK_MOTOR_TOTAL,
    SEED_BULK_STATUS_TARGETS,
    SEED_DENSE_WINDOW_HOURS,
    SEED_EQUIPMENT_POOL,
    SEED_LOCATION_POOL,
    SEED_MODEL_POOL,
    SEED_MOTOR_LIFESPAN_HOURS_POOL,
    SEED_OPERATION_START_DAYS_BEFORE_REGISTRATION,
    SEED_RNG_SEED,
    SEED_SPARSE_INTERVAL_SECONDS,
    SEED_TELEMETRY_HOURS,
    STATUS_LEVELS,
    STATUS_SEVERITY_RANK,
    TRANSITION_CONFIRM_SECONDS,
    TRANSITION_DEADBAND_RATIO,
)
from app.services.diagnosis import build_notification_message, build_notification_title

# (company_id, 회사명, 서비스 시작 시점 — 지금으로부터 며칠 전)
# created_at을 DB 기본값(현재 시각)에 맡기면 "총 운영 일수"(05 §3.1)가 항상 0일이 되어
# 상단 요약이 시연에서 아무것도 보여주지 못한다. 회사마다 다른 값을 준다.
_COMPANIES = [
    ("COMP-001", "(주)한국모터스", 412),
    ("COMP-002", "대한중공업(주)", 187),
]

# 로그인 ID는 `demo1`/`demo2`로 두되 **도메인은 회사에 맞춘다** (2026-08-12 고객 의견 2차 1-(1)).
# 종전에는 `@example.com`이었는데, 리포트 §5가 수신처를 표시하면서 그 문자열이 **PDF에 찍히게
# 됐다**(`dem****@example.com`). 리포트는 회의실에서 종이로 돌아가는 유일한 물건이라, 거기
# 예제 도메인이 보이면 "아직 만드는 중인 물건"으로 읽힌다. 로컬 파트를 사람 이름으로 바꾸지
# 않은 이유: 시연에서 직접 타이핑하는 로그인 ID라 짧고 외우기 쉬운 편이 낫고, 리포트에는
# 어차피 앞 3자만 남아 `dem****`로 가려진다.
_CONTACTS = [
    ("COMP-001", "김철수", "010-1234-5678", "demo1@hankuk-motors.co.kr"),
    ("COMP-002", "이영희", "010-9876-5432", "demo2@daehan-heavy.co.kr"),
]

# (motor_id, company_id, 모터명, 설치 위치, 모델명, 수집주기 초, 등록 시점 — 지금으로부터 며칠 전)
# 등록일자는 §4.1 상세 페이지에 표시된다. 소속 회사의 서비스 시작일보다 뒤여야 한다.
# 회사당 10대 — 대시보드 카드가 여러 행으로 늘어났을 때의 밀도와 조회 비용을 볼 수 있어야 한다.
_MOTORS = [
    # COMP-001 (주)한국모터스 — 제1공장 (서비스 시작 412일 전)
    ("MTR-001", "COMP-001", "2호기 메인 송풍기", "제1공장 지하 1층 기계실", "HYUN-37KW-4P", 10, 405),
    ("MTR-002", "COMP-001", "1호기 냉각펌프", "제1공장 1층 펌프실", "HYUN-15KW-4P", 20, 398),
    ("MTR-003", "COMP-001", "컨베이어 구동모터", "제1공장 생산라인 A", "HYUN-22KW-6P", 30, 233),
    ("MTR-004", "COMP-001", "급수 펌프", "제1공장 지하 1층 기계실", "HYUN-11KW-4P", 30, 390),
    ("MTR-005", "COMP-001", "배기 블로워", "제1공장 2층 공조실", "HYUN-30KW-4P", 20, 371),
    ("MTR-006", "COMP-001", "공기압축기 구동모터", "제1공장 1층 유틸리티실", "HYUN-45KW-4P", 10, 352),
    ("MTR-007", "COMP-001", "원심분리기 모터", "제1공장 생산라인 B", "HYUN-18KW-6P", 30, 288),
    ("MTR-008", "COMP-001", "도장부스 배기팬", "제1공장 3층 도장실", "HYUN-22KW-4P", 20, 205),
    ("MTR-009", "COMP-001", "냉각탑 팬모터", "제1공장 옥상", "HYUN-15KW-6P", 30, 154),
    ("MTR-010", "COMP-001", "포장기 구동모터", "제1공장 생산라인 C", "HYUN-7.5KW-4P", 30, 61),
    # COMP-002 대한중공업(주) — 제2공장 (서비스 시작 187일 전)
    ("MTR-011", "COMP-002", "3호기 배기 송풍기", "제2공장 2층 기계실", "HYUN-37KW-4P", 10, 180),
    ("MTR-012", "COMP-002", "2호기 냉각펌프", "제2공장 1층 펌프실", "HYUN-15KW-4P", 20, 180),
    ("MTR-013", "COMP-002", "포장라인 구동모터", "제2공장 생산라인 B", "HYUN-22KW-6P", 30, 96),
    ("MTR-014", "COMP-002", "크레인 권상모터", "제2공장 크레인베이", "HYUN-55KW-4P", 10, 173),
    ("MTR-015", "COMP-002", "유압유닛 모터", "제2공장 1층 유압실", "HYUN-30KW-4P", 20, 166),
    ("MTR-016", "COMP-002", "절삭유 순환펌프", "제2공장 가공라인 A", "HYUN-11KW-4P", 30, 152),
    ("MTR-017", "COMP-002", "집진기 흡입팬", "제2공장 3층 집진실", "HYUN-45KW-6P", 20, 131),
    ("MTR-018", "COMP-002", "열처리로 순환팬", "제2공장 열처리동", "HYUN-30KW-6P", 30, 110),
    ("MTR-019", "COMP-002", "컴프레서 냉각팬", "제2공장 1층 유틸리티실", "HYUN-7.5KW-4P", 30, 74),
    ("MTR-020", "COMP-002", "물류 컨베이어 모터", "제2공장 출하장", "HYUN-18KW-4P", 30, 45),
]

# 이상 시나리오. ratio는 48시간 창에서의 진행 비율(0.0=48시간 전, 1.0=현재).
# 두 회사 모두 조치 필요·주의 관찰·회복 사례를 갖도록 배치하고, FAULT와 급변(단계 스킵)을
# 각각 한 건씩 포함시킨다. 시나리오가 없는 모터는 기준값 + 소폭 노이즈로 NORMAL을 유지한다.
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
    # COMP-001 — 임펠러 불균형 의심: 진동 완만 상승, 아직 주의 단계 (WARNING 유지)
    "MTR-005": {
        "vibration": {"start": 0.60, "end": 1.00, "from": 2.0, "to": 3.2, "noise": 0.06},
    },
    # COMP-001 — 필터 막힘 의심: 온도 상승, 주의 단계 (WARNING 유지)
    "MTR-008": {
        "temperature": {"start": 0.55, "end": 1.00, "from": 55.0, "to": 68.0, "noise": 0.5},
    },
    # COMP-002 — 과부하: 전류가 정상에서 곧바로 DANGER로 급변한 뒤 FAULT 도달
    "MTR-011": {
        "current": {"start": 0.90, "end": 1.00, "from": 19.5, "to": 23.5, "noise": 0.25},
    },
    # COMP-002 — 온도 일시 상승 후 회복 (WARNING → NORMAL)
    "MTR-013": {
        "temperature": {"start": 0.30, "end": 0.42, "from": 63.0, "to": 64.5, "noise": 0.4},
    },
    # COMP-002 — 유압 펌프 캐비테이션 의심: 진동이 위험 구간까지 상승 (DANGER)
    "MTR-015": {
        "vibration": {"start": 0.70, "end": 1.00, "from": 3.0, "to": 4.6, "noise": 0.06},
    },
    # COMP-002 — 집진 덕트 저항 증가: 소음 상승, 주의 단계 (WARNING 유지)
    "MTR-017": {
        "sound": {"start": 0.65, "end": 1.00, "from": 72.0, "to": 82.0, "noise": 0.4},
    },
}

_STATUS_COLUMN = {
    "temperature": "temp_status",
    "vibration": "vib_status",
    "current": "current_status",
    "sound": "sound_status",
}


def classify(metric: str, value: float, thresholds: dict | None = None) -> str:
    """임계값 4구간 기준 상태 판정 (03_state_event_logic.md §1).

    `thresholds`는 해당 모터의 지표별 4구간(`motors.get_metric_thresholds`)이다.
    생략하면 `config.METRIC_THRESHOLDS` 기본값을 쓴다 — 시드가 데모 세계를 만들 때는
    모터별 행이 아직 없으므로 기본값이 맞다. **런타임 판정은 반드시 모터별 값을 넘긴다**
    (2026-08-11) — 설비마다 정상 범위가 다른 것이 예지보전의 전제다.
    """
    _, warning, danger, fault = (thresholds or METRIC_THRESHOLDS)[metric]
    if value >= fault:
        return "FAULT"
    if value >= danger:
        return "DANGER"
    if value >= warning:
        return "WARNING"
    return "NORMAL"


def _entry_threshold(metric: str, status: str, thresholds: dict | None = None) -> float | None:
    """해당 상태로 진입할 때 넘어야 했던 임계값. NORMAL은 진입 임계가 없다."""
    _, warning, danger, fault = (thresholds or METRIC_THRESHOLDS)[metric]
    return {"WARNING": warning, "DANGER": danger, "FAULT": fault}.get(status)


def classify_with_hysteresis(
    metric: str, value: float, confirmed: str, thresholds: dict | None = None
) -> str:
    """이력폭을 적용한 상태 판정 (02_architecture.md §2.3 핑퐁 방지).

    올라갈 때는 임계값을 그대로 쓰고, 내려올 때만 진입 임계보다 `TRANSITION_DEADBAND_RATIO`
    만큼 더 낮아지기를 요구한다. 값이 임계선 위에서 미세하게 흔들리는 동안에는 회복으로
    보지 않으므로 왕복 전이가 생기지 않는다.
    """
    observed = classify(metric, value, thresholds)
    if STATUS_SEVERITY_RANK[observed] >= STATUS_SEVERITY_RANK[confirmed]:
        return observed  # 악화 또는 유지 — 임계값 그대로

    entry = _entry_threshold(metric, confirmed, thresholds)
    if entry is not None and value > entry * (1 - TRANSITION_DEADBAND_RATIO):
        return confirmed  # 이력폭 안 — 아직 회복으로 인정하지 않는다
    return observed


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


def _seed_companies(conn, now: datetime) -> list[str]:
    conn.executemany(
        "INSERT INTO companies (company_id, company_name, created_at) VALUES (?, ?, ?)",
        [
            (company_id, name, _iso(now - timedelta(days=days_ago)))
            for company_id, name, days_ago in _COMPANIES
        ],
    )
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


def _motor_lifespan(motor_id: str, registered_at: datetime) -> tuple[int, str]:
    """설계 수명(h)과 구동일자 (2026-08-13 추가, 04 §3.3).

    **구동일자는 등록일보다 앞선다.** 설비는 모니터링 서비스를 도입하기 전부터 돌고 있었고,
    수명을 이 서비스 등록 시점부터 세면 노후 설비가 전부 새것으로 보인다.

    난수를 `motor_id`로 시드해 같은 모터에는 늘 같은 값이 나오게 한다 — 시연 중 재시드로
    "137호기 수명"이 달라지면 앞서 말한 숫자와 어긋난다.
    """
    rng = random.Random(f"lifespan|{motor_id}")
    low, high = SEED_OPERATION_START_DAYS_BEFORE_REGISTRATION
    started = registered_at - timedelta(days=rng.randint(low, high))
    return rng.choice(SEED_MOTOR_LIFESPAN_HOURS_POOL), _iso(started)


def _seed_motors(conn, now: datetime, motor_rows: list[tuple]) -> list[dict]:
    motors = []
    for motor_id, company_id, name, location, model, interval, days_ago in motor_rows:
        registered_at = now - timedelta(days=days_ago)
        lifespan_hours, operation_started_at = _motor_lifespan(motor_id, registered_at)
        conn.execute(
            "INSERT INTO motors (motor_id, company_id, motor_name, installation_location, "
            "model_name, serial_number, collection_interval_seconds, "
            "lifespan_hours, operation_started_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                motor_id,
                company_id,
                name,
                location,
                model,
                f"SN-{motor_id}",
                interval,
                lifespan_hours,
                operation_started_at,
                _iso(registered_at),
            ),
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
                "lifespan_hours": lifespan_hours,
                "operation_started_at": operation_started_at,
            }
        )
    return motors


def _baseline(metric: str, rng: random.Random) -> float:
    """평상시 기준값 — WARNING 임계의 70% 이하로 잡아 노이즈만으로는 전이가 생기지 않게 한다."""
    normal, warning, _, _ = METRIC_THRESHOLDS[metric]
    return round(rng.uniform(normal, warning * 0.7), 1)


def _metric_value(
    motor_id: str,
    metric: str,
    ratio: float,
    baseline: float,
    rng: random.Random,
    scenarios: dict[str, dict[str, dict]],
) -> float:
    """해당 시점의 지표값. 시나리오 구간이면 램프값, 아니면 기준값 + 소폭 노이즈."""
    scenario = scenarios.get(motor_id, {}).get(metric)
    if scenario and scenario["start"] <= ratio <= scenario["end"]:
        span = scenario["end"] - scenario["start"]
        progress = (ratio - scenario["start"]) / span if span else 1.0
        value = scenario["from"] + progress * (scenario["to"] - scenario["from"])
        value += rng.uniform(-scenario["noise"], scenario["noise"])
    else:
        noise = 0.1 if metric == "vibration" else 0.5
        value = baseline + rng.uniform(-noise, noise)
    return round(max(value, 0.0), 2)


def _generate_series(
    motor: dict, now: datetime, rng: random.Random, scenarios: dict[str, dict[str, dict]]
) -> tuple[list[tuple], list[dict]]:
    """텔레메트리 행과 확정된 상태 전이를 한 번의 패스로 생성한다.

    **걷는 것과 저장하는 것을 분리한다** (2026-08-11, remaining_work #12). 루프는 원래
    수집 주기 그대로 48시간을 걷는다 — 이력폭 판정과 확정 샘플 수가 그 촘촘함에 의존하므로
    걸음을 성기게 하면 전이 이력 자체가 달라진다. 대신 저장은 세 가지만 한다:

      ① 최근 `SEED_DENSE_WINDOW_HOURS` 안의 모든 행 (화면이 보는 구간)
      ② **전이가 확정된 시각의 행과 그 직전 행** — 이벤트 목록의 "값 변화"가
         `time = created_at`으로 정확히 조인하고 직전 행을 서브쿼리로 가져온다
         (`services/events.py`). 리포트도 같은 시각의 행이 없으면 아예 생성되지 않는다
         (`reports/service.py`). 이 두 행이 빠지면 화면이 조용히 비어버린다.
      ③ 그 밖의 구간은 `SEED_SPARSE_INTERVAL_SECONDS` 간격으로 솎아낸 행
    """
    interval = motor["collection_interval_seconds"]
    window_start = now - timedelta(hours=SEED_TELEMETRY_HOURS)
    dense_start = now - timedelta(hours=SEED_DENSE_WINDOW_HOURS)
    total_seconds = (now - window_start).total_seconds()
    baselines = {metric: _baseline(metric, rng) for metric in METRIC_NAMES}
    # 확정에 필요한 연속 샘플 수 = 확정 시간 / 수집 주기 (주기가 달라도 같은 시간이 걸린다)
    confirm_samples = max(math.ceil(TRANSITION_CONFIRM_SECONDS / interval), 1)

    rows: list[tuple] = []
    transitions: list[dict] = []
    confirmed = {metric: "NORMAL" for metric in METRIC_NAMES}
    pending = {metric: None for metric in METRIC_NAMES}
    pending_count = {metric: 0 for metric in METRIC_NAMES}

    previous_row: tuple | None = None  # 직전 샘플의 행 (담겼는지와 무관)
    previous_kept = False
    last_sparse_at: datetime | None = None

    current_time = window_start
    while current_time <= now:
        ratio = (current_time - window_start).total_seconds() / total_seconds
        timestamp = _iso(current_time)

        values = {
            m: _metric_value(motor["motor_id"], m, ratio, baselines[m], rng, scenarios)
            for m in METRIC_NAMES
        }
        statuses = {m: classify(m, values[m]) for m in METRIC_NAMES}

        row = (
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
        transitioned = False

        for metric in METRIC_NAMES:
            # 이력폭을 적용해 판정한다 — 임계선 근처의 미세한 흔들림을 회복으로 보지 않는다.
            observed = classify_with_hysteresis(metric, values[metric], confirmed[metric])
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

            if pending_count[metric] >= confirm_samples:
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
                transitioned = True
                confirmed[metric] = observed
                pending[metric] = None
                pending_count[metric] = 0

        in_dense = current_time >= dense_start
        due_sparse = (
            last_sparse_at is None
            or (current_time - last_sparse_at).total_seconds() >= SEED_SPARSE_INTERVAL_SECONDS
        )
        keep = in_dense or transitioned or due_sparse

        if keep:
            # 전이 행만 담고 직전 행을 빠뜨리면 이벤트 목록의 "값 변화"가 한쪽만 남는다.
            if transitioned and previous_row is not None and not previous_kept:
                rows.append(previous_row)
            rows.append(row)
            if not in_dense and due_sparse:
                last_sparse_at = current_time

        previous_row, previous_kept = row, keep
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
        title = build_notification_title(motor["motor_id"], transition["new_status"])
        # **한 번의 알림은 채널마다 한 행이다** (2026-08-12). 문자가 기본이고 이메일이
        # 함께 나간다(`NOTIFICATION_DEFAULT_CHANNELS`). 종전에는 세 채널 중 하나를 무작위로
        # 골라 한 행만 넣었는데, 그러면 리포트 §5가 "이메일로만 통보했다"고 적어 실제 발송
        # 방식과 어긋났다. 같은 `created_at`을 공유해야 리포트가 이 쌍을 한 이벤트로 묶는다.
        for channel in NOTIFICATION_DEFAULT_CHANNELS:
            conn.execute(
                "INSERT INTO notification_logs (motor_id, contact_id, channel_type, title, "
                "message_content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    motor["motor_id"],
                    contact["contact_id"],
                    channel,
                    title,
                    message,
                    transition["created_at"],
                ),
            )
            count += 1
        transition["notified"] = True

    return count


def _seed_login_logs(conn, contacts: list[dict], now: datetime) -> None:
    for contact in contacts:
        conn.execute(
            "INSERT INTO login_logs (contact_id, ip_address, created_at) VALUES (?, ?, ?)",
            (contact["contact_id"], "127.0.0.1", _iso(now - timedelta(days=1))),
        )


def _build_target_scenario(metric: str, target: str, rng: random.Random) -> dict[str, dict]:
    """지정 지표를 목표 상태까지 최근 절반 구간에서 완만히 램프시키는 시나리오.

    벌크 모터는 수집 주기가 300초라 확정 표본이 1개(ceil(300/300))다. 램프가 임계를
    넘는 순간 전이가 확정되므로, from(확실한 NORMAL) → to(목표 상태 대역)로 올리면
    NORMAL→WARNING(→DANGER→FAULT) 전이가 차례로 로그에 남는다.
    """
    _, warning, danger, fault = METRIC_THRESHOLDS[metric]
    from_val = round(warning * 0.5, 2)  # 시작은 확실히 NORMAL
    if target == "WARNING":
        to_val = warning + 0.45 * (danger - warning)
    elif target == "DANGER":
        to_val = danger + 0.45 * (fault - danger)
    else:  # FAULT
        to_val = fault + 0.15 * (fault - danger)
    noise = max((danger - warning) * 0.03, 0.02)
    return {
        metric: {
            "start": 0.5,
            "end": 1.0,
            "from": from_val,
            "to": round(to_val, 2),
            "noise": round(noise, 3),
        }
    }


def _build_bulk_motor_rows(
    rng: random.Random,
) -> tuple[list[tuple], dict[str, dict[str, dict]]]:
    """SEED_BULK_COMPANY를 목표 총 대수까지 채우는 추가 모터 행과 시나리오 (재정리안 200대).

    기존 큐레이션 모터는 그대로 두고 부족분만 생성한다. 전용 rng를 받아 큐레이션 모터의
    텔레메트리 난수열은 건드리지 않는다(기존 대시보드 데모 불변).
    """
    curated = sum(1 for m in _MOTORS if m[1] == SEED_BULK_COMPANY)
    needed = max(SEED_BULK_MOTOR_TOTAL - curated, 0)
    if needed == 0:
        return [], {}

    # 목표 상태 배정: 지정 분포만큼 이상 상태, 나머지는 NORMAL. 섞어 목록 전반에 분포시킨다.
    targets: list[str] = []
    for status, count in SEED_BULK_STATUS_TARGETS.items():
        targets.extend([status] * count)
    targets += ["NORMAL"] * max(needed - len(targets), 0)
    targets = targets[:needed]
    rng.shuffle(targets)

    rows: list[tuple] = []
    scenarios: dict[str, dict[str, dict]] = {}
    for i, target in enumerate(targets):
        motor_id = f"MTR-{101 + i:03d}"  # 큐레이션(MTR-001~020)과 겹치지 않는 대역
        equipment = SEED_EQUIPMENT_POOL[i % len(SEED_EQUIPMENT_POOL)]
        name = f"{i + 11}호기 {equipment}"
        location = SEED_LOCATION_POOL[i % len(SEED_LOCATION_POOL)]
        model = rng.choice(SEED_MODEL_POOL)
        days_ago = rng.randint(30, 400)  # 회사 서비스 시작(412일 전)보다 뒤
        # FAULT 모터는 대시보드 카드 첫 줄을 차지한다(심각도 순 배치). 그 줄이 자동 갱신에
        # 맞춰 움직여야 시연에서 실시간을 한자리에서 보여줄 수 있다 — config 주석 참조.
        interval = (
            SEED_BULK_FAULT_INTERVAL_SECONDS
            if target == "FAULT"
            else SEED_BULK_INTERVAL_SECONDS
        )
        rows.append((motor_id, SEED_BULK_COMPANY, name, location, model, interval, days_ago))
        if target != "NORMAL":
            metric = rng.choice(METRIC_NAMES)
            scenarios[motor_id] = _build_target_scenario(metric, target, rng)
    return rows, scenarios


def seed_demo_data(conn) -> dict:
    """데모 데이터 전체를 생성하고 요약을 반환한다. 호출측에서 commit한다."""
    rng = random.Random(SEED_RNG_SEED)
    bulk_rng = random.Random(SEED_RNG_SEED + 1)  # 벌크 모터 속성 생성용 — 큐레이션 난수열과 분리
    now = datetime.now(timezone.utc)

    _seed_companies(conn, now)
    contacts = _seed_contacts(conn)
    contacts_by_company = {c["company_id"]: c for c in contacts}

    bulk_rows, bulk_scenarios = _build_bulk_motor_rows(bulk_rng)
    motor_rows = list(_MOTORS) + bulk_rows
    scenarios = {**_SCENARIOS, **bulk_scenarios}
    motors = _seed_motors(conn, now, motor_rows)

    telemetry_count = 0
    all_transitions: list[dict] = []
    for motor in motors:
        rows, transitions = _generate_series(motor, now, rng, scenarios)
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
