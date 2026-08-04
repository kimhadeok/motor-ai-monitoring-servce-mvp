"""리포트(PDF) 렌더링. 06_report_spec.md §1 파이프라인.

Jinja2로 HTML 렌더 -> WeasyPrint로 PDF 변환까지 전부 메모리에서 처리하고,
디스크에 중간 파일을 쓰지 않는다 (report_pdf BLOB 저장 결정, 2026-08-04 확정).
"""

import io

from jinja2 import Environment, FileSystemLoader

from app.config import REPORT_TEMPLATE_DIR, REPORT_TEMPLATE_FILENAME

_env = Environment(loader=FileSystemLoader(str(REPORT_TEMPLATE_DIR)))


def render_report_html(context: dict) -> str:
    template = _env.get_template(REPORT_TEMPLATE_FILENAME)
    return template.render(**context)


def render_report_pdf(html_str: str) -> bytes:
    """렌더된 HTML 문자열 -> PDF 바이트. 디스크 미기록, io.BytesIO만 사용.

    입력이 context가 아니라 HTML인 이유: 리포트 HTML은 진단 시점에 이미 생성되어
    `motor_status_logs.report_html`에 저장돼 있고, PDF는 그것을 그대로 변환하기만 하면
    되기 때문이다 (06_report_spec.md §1). 같은 원본에서 나오므로 두 형식의 내용이
    어긋날 여지가 없다.

    WeasyPrint는 Pango 등 네이티브 라이브러리가 필요해 로컬 Windows 개발환경에서는
    별도 런타임 설치 없이 import가 실패할 수 있다(Streamlit Community Cloud는
    packages.txt로 해결됨). 그래서 import를 함수 내부로 지연시켜, 이 함수를 호출하지
    않는 한 모듈 자체는 항상 정상 import되도록 한다. 호출측은 예외를 잡아 HTML로
    폴백한다 — `app/reports/service.py`의 `get_report()`.
    """
    from weasyprint import HTML

    buffer = io.BytesIO()
    HTML(string=html_str, base_url=str(REPORT_TEMPLATE_DIR)).write_pdf(buffer)
    return buffer.getvalue()
