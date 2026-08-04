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


def render_report_pdf(context: dict) -> bytes:
    """context -> PDF 바이트. 디스크 미기록, io.BytesIO만 사용.

    WeasyPrint는 Pango/Cairo/GLib 네이티브 라이브러리가 필요해 로컬 Windows
    개발환경에서는 별도 GTK3 런타임 설치 없이 import가 실패할 수 있다
    (Streamlit Community Cloud는 packages.txt로 해결됨). 그래서 import를
    함수 내부로 지연시켜, 이 함수를 호출하지 않는 한 모듈 자체는 항상
    정상 import되도록 한다.
    """
    from weasyprint import HTML

    html_str = render_report_html(context)
    buffer = io.BytesIO()
    HTML(string=html_str, base_url=str(REPORT_TEMPLATE_DIR)).write_pdf(buffer)
    return buffer.getvalue()
