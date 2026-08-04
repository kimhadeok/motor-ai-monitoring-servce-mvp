"""1회성 로컬 시딩 스크립트.

Streamlit Community Cloud는 재배포/재시작 시 로컬 파일시스템이 초기화될 수 있어,
런타임 관리자 페이지 대신 배포 전 로컬에서 이 스크립트를 1회 실행해 시연용 데이터
(SQLite DB, ChromaDB persist 디렉터리, PDF 바이너리)를 만들고 그 결과물을 git에
커밋하는 방식을 사용한다 (2026-08-04 확정, .claude/docs/plan/2026-08-04_project-scaffolding.md 참고).

실행: uv run python scripts/seed_data.py
완료 후: git add data/app.db data/chroma/ && git commit -m "..."
"""

import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import (  # noqa: E402
    DB_PATH,
    METRIC_NAMES,
    RAG_SOURCES_DIR,
    REPORT_SESSION_ID_FORMAT,
    STATUS_LEVELS,
)
from app.db.connection import get_connection  # noqa: E402
from app.db.init_db import ensure_schema  # noqa: E402
from app.rag.chroma_client import get_chroma_client  # noqa: E402
from app.reports.generator import render_report_pdf  # noqa: E402

RNG = random.Random(20260804)

METRIC_LABELS = {"temperature": "온도", "vibration": "진동", "current": "전류", "sound": "소음"}
METRIC_UNITS = {"temperature": "°C", "vibration": "mm/s", "current": "A", "sound": "dB"}

# metric별 임계값: normal_range(기준 하한/참고값), warning_range, danger_range, fault_range
THRESHOLDS = {
    "temperature": (20.0, 60.0, 75.0, 90.0),
    "vibration": (0.0, 2.5, 4.0, 6.0),
    "current": (0.0, 15.0, 18.0, 22.0),
    "sound": (40.0, 75.0, 85.0, 95.0),
}


def classify(metric: str, value: float) -> str:
    _, warning, danger, fault = THRESHOLDS[metric]
    if value >= fault:
        return "FAULT"
    if value >= danger:
        return "DANGER"
    if value >= warning:
        return "WARNING"
    return "NORMAL"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def kst_str(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return (dt + timedelta(hours=9)).strftime(fmt)


def mask_phone(phone: str) -> str:
    parts = phone.split("-")
    if len(parts) == 3:
        return f"{parts[0]}-****-{parts[2]}"
    return phone


def reset_database() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    ensure_schema()
    print(f"[1/9] 스키마 초기화 완료: {DB_PATH}")


def seed_companies(conn) -> list[str]:
    companies = [
        ("COMP-001", "(주)한국모터스"),
        ("COMP-002", "대한중공업(주)"),
    ]
    conn.executemany(
        "INSERT INTO companies (company_id, company_name) VALUES (?, ?)", companies
    )
    print(f"[2/9] companies 시드 완료: {len(companies)}건")
    return [c[0] for c in companies]


def seed_contacts(conn, company_ids: list[str]) -> list[dict]:
    demo_password = "demo1234!"
    password_hash = bcrypt.hashpw(demo_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    contacts = [
        (company_ids[0], "김철수", "010-1234-5678", "demo1@example.com", password_hash, 1, None),
        (company_ids[1], "이영희", "010-9876-5432", "demo2@example.com", password_hash, 1, None),
    ]
    created = []
    for company_id, name, phone, email, pw_hash, is_primary, allowed_ip in contacts:
        cur = conn.execute(
            "INSERT INTO company_contacts "
            "(company_id, contact_name, phone_number, email, password_hash, is_primary, allowed_ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (company_id, name, phone, email, pw_hash, is_primary, allowed_ip),
        )
        created.append(
            {
                "contact_id": cur.lastrowid,
                "company_id": company_id,
                "contact_name": name,
                "phone_number": phone,
                "email": email,
            }
        )
    print(f"[2/9] company_contacts 시드 완료: {len(created)}건")
    print(f"       데모 로그인 계정 (전체 공통 비밀번호: {demo_password}):")
    for c in created:
        print(f"         - {c['email']} ({c['contact_name']}, {c['company_id']})")
    return created


def seed_motors(conn, company_ids: list[str]) -> list[dict]:
    motor_specs = [
        ("2호기 메인 송풍기", "제1공장 지하 1층 기계실", "HYUN-37KW-4P"),
        ("1호기 냉각펌프", "제1공장 1층 펌프실", "HYUN-15KW-4P"),
        ("컨베이어 구동모터", "제2공장 생산라인 A", "HYUN-22KW-6P"),
    ]
    motors = []
    seq = 1
    for company_id in company_ids:
        for name, location, model in motor_specs:
            motor_id = f"MTR-{seq:03d}"
            interval = RNG.choice((10, 20, 30))
            conn.execute(
                "INSERT INTO motors "
                "(motor_id, company_id, motor_name, installation_location, model_name, "
                "serial_number, collection_interval_seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (motor_id, company_id, name, location, model, f"SN-{motor_id}", interval),
            )
            for metric in METRIC_NAMES:
                normal, warning, danger, fault = THRESHOLDS[metric]
                conn.execute(
                    "INSERT INTO motor_thresholds "
                    "(motor_id, metric_name, normal_range, warning_range, danger_range, fault_range) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
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
            seq += 1
    print(f"[3/9] motors + motor_thresholds 시드 완료: {len(motors)}개 모터")
    return motors


def baseline_value(metric: str) -> float:
    normal, warning, _, _ = THRESHOLDS[metric]
    return round(RNG.uniform(normal, warning * 0.7), 1)


def generate_telemetry(conn, motors: list[dict]) -> None:
    """최근 6시간(장기 트렌드 윈도우) 데이터를 생성. 목록의 첫 번째 모터는
    베어링 윤활 부족 시나리오(온도+진동 동반 완만 상승, past_incident_sample.txt와 동일 패턴)로
    WARNING -> DANGER 전이가 관측되도록 이상치 구간을 삽입한다.
    """
    now = utc_now()
    window_start = now - timedelta(hours=6)

    for idx, motor in enumerate(motors):
        interval = motor["collection_interval_seconds"]
        is_scenario_motor = idx == 0
        baselines = {m: baseline_value(m) for m in METRIC_NAMES}

        t = window_start
        rows = []
        while t <= now:
            elapsed_ratio = (t - window_start).total_seconds() / (now - window_start).total_seconds()
            values = {}
            for metric in METRIC_NAMES:
                noise = RNG.uniform(-0.5, 0.5) if metric != "vibration" else RNG.uniform(-0.1, 0.1)
                value = baselines[metric] + noise

                if is_scenario_motor and metric in ("temperature", "vibration") and elapsed_ratio > 0.5:
                    # 마지막 3시간 동안 온도/진동이 함께 완만히 상승 (WARNING -> DANGER)
                    ramp = (elapsed_ratio - 0.5) / 0.5  # 0.0 ~ 1.0
                    if metric == "temperature":
                        value = 58.0 + ramp * 24.0 + RNG.uniform(-1.0, 1.0)  # 58 -> 82
                    else:
                        value = 2.1 + ramp * 1.6 + RNG.uniform(-0.05, 0.05)  # 2.1 -> 3.7

                value = round(max(value, 0.0), 2)
                values[metric] = value

            status = {m: classify(m, values[m]) for m in METRIC_NAMES}
            rows.append(
                (
                    iso(t),
                    motor["motor_id"],
                    motor["company_id"],
                    values["temperature"],
                    status["temperature"],
                    values["vibration"],
                    status["vibration"],
                    values["current"],
                    status["current"],
                    values["sound"],
                    status["sound"],
                )
            )
            t += timedelta(seconds=interval)

        conn.executemany(
            "INSERT INTO motor_telemetry "
            "(time, motor_id, company_id, temperature, temp_status, vibration, vib_status, "
            "current, current_status, sound, sound_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    print(f"[4/9] motor_telemetry 시드 완료: {len(motors)}개 모터 x 최근 6시간")


def scan_transitions_and_log(conn, motors: list[dict]) -> list[dict]:
    """motor_telemetry를 시간순으로 스캔해 상태 전이 지점마다 motor_status_logs 행 생성."""
    created_logs = []
    for motor in motors:
        rows = conn.execute(
            "SELECT time, temp_status, vib_status, current_status, sound_status "
            "FROM motor_telemetry WHERE motor_id = ? ORDER BY time ASC",
            (motor["motor_id"],),
        ).fetchall()

        status_col = {
            "temperature": "temp_status",
            "vibration": "vib_status",
            "current": "current_status",
            "sound": "sound_status",
        }
        previous = {m: "NORMAL" for m in METRIC_NAMES}

        for row in rows:
            for metric in METRIC_NAMES:
                current_status = row[status_col[metric]]
                if current_status == previous[metric]:
                    continue

                prev_rank = STATUS_LEVELS.index(previous[metric])
                new_rank = STATUS_LEVELS.index(current_status)
                if new_rank - prev_rank > 1:
                    reason = "급변(단계 스킵)"
                elif new_rank < prev_rank:
                    reason = "회복"
                else:
                    reason = f"{METRIC_LABELS[metric]} 임계치 초과"

                cur = conn.execute(
                    "INSERT INTO motor_status_logs "
                    "(motor_id, metric_name, previous_status, new_status, trigger_reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (motor["motor_id"], metric, previous[metric], current_status, reason, row["time"]),
                )
                created_logs.append(
                    {
                        "log_id": cur.lastrowid,
                        "motor": motor,
                        "metric_name": metric,
                        "previous_status": previous[metric],
                        "new_status": current_status,
                        "trigger_reason": reason,
                        "created_at": row["time"],
                    }
                )
                previous[metric] = current_status

    print(f"[5/9] motor_status_logs 시드 완료: {len(created_logs)}건 (상태 전이 이벤트)")
    return created_logs


def ingest_rag_sources() -> None:
    """data/rag_sources/*.txt를 문단 단위로 청크 분할 후 ChromaDB에 인제스트.

    스캐폴딩 단계에서는 API 키 없이도 시드 스크립트가 완결되도록 ChromaDB 기본
    로컬 임베딩 함수(all-MiniLM-L6-v2, onnx)를 사용한다. 실제 서비스 단계에서
    OpenAI 임베딩으로 교체할 경우 app/rag/chroma_client.py에 embedding_function을
    지정하면 된다.
    """
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="manuals_and_incidents")

    if collection.count() > 0:
        client.delete_collection("manuals_and_incidents")
        collection = client.get_or_create_collection(name="manuals_and_incidents")

    documents, ids, metadatas = [], [], []
    for path in sorted(RAG_SOURCES_DIR.glob("*.txt")):
        chunks = [c.strip() for c in path.read_text(encoding="utf-8").split("\n\n") if c.strip()]
        for i, chunk in enumerate(chunks):
            documents.append(chunk)
            ids.append(f"{path.stem}-{i}")
            metadatas.append({"source": path.name})

    if documents:
        collection.add(documents=documents, ids=ids, metadatas=metadatas)

    print(f"[6/9] RAG 인제스트 완료: {len(documents)}개 청크 -> {collection.name}")


def query_sop_steps(motor_name: str, metric: str) -> list[str]:
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="manuals_and_incidents")
    query_text = f"{motor_name} {METRIC_LABELS[metric]} 이상 대응 정비 절차"
    result = collection.query(query_texts=[query_text], n_results=2)

    steps: list[str] = []
    for doc in result.get("documents", [[]])[0]:
        sentences = re.split(r"(?<=[.])\s+", doc.replace("\n", " "))
        steps.extend(s.strip() for s in sentences if len(s.strip()) > 8)

    if not steps:
        steps = ["설비 안전 정지 후 담당자 육안 점검을 진행하십시오."]

    return steps[:4]


def build_diagnosis_text(motor: dict, metric: str, value: float, status: str) -> str:
    label = METRIC_LABELS[metric]
    unit = METRIC_UNITS[metric]
    _, warning, danger, _ = THRESHOLDS[metric]
    threshold = danger if status in ("DANGER", "FAULT") else warning
    return (
        f"주요 원인: {label} 수치가 {value}{unit}로 임계치({threshold}{unit})를 초과했습니다. "
        f"단기(2시간) 버퍼 데이터 기준 완만한 상승 추세가 관측되며, 장기(6시간) 트렌드 분석 결과 "
        f"점진적 악화 패턴으로 판단됩니다.\n"
        f"연쇄 영향 분석: 온도와 진동이 함께 상승하는 패턴은 베어링 윤활 부족의 전형적 징후로, "
        f"과거 유사 장애 이력과 일치합니다.\n"
        f"방치 시 예상 결과: 현재 추세가 지속될 경우 FAULT(고장/정지) 단계로 진행될 가능성이 있어 "
        f"조속한 점검을 권장합니다."
    )


def build_notification_message(motor: dict, status: str, reason: str) -> str:
    label = {"DANGER": "위험", "FAULT": "고장/정지"}.get(status, status)
    return f"[{status}] {motor['motor_id']} 모터 {label} 감지 ({reason}). 리포트를 확인하세요."


def generate_reports_and_notifications(
    conn, logs: list[dict], contacts_by_company: dict[str, dict]
) -> tuple[int, int]:
    report_count = 0
    notif_count = 0

    for log in logs:
        if log["new_status"] not in ("DANGER", "FAULT") or log["metric_name"] == "connectivity":
            continue

        motor = log["motor"]
        metric = log["metric_name"]
        status_col = {
            "temperature": "temperature",
            "vibration": "vibration",
            "current": "current",
            "sound": "sound",
        }[metric]

        telemetry_row = conn.execute(
            "SELECT * FROM motor_telemetry WHERE motor_id = ? AND time = ?",
            (motor["motor_id"], log["created_at"]),
        ).fetchone()
        if telemetry_row is None:
            continue

        event_dt = datetime.strptime(log["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
        report_dt = event_dt + timedelta(seconds=12)
        session_id = REPORT_SESSION_ID_FORMAT.format(
            motor_id=motor["motor_id"],
            date=kst_str(event_dt, "%Y%m%d"),
            time=kst_str(event_dt, "%H%M%S"),
        )

        sensors = []
        for m in METRIC_NAMES:
            value = telemetry_row[m]
            m_status = telemetry_row[
                {"temperature": "temp_status", "vibration": "vib_status",
                 "current": "current_status", "sound": "sound_status"}[m]
            ]
            _, warning, _, _ = THRESHOLDS[m]
            sensors.append(
                {
                    "label": METRIC_LABELS[m],
                    "value": value,
                    "unit": METRIC_UNITS[m],
                    "range_text": f"≤ {warning} {METRIC_UNITS[m]}",
                    "status": m_status,
                    "status_class": m_status.lower(),
                }
            )

        contact = contacts_by_company[motor["company_id"]]
        sop_steps = query_sop_steps(motor["motor_name"], metric)
        diagnosis_text = build_diagnosis_text(motor, metric, telemetry_row[status_col], log["new_status"])
        notification_message = build_notification_message(motor, log["new_status"], log["trigger_reason"])

        context = {
            "status": log["new_status"],
            "status_class": log["new_status"].lower(),
            "status_label": "위험 단계 감지" if log["new_status"] == "DANGER" else "고장/정지 감지",
            "company_name": "",
            "company_id": motor["company_id"],
            "motor_id": motor["motor_id"],
            "motor_name": motor["motor_name"],
            "installation_location": motor["installation_location"],
            "model_name": motor["model_name"],
            "event_time": kst_str(event_dt),
            "generated_date": kst_str(report_dt, "%Y-%m-%d"),
            "report_generated_at": kst_str(report_dt, "%H:%M:%S"),
            "session_id": session_id,
            "sensors": sensors,
            "diagnosis_model_label": "GPT-4o 기반 진단 에이전트",
            "diagnosis_text": diagnosis_text,
            "sop_steps": sop_steps,
            "trigger_reason": log["trigger_reason"],
            "recipient_name": f"{contact['contact_name']} ({mask_phone(contact['phone_number'])})",
            "notification_message": notification_message,
        }
        row = conn.execute(
            "SELECT company_name FROM companies WHERE company_id = ?", (motor["company_id"],)
        ).fetchone()
        context["company_name"] = row["company_name"] if row else motor["company_id"]

        try:
            pdf_bytes = render_report_pdf(context)
            conn.execute(
                "UPDATE motor_status_logs SET report_pdf = ? WHERE log_id = ?",
                (pdf_bytes, log["log_id"]),
            )
            report_count += 1
        except Exception as exc:  # WeasyPrint 네이티브 라이브러리 미설치 등 (README 참고)
            print(f"       [경고] PDF 생성 실패 (log_id={log['log_id']}): {exc}")

        conn.execute(
            "INSERT INTO notification_logs "
            "(motor_id, contact_id, channel_type, title, message_content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                motor["motor_id"],
                contact["contact_id"],
                RNG.choice(("SMS", "EMAIL", "KAKAO_ALIMTALK")),
                f"[{log['new_status']}] {motor['motor_id']} 이상 감지",
                notification_message,
                log["created_at"],
            ),
        )
        notif_count += 1

    print(f"[7/9] PDF 리포트(report_pdf BLOB) 생성 완료: {report_count}건")
    print(f"[8/9] notification_logs 시드 완료: {notif_count}건")
    return report_count, notif_count


def seed_login_logs(conn, contacts: list[dict]) -> None:
    for contact in contacts:
        conn.execute(
            "INSERT INTO login_logs (contact_id, ip_address, created_at) VALUES (?, ?, ?)",
            (contact["contact_id"], "127.0.0.1", iso(utc_now() - timedelta(days=1))),
        )
    print(f"[8/9] login_logs 시드 완료: {len(contacts)}건")


def main() -> None:
    reset_database()
    conn = get_connection()
    try:
        company_ids = seed_companies(conn)
        contacts = seed_contacts(conn, company_ids)
        contacts_by_company = {c["company_id"]: c for c in contacts}
        motors = seed_motors(conn, company_ids)
        generate_telemetry(conn, motors)
        logs = scan_transitions_and_log(conn, motors)
        conn.commit()

        ingest_rag_sources()

        report_count, notif_count = generate_reports_and_notifications(conn, logs, contacts_by_company)
        seed_login_logs(conn, contacts)
        conn.commit()
    finally:
        conn.close()

    print("[9/9] 완료 요약")
    print(f"       companies={len(company_ids)}, contacts={len(contacts)}, motors={len(motors)}")
    print(f"       status_logs={len(logs)}, reports(PDF)={report_count}, notifications={notif_count}")
    print()
    print("      다음 명령으로 결과물을 커밋하세요:")
    print("        git add data/app.db data/chroma/")
    print('        git commit -m "chore: 시연용 데이터 갱신"')


if __name__ == "__main__":
    main()
