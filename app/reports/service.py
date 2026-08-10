"""리포트 조립 및 제공.

06_report_spec.md §1 확정 — 파이프라인이 두 구간으로 나뉜다.

① 진단 시점: Jinja2 렌더 결과를 `motor_status_logs.report_html`(TEXT)에 저장. 순수 Python이라
   어떤 환경에서도 성공하므로 이벤트 처리 경로가 PDF 가능 여부에 의존하지 않는다.
② 리포트 요청 시점: 저장된 HTML을 WeasyPrint로 PDF 변환해 `report_pdf`(BLOB)에 캐시.
   변환이 불가한 환경(네이티브 라이브러리 미설치)에서는 저장된 HTML을 그대로 제공한다.
"""

from datetime import timedelta

from app.agents.diagnosis_agent import run_diagnosis
from app.agents.schema import DiagnosisContext
from app.config import (
    DIAGNOSIS_FALLBACK_MODEL_LABEL,
    DIAGNOSIS_MODEL_LABEL,
    METRIC_LABELS,
    METRIC_NAMES,
    METRIC_STATUS_COLUMNS,
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
from app.rag.knowledge import lookup_fault_modes
from app.reports.generator import render_report_html, render_report_pdf
from app.services.diagnosis import (
    build_diagnosis_facts,
    build_notification_message,
)
from app.services.motors import get_thresholds

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
        metric_status = telemetry[METRIC_STATUS_COLUMNS[name]]
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

    # 근거를 먼저 측정하고 문장은 그 근거만 서술한다 (services/diagnosis.py 모듈 주석 참조).
    facts = build_diagnosis_facts(
        conn, motor["motor_id"], metric, status, log["created_at"], telemetry
    )

    # 참조 지식 기반 결정적 조회 — 벡터 검색과 달리 같은 지표면 항상 같은 근거가 나온다.
    # 리포트의 "의심 고장 모드" 섹션과 진단 에이전트 입력이 **같은 목록**을 봐야 한다.
    # 각자 조회하면 조회 시점·상한이 달라져 본문과 근거가 어긋날 수 있다.
    suspected_faults = lookup_fault_modes(metric)

    # 진단 에이전트 (app/agents/diagnosis_agent.py). LLM이 불가한 환경에서는 내부에서
    # 규칙 기반으로 폴백하므로 여기서 예외를 걱정하지 않아도 된다.
    diagnosis = run_diagnosis(
        DiagnosisContext(
            motor_id=motor["motor_id"],
            motor_name=motor["motor_name"],
            model_name=motor["model_name"],
            installation_location=motor["installation_location"],
            status=status,
            trigger_reason=log["trigger_reason"],
            facts=facts,
            suspected_faults=suspected_faults,
        )
    )

    # 임계값은 모터마다 다르므로 리포트에 참고표로 싣는다 — 센서 카드의 "정상 기준" 한 줄로는
    # 이 값이 어느 구간에 속하는지, FAULT까지 얼마나 남았는지 알 수 없다 (06 §2.2).
    thresholds = [
        {
            "label": METRIC_LABELS.get(t["metric_name"], t["metric_name"]),
            "unit": METRIC_UNITS.get(t["metric_name"], ""),
            "normal": f"< {t['warning_range']:g}",
            "warning": f"{t['warning_range']:g} ~ {t['danger_range']:g}",
            "danger": f"{t['danger_range']:g} ~ {t['fault_range']:g}",
            "fault": f"≥ {t['fault_range']:g}",
            # 이번 이벤트를 일으킨 지표를 표에서도 짚어준다
            "is_trigger": t["metric_name"] == metric,
        }
        for t in get_thresholds(conn, motor["motor_id"])
    ]

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
        "thresholds": thresholds,
        # 생성 경로와 표기를 일치시킨다 (2026-08-10 확정). 호출하지 않은 모델명을 적으면
        # 담당자가 폴백 결과를 LLM 생성물로 오독한다.
        "diagnosis_model_label": (
            DIAGNOSIS_MODEL_LABEL if diagnosis.source == "llm" else DIAGNOSIS_FALLBACK_MODEL_LABEL
        ),
        "diagnosis_summary": diagnosis.summary,
        "diagnosis_cause": diagnosis.cause,
        "diagnosis_chained_effects": diagnosis.chained_effects,
        "diagnosis_if_ignored": diagnosis.if_ignored,
        "trend_windows": [w for w in (facts["short_term"], facts["long_term"]) if w],
        "companion_metrics": facts["companions"],
        "metric_characteristic": facts["characteristic"],
        "suspected_faults": suspected_faults,
        "sop_steps": query_sop_steps(motor["motor_name"], metric),
        "trigger_reason": log["trigger_reason"],
        "recipient_name": recipient,
        "notification_message": build_notification_message(
            motor["motor_id"], status, log["trigger_reason"]
        ),
    }


def _missing_report_logs(conn) -> list:
    """report_html이 아직 없는 DANGER/FAULT 상태 로그."""
    placeholders = ",".join("?" for _ in REPORTABLE_STATUSES)
    return conn.execute(
        f"SELECT * FROM motor_status_logs WHERE new_status IN ({placeholders}) "
        "AND report_html IS NULL ORDER BY created_at ASC",
        REPORTABLE_STATUSES,
    ).fetchall()


def count_missing_reports(conn) -> int:
    """전건 생성 대상 건수. 호출측이 예상 소요를 미리 알릴 때 쓴다."""
    return len(_missing_report_logs(conn))


def generate_missing_report_html(conn) -> int:
    """report_html이 비어 있는 DANGER/FAULT 로그 전건에 HTML을 생성한다.

    **부팅 경로에서는 호출하지 않는다** (2026-08-07 확정). Jinja2 렌더 자체는 건당 1ms
    미만이지만, `build_report_context()`가 호출하는 `query_sop_steps()`가 건당 약 0.3초의
    임베딩 API 왕복을 유발한다. 전건 생성 시 이 왕복이 로그 수만큼 반복돼 콜드 스타트를
    지배했다. 지금은 `get_report()`가 최초 열람 시 만들어 저장한다.

    진단 에이전트가 붙은 뒤(2026-08-10) 건당 비용이 **약 4초**로 올랐다 — SOP 임베딩
    0.3초에 gpt-4o 구조화 출력 3.7초(실측)가 더해진다. 호출측이 건수와 예상 소요를
    안내할 수 있도록 대상 건수는 이 함수가 아니라 `count_missing_reports()`로 먼저 센다.

    `scripts/seed_data.py --with-reports`에서 로컬 전수 확인용으로만 쓴다.
    """
    logs = _missing_report_logs(conn)

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


def get_report(log_id: int) -> dict | None:
    """리포트를 제공한다. `{"html": str, "pdf": bytes | None}`.

    **HTML은 항상 돌려준다** (2026-08-10 변경). 종전에는 PDF가 있으면 PDF만 반환해
    화면이 다운로드 버튼 하나로 끝났다 — 담당자가 내려받기 전에는 내용을 볼 수 없었다.
    지금은 화면에 항상 HTML을 띄우고, 내려받기만 PDF/HTML 중 가능한 쪽으로 준다
    (05_ui_screens.md §3.3).

    동작 순서:
      1. 저장된 HTML이 없으면 지금 만들어 저장 (최초 열람 경로)
      2. `report_pdf` 캐시가 있으면 그대로 사용
      3. 없으면 PDF 변환을 시도하고 성공 시 캐시. 변환 불가 환경이면 `pdf=None`
    """
    with connection_scope() as conn:
        row = conn.execute(
            "SELECT report_pdf, report_html FROM motor_status_logs WHERE log_id = ?",
            (log_id,),
        ).fetchone()
        if row is None:
            return None

        html = row["report_html"]
        if html is None:
            # 최초 열람 — 여기서 진단 에이전트가 돌고 HTML이 만들어진다.
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

        if row["report_pdf"] is not None:
            return {"html": html, "pdf": row["report_pdf"]}

        try:
            pdf_bytes = render_report_pdf(html)
        except Exception:
            # WeasyPrint 네이티브 라이브러리 미설치 등 — HTML만 제공한다 (06 §1)
            return {"html": html, "pdf": None}

        conn.execute(
            "UPDATE motor_status_logs SET report_pdf = ? WHERE log_id = ?", (pdf_bytes, log_id)
        )
        return {"html": html, "pdf": pdf_bytes}
