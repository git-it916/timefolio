"""
Timefolio 따라잡기 전략 — 통합 실행기.

사용법:
    python run.py                스크래핑 1회 + 자동 분석
    python run.py scrape         스크래핑만 (데이터 수집)
    python run.py analyze        분석만 (최근 2개 스냅샷 비교)
    python run.py list           저장된 스냅샷 목록 확인
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def cmd_scrape() -> str:
    from timefolio.scraper import run_scraper
    return run_scraper()


def cmd_analyze() -> None:
    from timefolio.analyzer import run
    run()


def cmd_list() -> None:
    from timefolio.analyzer import list_snapshots
    snapshots = list_snapshots()
    if not snapshots:
        print("저장된 스냅샷이 없습니다. 'python run.py scrape'로 데이터를 수집하세요.")
        return
    print(f"스냅샷 {len(snapshots)}개:")
    for date, seq, path in snapshots:
        print(f"  {date}_{seq}  ->  {path}")


def cmd_all() -> None:
    from timefolio.analyzer import list_snapshots

    print("=" * 50)
    print("  [1/2] 스크래핑 시작")
    print("=" * 50)
    cmd_scrape()

    snapshots = list_snapshots()
    if len(snapshots) >= 2:
        print()
        print("=" * 50)
        print("  [2/2] 전략 분석 시작")
        print("=" * 50)
        cmd_analyze()
    else:
        print()
        print("스냅샷이 1개뿐입니다.")
        print("한 번 더 실행하면 비교 분석이 가능합니다: python run.py")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    commands = {
        "scrape": cmd_scrape,
        "analyze": cmd_analyze,
        "list": cmd_list,
        "all": cmd_all,
    }

    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return

    handler = commands.get(cmd)
    if handler is None:
        print(f"알 수 없는 명령: {cmd}")
        print(__doc__)
        sys.exit(1)

    handler()


if __name__ == "__main__":
    main()
