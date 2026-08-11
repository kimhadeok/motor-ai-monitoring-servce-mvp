"""관리자 페이지의 기본 테이블 CRUD (05_ui_screens.md §6).

대상은 **시간에 무관한 기본 테이블 4종**이다 — 회사 / 담당자 / 모터 / 지표 임계값.
텔레메트리·상태로그·알림 같은 시계열은 시드와 런타임 틱이 만들며 여기서 건드리지 않는다.

**입력한 데이터는 재시드로 사라진다** (2026-08-11 범위 확정). 부팅 시 최신 텔레메트리가
`DEMO_DATA_MAX_AGE_HOURS`(2시간)보다 오래되면 `bootstrap`이 DB 파일을 통째로 지우고 다시
만들기 때문이다(`02 §6.1`). 시연용 MVP라 이 동작을 유지하기로 했고, 대신 화면이 그 사실을
직접 알린다. 정식 서비스에서는 기본 테이블을 보존하도록 부트스트랩을 나눠야 한다.

**삭제는 연쇄 삭제다.** `PRAGMA foreign_keys = ON`(`db/connection.py`)이라 참조가 남아 있으면
삭제가 실패한다. 모터를 지우면 그 모터의 텔레메트리·상태로그·알림·임계값을 함께 지운다.
담당자도 마찬가지인데, `notification_logs.contact_id`는 **NOT NULL**이라 알림 행을 지워야만
담당자를 지울 수 있다.

모든 조회·변경은 `company_id`로 범위를 좁힌다. 로그인한 담당자가 다른 회사의 데이터를
보거나 고치면 안 된다(테넌트 경계).
"""

import sqlite3

import bcrypt

from app.config import (
    ALLOWED_COLLECTION_INTERVALS_SECONDS,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_THRESHOLDS,
)


class AdminError(Exception):
    """입력값이 규칙에 맞지 않을 때. 메시지를 그대로 화면에 보여준다."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AdminError(message)


# --- 회사 ------------------------------------------------------------------


def get_company(conn, company_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM companies WHERE company_id = ?", (company_id,)
    ).fetchone()


def update_company(conn, company_id: str, company_name: str) -> None:
    """회사명만 고친다.

    회사 추가·삭제는 두지 않는다. 로그인 담당자는 자기 회사만 볼 수 있으므로 회사를 추가해도
    화면에 나타나지 않고, 자기 회사를 지우면 로그인 자체가 성립하지 않는다.
    """
    name = company_name.strip()
    _require(bool(name), "회사명을 입력해 주세요.")
    conn.execute(
        "UPDATE companies SET company_name = ? WHERE company_id = ?", (name, company_id)
    )


# --- 담당자 ----------------------------------------------------------------


def list_contacts(conn, company_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM company_contacts WHERE company_id = ? ORDER BY contact_id",
        (company_id,),
    ).fetchall()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _validate_contact(name: str, phone: str, email: str) -> tuple[str, str, str]:
    name, phone, email = name.strip(), phone.strip(), email.strip()
    _require(bool(name), "담당자명을 입력해 주세요.")
    _require(bool(phone), "연락처를 입력해 주세요.")
    _require("@" in email, "이메일 형식이 아닙니다.")
    return name, phone, email


def create_contact(
    conn,
    company_id: str,
    contact_name: str,
    phone_number: str,
    email: str,
    password: str,
    is_primary: bool,
) -> None:
    name, phone, mail = _validate_contact(contact_name, phone_number, email)
    _require(bool(password), "비밀번호를 입력해 주세요.")
    try:
        conn.execute(
            "INSERT INTO company_contacts (company_id, contact_name, phone_number, "
            "email, password_hash, is_primary) VALUES (?, ?, ?, ?, ?, ?)",
            (company_id, name, phone, mail, _hash_password(password), int(is_primary)),
        )
    except sqlite3.IntegrityError as exc:
        # email이 UNIQUE다. 다른 회사 담당자와도 겹칠 수 있어 목록만으로는 미리 막을 수 없다.
        raise AdminError(f"이미 등록된 이메일입니다: {mail}") from exc


def update_contact(
    conn,
    company_id: str,
    contact_id: int,
    contact_name: str,
    phone_number: str,
    email: str,
    is_primary: bool,
    password: str | None = None,
) -> None:
    """담당자 정보 수정. `password`가 비어 있지 않을 때만 비밀번호를 바꾼다."""
    name, phone, mail = _validate_contact(contact_name, phone_number, email)
    try:
        conn.execute(
            "UPDATE company_contacts SET contact_name = ?, phone_number = ?, email = ?, "
            "is_primary = ? WHERE contact_id = ? AND company_id = ?",
            (name, phone, mail, int(is_primary), contact_id, company_id),
        )
        if password:
            conn.execute(
                "UPDATE company_contacts SET password_hash = ? "
                "WHERE contact_id = ? AND company_id = ?",
                (_hash_password(password), contact_id, company_id),
            )
    except sqlite3.IntegrityError as exc:
        raise AdminError(f"이미 등록된 이메일입니다: {mail}") from exc


def delete_contact(conn, company_id: str, contact_id: int, current_contact_id: int) -> None:
    """담당자 삭제. 참조하는 알림·로그를 함께 지운다.

    두 가지는 막는다.
    - **본인 삭제**: 지우는 순간 로그인 상태가 존재하지 않는 담당자를 가리키게 된다.
    - **마지막 담당자 삭제**: 그 회사로 로그인할 방법이 사라진다.
    """
    _require(contact_id != current_contact_id, "로그인 중인 본인은 삭제할 수 없습니다.")
    remaining = conn.execute(
        "SELECT COUNT(*) FROM company_contacts WHERE company_id = ?", (company_id,)
    ).fetchone()[0]
    _require(remaining > 1, "회사의 마지막 담당자는 삭제할 수 없습니다.")

    # notification_logs.contact_id는 NOT NULL이라 행을 지워야 담당자를 지울 수 있다.
    conn.execute("DELETE FROM notification_logs WHERE contact_id = ?", (contact_id,))
    # 아래 둘은 NULL 허용이라 참조만 끊는다 — 조치 이력 자체는 남겨 둔다.
    conn.execute(
        "UPDATE motor_status_logs SET contact_id = NULL WHERE contact_id = ?", (contact_id,)
    )
    conn.execute("UPDATE login_logs SET contact_id = NULL WHERE contact_id = ?", (contact_id,))
    conn.execute(
        "DELETE FROM company_contacts WHERE contact_id = ? AND company_id = ?",
        (contact_id, company_id),
    )


# --- 모터 ------------------------------------------------------------------


def list_motors(conn, company_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM motors WHERE company_id = ? ORDER BY motor_id", (company_id,)
    ).fetchall()


def _validate_motor(
    motor_id: str, name: str, location: str, model: str, interval: int
) -> tuple[str, str, str, str]:
    motor_id, name = motor_id.strip(), name.strip()
    location, model = location.strip(), model.strip()
    _require(bool(motor_id), "모터 ID를 입력해 주세요.")
    _require(bool(name), "모터명을 입력해 주세요.")
    _require(bool(location), "설치 위치를 입력해 주세요.")
    _require(bool(model), "모델명을 입력해 주세요.")
    _require(
        interval in ALLOWED_COLLECTION_INTERVALS_SECONDS,
        f"수집 주기는 {', '.join(str(s) for s in ALLOWED_COLLECTION_INTERVALS_SECONDS)}초 중 "
        "하나여야 합니다 (02 §2.1).",
    )
    return motor_id, name, location, model


def create_motor(
    conn,
    company_id: str,
    motor_id: str,
    motor_name: str,
    installation_location: str,
    model_name: str,
    serial_number: str,
    collection_interval_seconds: int,
) -> None:
    """모터 등록. 지표 임계값 4행을 기본값으로 함께 만든다.

    임계값이 없으면 모터 상세의 임계값 표가 비고, 리포트의 임계값 참고표도 빈칸이 된다.
    기본값은 시드와 같은 `config.METRIC_THRESHOLDS`를 쓴다 — 화면마다 다른 기준이 보이면 안 된다.

    **새 모터에는 계측값이 없다.** 시드는 부팅 때 한 번만 돌고, 런타임 틱은 마지막 행이 있는
    모터만 이어 붙인다(`services/runtime_tick.py`). 대시보드 카드에 "수집된 계측값이
    없습니다"로 나오는 것이 정상이며, 화면이 이 사실을 미리 알린다.
    """
    mid, name, location, model = _validate_motor(
        motor_id, motor_name, installation_location, model_name, collection_interval_seconds
    )
    serial = serial_number.strip() or None
    try:
        conn.execute(
            "INSERT INTO motors (motor_id, company_id, motor_name, installation_location, "
            "model_name, serial_number, collection_interval_seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mid, company_id, name, location, model, serial, collection_interval_seconds),
        )
    except sqlite3.IntegrityError as exc:
        raise AdminError(f"이미 있는 모터 ID이거나 시리얼 번호입니다: {mid} / {serial}") from exc

    for metric in METRIC_NAMES:
        normal, warning, danger, fault = METRIC_THRESHOLDS[metric]
        conn.execute(
            "INSERT INTO motor_thresholds (motor_id, metric_name, normal_range, "
            "warning_range, danger_range, fault_range) VALUES (?, ?, ?, ?, ?, ?)",
            (mid, metric, normal, warning, danger, fault),
        )


def update_motor(
    conn,
    company_id: str,
    motor_id: str,
    motor_name: str,
    installation_location: str,
    model_name: str,
    serial_number: str,
    collection_interval_seconds: int,
) -> None:
    """모터 정보 수정. `motor_id`는 바꾸지 않는다 — 텔레메트리 수만 행이 이 값을 참조한다."""
    _, name, location, model = _validate_motor(
        motor_id, motor_name, installation_location, model_name, collection_interval_seconds
    )
    serial = serial_number.strip() or None
    try:
        conn.execute(
            "UPDATE motors SET motor_name = ?, installation_location = ?, model_name = ?, "
            "serial_number = ?, collection_interval_seconds = ? "
            "WHERE motor_id = ? AND company_id = ?",
            (name, location, model, serial, collection_interval_seconds, motor_id, company_id),
        )
    except sqlite3.IntegrityError as exc:
        raise AdminError(f"이미 쓰이는 시리얼 번호입니다: {serial}") from exc


def count_motor_references(conn, motor_id: str) -> dict[str, int]:
    """모터를 지울 때 함께 사라질 행 수. 확인 창에서 그대로 보여준다."""
    def _count(sql: str) -> int:
        return conn.execute(sql, (motor_id,)).fetchone()[0]

    return {
        "telemetry": _count("SELECT COUNT(*) FROM motor_telemetry WHERE motor_id = ?"),
        "status_logs": _count("SELECT COUNT(*) FROM motor_status_logs WHERE motor_id = ?"),
        "notifications": _count("SELECT COUNT(*) FROM notification_logs WHERE motor_id = ?"),
    }


def delete_motor(conn, company_id: str, motor_id: str) -> None:
    """모터 삭제. 참조하는 시계열·로그·알림·임계값을 함께 지운다.

    `PRAGMA foreign_keys = ON`이라 순서가 중요하다 — 자식 행을 먼저 지워야 한다.
    """
    _require(
        conn.execute(
            "SELECT 1 FROM motors WHERE motor_id = ? AND company_id = ?", (motor_id, company_id)
        ).fetchone()
        is not None,
        "해당 모터를 찾을 수 없습니다.",
    )
    conn.execute("DELETE FROM notification_logs WHERE motor_id = ?", (motor_id,))
    conn.execute("DELETE FROM motor_status_logs WHERE motor_id = ?", (motor_id,))
    conn.execute("DELETE FROM motor_telemetry WHERE motor_id = ?", (motor_id,))
    conn.execute("DELETE FROM motor_thresholds WHERE motor_id = ?", (motor_id,))
    conn.execute(
        "DELETE FROM motors WHERE motor_id = ? AND company_id = ?", (motor_id, company_id)
    )


# --- 지표 임계값 -----------------------------------------------------------


def list_thresholds(conn, company_id: str, motor_id: str) -> list[dict]:
    """모터의 지표별 임계값 4행. 화면 표시 순서는 `METRIC_NAMES`로 고정한다."""
    rows = {
        r["metric_name"]: r
        for r in conn.execute(
            "SELECT t.* FROM motor_thresholds t JOIN motors m ON m.motor_id = t.motor_id "
            "WHERE t.motor_id = ? AND m.company_id = ?",
            (motor_id, company_id),
        ).fetchall()
    }
    result = []
    for metric in METRIC_NAMES:
        row = rows.get(metric)
        default = METRIC_THRESHOLDS[metric]
        result.append(
            {
                "metric_name": metric,
                "label": METRIC_LABELS.get(metric, metric),
                "normal_range": row["normal_range"] if row else default[0],
                "warning_range": row["warning_range"] if row else default[1],
                "danger_range": row["danger_range"] if row else default[2],
                "fault_range": row["fault_range"] if row else default[3],
            }
        )
    return result


def update_thresholds(conn, company_id: str, motor_id: str, rows: list[dict]) -> None:
    """지표별 임계값 저장. 네 구간이 오름차순이어야 한다.

    순서가 뒤집히면 상태 판정(`normal <= 값 < warning <= ...`)이 성립하지 않아, 화면이
    조용히 잘못된 상태를 보여주게 된다. 저장 전에 막는다.
    """
    _require(
        conn.execute(
            "SELECT 1 FROM motors WHERE motor_id = ? AND company_id = ?", (motor_id, company_id)
        ).fetchone()
        is not None,
        "해당 모터를 찾을 수 없습니다.",
    )
    for row in rows:
        label = row.get("label", row["metric_name"])
        values = [
            row["normal_range"],
            row["warning_range"],
            row["danger_range"],
            row["fault_range"],
        ]
        _require(all(v is not None for v in values), f"{label}: 빈 값이 있습니다.")
        _require(
            all(a < b for a, b in zip(values, values[1:])),
            f"{label}: 정상 < 경고 < 위험 < 고장 순으로 커져야 합니다.",
        )

    for row in rows:
        conn.execute(
            "INSERT INTO motor_thresholds (motor_id, metric_name, normal_range, "
            "warning_range, danger_range, fault_range) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(motor_id, metric_name) DO UPDATE SET "
            "normal_range = excluded.normal_range, warning_range = excluded.warning_range, "
            "danger_range = excluded.danger_range, fault_range = excluded.fault_range",
            (
                motor_id,
                row["metric_name"],
                row["normal_range"],
                row["warning_range"],
                row["danger_range"],
                row["fault_range"],
            ),
        )
