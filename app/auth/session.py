"""로그인 검증 및 세션 상태 헬퍼. 05_ui_screens.md §2, §5-1 기준."""

from dataclasses import dataclass

import bcrypt
import streamlit as st

from app.db.connection import connection_scope


@dataclass
class AuthResult:
    success: bool
    contact_id: int | None = None
    company_id: str | None = None
    contact_name: str | None = None
    company_name: str | None = None
    error: str | None = None


def login(email: str, password: str, ip_address: str) -> AuthResult:
    """이메일/비밀번호 검증 + allowed_ip 체크 + login_logs 기록 (성공/실패 모두)."""
    with connection_scope() as conn:
        # 회사명은 상단 헤더에 매 화면 표시되므로 로그인 시 한 번 읽어 세션에 담는다.
        row = conn.execute(
            "SELECT ct.contact_id, ct.company_id, ct.contact_name, ct.password_hash, "
            "       ct.allowed_ip, co.company_name "
            "FROM company_contacts ct JOIN companies co ON co.company_id = ct.company_id "
            "WHERE ct.email = ?",
            (email,),
        ).fetchone()

        result: AuthResult
        if row is None:
            result = AuthResult(success=False, error="이메일 또는 비밀번호가 올바르지 않습니다.")
        elif not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
            result = AuthResult(success=False, error="이메일 또는 비밀번호가 올바르지 않습니다.")
        elif row["allowed_ip"] and row["allowed_ip"] != ip_address:
            result = AuthResult(success=False, error="허용되지 않은 접속 위치입니다.")
        else:
            result = AuthResult(
                success=True,
                contact_id=row["contact_id"],
                company_id=row["company_id"],
                contact_name=row["contact_name"],
                company_name=row["company_name"],
            )

        conn.execute(
            "INSERT INTO login_logs (contact_id, ip_address) VALUES (?, ?)",
            (result.contact_id, ip_address),
        )

        return result


def is_authenticated() -> bool:
    return bool(st.session_state.get("authenticated"))


def start_session(auth: AuthResult) -> None:
    st.session_state["authenticated"] = True
    st.session_state["contact_id"] = auth.contact_id
    st.session_state["company_id"] = auth.company_id
    st.session_state["contact_name"] = auth.contact_name
    st.session_state["company_name"] = auth.company_name


def end_session() -> None:
    for key in (
        "authenticated",
        "contact_id",
        "company_id",
        "contact_name",
        "company_name",
        "selected_motor_id",
    ):
        st.session_state.pop(key, None)
