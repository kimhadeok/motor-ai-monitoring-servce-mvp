"""데모 데이터 수동 재생성 CLI (선택적 도구).

평상시에는 앱 부팅 시 `app/services/bootstrap.py`가 자동으로 데이터를 만들므로
이 스크립트를 실행할 필요가 없다 (02_architecture.md §6.4). 로컬에서 데이터를
강제로 다시 만들거나 시드 로직 변경을 빠르게 확인하고 싶을 때만 사용한다.

부트스트랩과 동일한 `app/` 로직을 호출하며 별도 구현을 두지 않는다.

실행: uv run python scripts/seed_data.py [--force]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.bootstrap import bootstrap_demo_data  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="시연용 데모 데이터를 생성한다.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="기존 DB를 삭제하고 처음부터 다시 만든다 (기본값: 데이터가 있으면 시드 생략)",
    )
    args = parser.parse_args()

    summary = bootstrap_demo_data(force=args.force)

    if summary.get("skipped_concurrent"):
        print("다른 프로세스가 부트스트랩 중이어서 건너뛰었습니다.")
        return

    print("=== 데모 데이터 생성 완료 ===")
    if summary.get("seeded"):
        print(f"  회사             {summary['companies']}건")
        print(f"  담당자           {summary['contacts']}건")
        print(f"  모터             {summary['motors']}대")
        print(f"  텔레메트리       {summary['telemetry']:,}행")
        print(f"  상태 전이 로그   {summary['status_logs']}건")
        print(f"  알림             {summary['notifications']}건 (쿨다운 적용 후)")
    else:
        print("  기존 데이터가 있어 시드를 건너뛰었습니다 (--force로 재생성 가능)")

    print(f"  RAG 청크         {summary['rag_chunks']}개")
    print(f"  리포트 HTML      {summary['reports_html']}건")

    timings = summary.get("timings", {})
    if timings:
        detail = "  ".join(f"{k}={v:.2f}s" for k, v in timings.items() if k != "total")
        print(f"\n  소요: {timings.get('total', 0):.2f}s  ({detail})")

    if summary.get("demo_emails"):
        print(f"\n  데모 계정 (비밀번호 공통: {summary['demo_password']})")
        for email in summary["demo_emails"]:
            print(f"    - {email}")


if __name__ == "__main__":
    main()
