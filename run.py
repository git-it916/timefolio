"""
Timefolio 따라잡기 전략 — 통합 실행기.

사용법:
    python run.py                스크래핑 1회 + 자동 분석
    python run.py scrape         스크래핑만 (데이터 수집)
    python run.py analyze        분석만 (최근 2개 스냅샷 비교)
    python run.py list           저장된 스냅샷 목록 확인
    python run.py arb            차익거래 봇 실행 (.env ARB_DRY_RUN 설정)
    python run.py arb-dry        차익거래 봇 DRY_RUN (주문 제출 안 함)
    python run.py probe          웹사이트 DOM 구조 프로브
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
    from timefolio.analyzer import (
        analyze, analyze_top20_trades, find_hidden_convictions, list_snapshots,
        print_hidden_convictions, print_report, print_top20_trades,
        save_report, signals_to_dataframe,
    )
    from timefolio.notifier import send_signal_report

    snapshots = list_snapshots()
    curr_path, prev_path = snapshots[-1][2], snapshots[-2][2]
    signals = analyze(curr_path, prev_path)
    trades = analyze_top20_trades(curr_path, prev_path)
    hiddens = find_hidden_convictions(curr_path)
    print_report(signals)
    print_top20_trades(trades)
    print_hidden_convictions(hiddens)
    report_path = save_report(signals_to_dataframe(signals))
    print(f"\n>> 상세 리포트 저장: {report_path}")
    send_signal_report(signals, trades, hiddens)


def cmd_list() -> None:
    from timefolio.analyzer import list_snapshots
    snapshots = list_snapshots()
    if not snapshots:
        print("저장된 스냅샷이 없습니다. 'python run.py scrape'로 데이터를 수집하세요.")
        return
    print(f"스냅샷 {len(snapshots)}개:")
    for date, seq, path in snapshots:
        print(f"  {date}_{seq}  ->  {path}")


def cmd_arb() -> None:
    from timefolio.fast_arb import run_fast_arbitrage
    run_fast_arbitrage()


def cmd_arb_dry() -> None:
    from timefolio.fast_arb import run_fast_arbitrage
    run_fast_arbitrage(dry_run=True)


def cmd_arb_loop() -> None:
    from timefolio.arb_loop import run_arb_loop
    run_arb_loop()


def cmd_arb_loop_dry() -> None:
    from timefolio.arb_loop import run_arb_loop
    run_arb_loop(dry_run=True)


def cmd_arb_selenium() -> None:
    from timefolio.arbitrage import run_arbitrage
    run_arbitrage()


def cmd_probe() -> None:
    import subprocess
    import sys
    subprocess.run([sys.executable, "probe.py"], check=False)


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
        print("  [2/2] 전략 분석 + 텔레그램 전송")
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
        "arb": cmd_arb,
        "arb-dry": cmd_arb_dry,
        "arb-loop": cmd_arb_loop,
        "arb-loop-dry": cmd_arb_loop_dry,
        "arb-selenium": cmd_arb_selenium,
        "probe": cmd_probe,
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
