"""앱 로거 설정 (2026-08-10).

**왜 필요한가.** Streamlit Community Cloud에서 앱 내부 상태를 볼 수 있는 통로는
Manage app 로그(프로세스 stdout/stderr)뿐이다. 그런데 Python 기본 설정에서는 핸들러가
없는 로거의 INFO가 그냥 버려지고 WARNING 이상만 `lastResort` 핸들러로 나간다.
Streamlit이 붙이는 핸들러도 `streamlit` 네임스페이스에만 적용되므로 우리 로그는 걸리지 않는다.
그래서 `app.*` 네임스페이스에 핸들러를 직접 붙인다.

이게 없으면 배포본에서 다음을 판정할 방법이 없다.
- 커밋된 `data/chroma/`가 열렸는지 (안 열려도 SOP가 키워드 폴백으로 **조용히** 떨어진다)
- 진단이 LLM으로 나갔는지, 폴백이면 그 사유가 무엇인지
- 부팅 시드가 얼마나 걸렸는지
"""

import io
import logging
import sys

from app.config import LOG_FORMAT, LOG_LEVEL

_APP_LOGGER_NAME = "app"
_configured = False
# TextIOWrapper가 가비지 컬렉션되면 감싼 버퍼까지 닫힌다. 모듈 레벨에서 참조를 붙들어 둔다.
_utf8_stream = None


def _log_stream():
    """UTF-8로 쓸 수 있는 stderr.

    배포 대상(Linux)은 UTF-8이라 그대로 쓰면 되지만, Windows 콘솔은 기본 코드페이지가
    cp949라 한글 로그가 깨져 로컬에서 읽을 수 없다. 인코딩이 UTF-8이 아닐 때만 감싼다.
    """
    global _utf8_stream

    stream = sys.stderr
    if (getattr(stream, "encoding", "") or "").lower().replace("-", "") == "utf8":
        return stream
    buffer = getattr(stream, "buffer", None)
    if buffer is None:  # 버퍼가 없는 스트림(테스트 더미 등)은 그대로 쓴다
        return stream

    _utf8_stream = io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True)
    return _utf8_stream


def configure_logging() -> logging.Logger:
    """`app.*` 로거에 stderr 핸들러를 1회 붙인다. 재호출은 무해하다.

    `propagate = False`로 루트로 올리지 않는다. Streamlit이나 다른 라이브러리가 루트에
    핸들러를 붙여 두면 같은 줄이 두 번 찍히기 때문이다.
    """
    global _configured

    logger = logging.getLogger(_APP_LOGGER_NAME)
    if _configured:
        return logger

    handler = logging.StreamHandler(_log_stream())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False

    # 알 수 없는 LOG_LEVEL 값이 들어와도 앱이 죽지 않게 한다 (CLAUDE.md fallback).
    level = getattr(logging, LOG_LEVEL, None)
    logger.setLevel(level if isinstance(level, int) else logging.INFO)

    _configured = True
    return logger
