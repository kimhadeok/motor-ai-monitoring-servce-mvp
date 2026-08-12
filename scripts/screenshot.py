"""실행 중인 앱의 화면을 캡처한다 (개발 도구).

CSS·레이아웃 수정이 브라우저에서 실제로 어떻게 그려지는지 확인하기 위한 것이다.
`AppTest`는 어떤 위젯과 HTML이 만들어졌는지만 알려줄 뿐, 렌더 결과(레이아웃 붕괴,
색 대비, 요소 겹침)는 보여주지 못한다.

주의: 헤드리스 Chromium은 사용자의 Chrome과 폰트 렌더링이 다를 수 있다. 레이아웃 붕괴나
색 문제는 잡히지만 글자 줄바꿈이 완전히 같지는 않다. 최종 확인은 실제 브라우저가 기준이다.

사용법:
    uv run streamlit run main.py --server.port 8501 --server.headless true   # 먼저 앱 실행
    uv run python scripts/screenshot.py --out <디렉터리> [--email demo1@hankuk-motors.co.kr]
    uv run python scripts/screenshot.py --out <디렉터리> --theme dark --detail
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

def capture(url: str, out_dir: Path, theme: str, email: str, password: str, detail: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # 테마는 OS 선호도(prefers-color-scheme)를 에뮬레이션해 바꾼다. Streamlit의 기본
        # 설정이 "Use system setting"이라 저장된 선택이 없으면 이 값을 그대로 따른다.
        # localStorage 키를 직접 건드리는 방식은 키 이름이 내부 구현이라 버전에 따라 깨진다.
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            color_scheme="no-preference" if theme == "system" else theme,
        )
        page = context.new_page()

        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=out_dir / f"01-login-{theme}.png", full_page=True)
        print(f"  01-login-{theme}.png")

        # 로그인 — 폼이 이미 채워져 있어도 명시적으로 넣어 재현성을 확보한다.
        inputs = page.locator('input[aria-label="이메일"], input[type="text"]').first
        inputs.fill(email)
        page.locator('input[type="password"]').first.fill(password)
        page.get_by_role("button", name="로그인").click()
        page.wait_for_timeout(3000)

        page.screenshot(path=out_dir / f"02-dashboard-{theme}.png", full_page=True)
        print(f"  02-dashboard-{theme}.png")

        if detail:
            # 첫 모터 카드 클릭 → 상세
            page.locator('[class*="st-key-motorclick-"] button').first.click()
            page.wait_for_timeout(2500)
            page.screenshot(path=out_dir / f"03-detail-{theme}.png", full_page=True)
            print(f"  03-detail-{theme}.png")

        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="실행 중인 Streamlit 앱 화면을 캡처한다.")
    parser.add_argument("--url", default="http://localhost:8501")
    parser.add_argument("--out", required=True, help="스크린샷을 저장할 디렉터리")
    parser.add_argument("--theme", default="light", choices=("light", "dark", "system"))
    parser.add_argument("--email", default="demo1@hankuk-motors.co.kr")
    parser.add_argument("--password", default="demo1234!")
    parser.add_argument("--detail", action="store_true", help="모터 상세 페이지까지 캡처")
    args = parser.parse_args()

    print(f"캡처 → {args.out} (theme={args.theme})")
    capture(args.url, Path(args.out), args.theme, args.email, args.password, args.detail)


if __name__ == "__main__":
    main()
