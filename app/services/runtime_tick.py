"""런타임 틱 — 마지막 저장 시각 이후의 텔레메트리를 이어 붙인다 (05 §5-2, 2026-08-11).

**왜 필요한가.** 데모 시드는 실행 시각까지만 데이터를 채운다(02 §6.1). 그래서
`st.fragment(run_every=...)`로 자동 갱신만 붙이면 화면은 10초마다 다시 그려지지만 보이는
숫자는 그대로다 — 담당자 눈에는 아무 일도 일어나지 않는다. 틱이 경과분을 채워야 수치와
그래프가 실제로 움직인다.

**무엇을 하지 않는가.** 틱은 **상태를 바꾸지 않고 상태 로그도 남기지 않는다.**
수집→판정→전이(remaining_work #2-1)는 MVP 범위 밖으로 확정됐다(2026-08-11). 그런데 값만
자유롭게 흔들면 임계를 넘는 순간 카드 색이 바뀌는데 이벤트 목록에는 아무 기록이 없는
어긋난 화면이 된다. 대표 상태는 최신 텔레메트리 행의 지표별 상태에서 나오기 때문이다
(`services/motors.py`). 그래서 값은 **자기가 속한 상태 구간 안에서만** 흔들린다.

**구간은 저장된 status가 아니라 값을 현재 임계로 다시 분류해서 정한다** (2026-08-11).
저장된 status를 기준 삼으면 관리자가 임계값을 바꿨을 때 값을 옛 상태의 구간으로 끌어당겨
설정 변경을 무력화한다. 값이 스스로 속한 구간에서 흔들리게 하면, 임계값을 바꾼 **다음
수집부터** 새 기준의 상태가 저장된다 — 과거 판정은 건드리지 않는다(05 §6.3).

**여러 탭이 동시에 돌 때.** Streamlit은 세션마다 스크립트를 실행하므로 탭이 둘이면 틱도
둘이다. 같은 (시각, 모터)에 대해 같은 값이 나오도록 난수를 `(motor_id, timestamp)`로
시드하고, 삽입은 `INSERT OR IGNORE`(PK `(time, motor_id)`)로 중복을 흡수한다.

**한계.** 값은 구간 안에서 무작위 보행이라 앱을 아주 오래 띄워두면 구간 안에서 서서히
치우칠 수 있다. 구간 밖으로는 나가지 않으므로 상태·색·집계는 영향을 받지 않는다.
"""

import random
from datetime import datetime, timedelta, timezone

from app.config import (
    METRIC_NAMES,
    RUNTIME_TICK_BAND_MARGIN_RATIO,
    RUNTIME_TICK_ENABLED,
    RUNTIME_TICK_FAULT_HEADROOM,
    RUNTIME_TICK_MAX_STEPS_PER_MOTOR,
    RUNTIME_TICK_NOISE_RATIO,
    parse_utc,
)

from app.services.motors import get_metric_thresholds

# `_iso`는 시드와 **같은 시각 포맷**을 써야 한다. 밀리초 3자리 고정이라
# config.DB_DATETIME_FORMAT의 strftime(마이크로초 6자리)과 다르고, 문자열 비교로 정렬·조인하는
# 컬럼이라 어긋나면 안 된다. `classify`는 판정 규칙이 시드와 런타임에서 한 벌이어야 해서 공유한다.
from app.services.seeding import _iso, classify


def _status_band(metric: str, status: str, thresholds: dict) -> tuple[float, float]:
    """해당 상태가 유지되는 값 구간 [하한, 상한). `classify()`의 역함수다."""
    normal, warning, danger, fault = thresholds[metric]
    if status == "FAULT":
        # 상한이 없는 구간이라 관측 가능한 폭을 준다 — 값이 무한정 오르면 안 된다.
        return fault, fault * RUNTIME_TICK_FAULT_HEADROOM
    if status == "DANGER":
        return danger, fault
    if status == "WARNING":
        return warning, danger
    return normal, warning


def _next_value(
    metric: str, value: float, status: str, rng: random.Random, thresholds: dict
) -> float:
    """구간 안에서 한 걸음. 구간을 벗어나지 않으므로 상태 판정이 바뀌지 않는다."""
    low, high = _status_band(metric, status, thresholds)
    span = high - low
    margin = span * RUNTIME_TICK_BAND_MARGIN_RATIO
    stepped = value + rng.uniform(-span * RUNTIME_TICK_NOISE_RATIO, span * RUNTIME_TICK_NOISE_RATIO)
    return round(min(max(stepped, low + margin), high - margin), 2)


def _due_timestamps(last_time: datetime, interval: int, now: datetime) -> list[datetime]:
    """마지막 저장 시각 이후 채워야 할 수집 시각들. 상한을 넘으면 최근 것만 남긴다."""
    if interval <= 0:
        return []
    elapsed = (now - last_time).total_seconds()
    steps = int(elapsed // interval)
    if steps <= 0:
        return []
    if steps > RUNTIME_TICK_MAX_STEPS_PER_MOTOR:
        # 밀린 구간을 전부 채우면 화면이 멈춘다. 앞은 비우고 최근 구간만 채운다.
        first = steps - RUNTIME_TICK_MAX_STEPS_PER_MOTOR + 1
    else:
        first = 1
    return [last_time + timedelta(seconds=interval * n) for n in range(first, steps + 1)]


def run_tick(conn, company_id: str) -> int:
    """`company_id` 소속 모터의 텔레메트리를 현재 시각까지 이어 붙인다. 삽입한 행 수를 반환.

    호출측에서 commit한다(`connection_scope()`가 담당). 상태 로그·알림은 만들지 않는다.
    """
    if not RUNTIME_TICK_ENABLED:
        return 0

    now = datetime.now(timezone.utc)
    motors = conn.execute(
        "SELECT motor_id, company_id, collection_interval_seconds FROM motors "
        "WHERE company_id = ? ORDER BY motor_id",
        (company_id,),
    ).fetchall()

    rows: list[tuple] = []
    for motor in motors:
        motor_id = motor["motor_id"]
        # 최신 행은 인덱스(motor_id, time DESC) 점조회 — 윈도우 함수보다 싸다는 실측 근거는
        # `services/motors.py list_company_motor_status()` docstring 참조.
        last = conn.execute(
            "SELECT * FROM motor_telemetry WHERE motor_id = ? ORDER BY time DESC LIMIT 1",
            (motor_id,),
        ).fetchone()
        if last is None:
            continue  # 시드가 아직 없는 모터 — 틱이 데이터를 새로 만들지는 않는다

        last_time = parse_utc(last["time"])
        values = {metric: last[metric] for metric in METRIC_NAMES}
        thresholds = get_metric_thresholds(conn, motor_id)

        # **저장된 status가 아니라 값을 현재 임계로 다시 분류해서 구간을 정한다** (2026-08-11).
        # 저장된 status를 기준 삼으면, 관리자가 임계값을 바꿨을 때 값을 옛 상태의 구간 안으로
        # 끌어당겨 낡은 판정을 억지로 유지시킨다 — 데이터를 조작해 설정 변경을 무력화하는
        # 셈이다. 값이 스스로 속한 구간에서 흔들리게 하면, 임계값을 바꾼 **다음 수집부터**
        # 새 기준의 상태가 저장된다(05 §6.3 확정: 과거 판정은 불변, 앞으로만 적용).
        statuses = {
            metric: classify(metric, values[metric], thresholds) for metric in METRIC_NAMES
        }

        for stamp in _due_timestamps(last_time, motor["collection_interval_seconds"], now):
            timestamp = _iso(stamp)
            # 탭이 여럿이어도 같은 (모터, 시각)에는 같은 값이 나오도록 시드를 고정한다.
            rng = random.Random(f"{motor_id}|{timestamp}")
            values = {
                metric: _next_value(metric, values[metric], statuses[metric], rng, thresholds)
                for metric in METRIC_NAMES
            }
            rows.append(
                (
                    timestamp,
                    motor_id,
                    motor["company_id"],
                    *[
                        item
                        for metric in METRIC_NAMES
                        for item in (values[metric], statuses[metric])
                    ],
                )
            )

    if not rows:
        return 0

    conn.executemany(
        "INSERT OR IGNORE INTO motor_telemetry "
        "(time, motor_id, company_id, temperature, temp_status, vibration, vib_status, "
        "current, current_status, sound, sound_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)
