"""리포트 조립 및 제공.

06_report_spec.md §1 확정 — 파이프라인이 두 구간으로 나뉜다.

① 진단 시점: Jinja2 렌더 결과를 `motor_status_logs.report_html`(TEXT)에 저장. 순수 Python이라
   어떤 환경에서도 성공하므로 이벤트 처리 경로가 PDF 가능 여부에 의존하지 않는다.
② 리포트 요청 시점: 저장된 HTML을 WeasyPrint로 PDF 변환해 `report_pdf`(BLOB)에 캐시.
   변환이 불가한 환경(네이티브 라이브러리 미설치)에서는 저장된 HTML을 그대로 제공한다.
"""

from datetime import timedelta

from app.config import (
    DIAGNOSIS_MODEL_LABEL,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_THRESHOLDS,
    METRIC_UNITS,
    REPORT_DATE_FORMAT,
    REPORT_DATETIME_FORMAT,
    REPORT_SESSION_ID_FORMAT,
    REPORT_TIME_FORMAT,
    format_display,
    parse_utc,
)
from app.db.connection import connection_scope
from app.rag.ingest import query_sop_steps
from app.reports.generator import render_report_html, render_report_pdf
from app.services.diagnosis import build_diagnosis_text, build_notification_message

_TELEMETRY_STATUS_COLUMN = {
    "temperature": "temp_status",
    "vibration": "vib_status",
    "current": "current_status",
    "sound": "sound_status",
}

_STATUS_LABEL = {"DANGER": "위험 단계 감지", "FAULT": "고장/정지 감지"}

# 리포트 생성 대상 상태 (03_state_event_logic.md §4.1)
REPORTABLE_STATUSES = ("DANGER", "FAULT")


def _mask_phone(phone: str) -> str:
    parts = phone.split("-")
    return f"{parts[0]}-****-{parts[2]}" if len(parts) == 3 else phone


def build_report_context(conn, log) -> dict | None:
    """상태 로그 1건에 대한 리포트 렌더 컨텍스트. 필요한 참조가 없으면 None."""
    motor = conn.execute(
        "SELECT m.*, c.company_name FROM motors m "
        "JOIN companies c ON c.company_id = m.company_id WHERE m.motor_id = ?",
        (log["motor_id"],),
    ).fetchone()
    if motor is None:
        return None

    telemetry = conn.execute(
        "SELECT * FROM motor_telemetry WHERE motor_id = ? AND time = ?",
        (log["motor_id"], log["created_at"]),
    ).fetchone()
    if telemetry is None:
        return None

    contact = conn.execute(
        "SELECT contact_name, phone_number FROM company_contacts "
        "WHERE company_id = ? ORDER BY is_primary DESC, contact_id ASC LIMIT 1",
        (motor["company_id"],),
    ).fetchone()

    metric = log["metric_name"]
    status = log["new_status"]
    event_dt = parse_utc(log["created_at"])
    report_dt = event_dt + timedelta(seconds=12)

    sensors = []
    for name in METRIC_NAMES:
        _, warning, _, _ = METRIC_THRESHOLDS[name]
        metric_status = telemetry[_TELEMETRY_STATUS_COLUMN[name]]
        sensors.append(
            {
                "label": METRIC_LABELS[name],
                "value": telemetry[name],
                "unit": METRIC_UNITS[name],
                "range_text": f"≤ {warning} {METRIC_UNITS[name]}",
                "status": metric_status,
                "status_class": metric_status.lower(),
            }
        )

    recipient = "담당자 미지정"
    if contact is not None:
        recipient = f"{contact['contact_name']} ({_mask_phone(contact['phone_number'])})"

    return {
        "status": status,
        "status_class": status.lower(),
        "status_label": _STATUS_LABEL.get(status, status),
        "company_name": motor["company_name"],
        "company_id": motor["company_id"],
        "motor_id": motor["motor_id"],
        "motor_name": motor["motor_name"],
        "installation_location": motor["installation_location"],
        "model_name": motor["model_name"],
        "event_time": format_display(event_dt, REPORT_DATETIME_FORMAT),
        "generated_date": format_display(report_dt, "%Y-%m-%d"),
        "report_generated_at": format_display(report_dt, "%H:%M:%S"),
        "session_id": REPORT_SESSION_ID_FORMAT.format(
            motor_id=motor["motor_id"],
            date=format_display(event_dt, REPORT_DATE_FORMAT),
            time=format_display(event_dt, REPORT_TIME_FORMAT),
        ),
        "sensors": sensors,
        "diagnosis_model_label": DIAGNOSIS_MODEL_LABEL,
        "diagnosis_text": build_diagnosis_text(metric, telemetry[metric], status),
        "sop_steps": query_sop_steps(motor["motor_name"], metric),
        "trigger_reason": log["trigger_reason"],
        "recipient_name": recipient,
        "notification_message": build_notification_message(
            motor["motor_id"], status, log["trigger_reason"]
        ),
    }


def generate_missing_report_html(conn) -> int:
    """report_html이 비어 있는 DANGER/FAULT 로그 전건에 HTML을 생성한다.

    부팅 시 호출된다. 건당 렌더 비용이 1ms 미만이라 전건 생성해도 부담이 없다.
    """
    placeholders = ",".join("?" for _ in REPORTABLE_STATUSES)
    logs = conn.execute(
        f"SELECT * FROM motor_status_logs WHERE new_status IN ({placeholders}) "
        "AND report_html IS NULL ORDER BY created_at ASC",
        REPORTABLE_STATUSES,
    ).fetchall()

    generated = 0
    for log in logs:
        context = build_report_context(conn, log)
        if context is None:
            continue
        conn.execute(
            "UPDATE motor_status_logs SET report_html = ? WHERE log_id = ?",
            (render_report_html(context), log["log_id"]),
        )
        generated += 1
    return generated


def get_report(log_id: int) -> tuple[str, bytes | str] | None:
    """리포트를 제공한다. `("pdf", bytes)` 또는 `("html", str)`을 반환.

    05_ui_screens.md §3.3 확정 동작:
      1. report_pdf 캐시가 있으면 그대로 제공
      2. 없으면 저장된 HTML로 PDF 변환을 시도하고 성공 시 캐시
      3. 변환 불가 환경이면 HTML을 반환
    """
    with connection_scope() as conn:
        row = conn.execute(
            "SELECT report_pdf, report_html FROM motor_status_logs WHERE log_id = ?",
            (log_id,),
        ).fetchone()
        if row is None:
            return None

        if row["report_pdf"] is not None:
            return "pdf", row["report_pdf"]

        html = row["report_html"]
        if html is None:
            # 진단 시 HTML이 만들어지지 않은 예외적 경우 — 지금 만들어 저장한다.
            log = conn.execute(
                "SELECT * FROM motor_status_logs WHERE log_id = ?", (log_id,)
            ).fetchone()
            context = build_report_context(conn, log)
            if context is None:
                return None
            html = render_report_html(context)
            conn.execute(
                "UPDATE motor_status_logs SET report_html = ? WHERE log_id = ?", (html, log_id)
            )

        try:
            pdf_bytes = render_report_pdf(html)
        except Exception:
            # WeasyPrint 네이티브 라이브러리 미설치 등 — HTML로 폴백 (06 §1)
            return "html", html

        conn.execute(
            "UPDATE motor_status_logs SET report_pdf = ? WHERE log_id = ?", (pdf_bytes, log_id)
        )
        return "pdf", pdf_bytes
