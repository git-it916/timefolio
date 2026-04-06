"""
Timefolio 자동 스케줄러.

아침 8시부터 30분 간격으로 run.py 실행 후 결과를 텔레그램으로 전송.

사용법:
    python scheduler.py          스케줄러 시작
    python scheduler.py once     즉시 1회 실행 (테스트용)
"""

import logging
import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def job() -> None:
    """스크래핑 → 분석 → 텔레그램 전송."""
    from timefolio.analyzer import (
        analyze,
        analyze_top20_trades,
        list_snapshots,
        print_report,
        print_top20_trades,
        save_report,
        signals_to_dataframe,
    )
    from timefolio.notifier import send_error, send_scrape_only, send_signal_report
    from timefolio.scraper import run_scraper

    now = datetime.now().strftime("%H:%M:%S")
    log.info("=" * 50)
    log.info("  스케줄 실행 시작: %s", now)
    log.info("=" * 50)

    try:
        csv_path = run_scraper()
        log.info("스크래핑 완료: %s", csv_path)

        snapshots = list_snapshots()
        if len(snapshots) < 2:
            log.info("스냅샷 1개 — 비교 분석 건너뜀")
            send_scrape_only(csv_path)
            return

        curr_path, prev_path = snapshots[-1][2], snapshots[-2][2]
        signals = analyze(curr_path, prev_path)
        trades = analyze_top20_trades(curr_path, prev_path)
        print_report(signals)
        print_top20_trades(trades)

        report_path = save_report(signals_to_dataframe(signals))
        log.info("리포트 저장: %s", report_path)

        send_signal_report(signals, trades)
        log.info("텔레그램 전송 완료")

    except Exception as e:
        log.exception("실행 중 오류 발생")
        try:
            send_error(e)
        except Exception:
            log.exception("텔레그램 에러 전송 실패")


def main() -> None:
    from timefolio.config import (
        SCHEDULE_END_HOUR,
        SCHEDULE_INTERVAL_MIN,
        SCHEDULE_START_HOUR,
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID,
    )

    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"

    if cmd == "once":
        log.info("즉시 1회 실행")
        job()
        return

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning(
            "⚠️  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID가 설정되지 않았습니다.\n"
            "   .env 파일에 값을 입력하세요. 텔레그램 전송 없이 실행됩니다."
        )

    scheduler = BlockingScheduler()

    # 08:00~15:00 매 30분
    trigger = CronTrigger(
        hour=f"{SCHEDULE_START_HOUR}-{SCHEDULE_END_HOUR}",
        minute=f"*/{SCHEDULE_INTERVAL_MIN}",
        day_of_week="mon-fri",
    )
    scheduler.add_job(job, trigger, id="timefolio_main", name="Timefolio 정기 스크래핑")

    # 15:27 장 마감 직전
    trigger_close = CronTrigger(
        hour=15,
        minute=27,
        day_of_week="mon-fri",
    )
    scheduler.add_job(job, trigger_close, id="timefolio_close", name="Timefolio 장마감 스크래핑")

    log.info(
        "스케줄러 시작: 월~금 %02d:00~%02d:00 %d분 간격 + 15:27 장마감",
        SCHEDULE_START_HOUR,
        SCHEDULE_END_HOUR,
        SCHEDULE_INTERVAL_MIN,
    )
    log.info("종료하려면 Ctrl+C")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("스케줄러 종료")


if __name__ == "__main__":
    main()
