"""
HTTP 기반 고속 차익거래 봇.

Selenium 없이 순수 REST API로 동작. 전체 사이클 ~1초.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from timefolio.api_client import TimefolioApiClient
from timefolio.comparator import ArbitrageOpportunity, PriceComparator, print_comparison
from timefolio.config import (
    ARB_DRY_RUN,
    ARB_TOP_N,
    KIS_APP_KEY,
    KIS_APP_SECRET,
    KIS_ACCOUNT,
    MAX_SINGLE_WEIGHT,
    MIN_ARB_PCT,
    USER_ID,
    USER_PW,
)
from timefolio.kis_api import KISApi, KISAuth

log = logging.getLogger(__name__)


def _check_market_hours() -> bool:
    now = datetime.now()
    return now.replace(hour=9, minute=0) <= now <= now.replace(hour=15, minute=20)


def run_fast_arbitrage(dry_run: bool | None = None) -> None:
    """HTTP 기반 고속 차익거래 봇 1회 실행."""
    effective_dry_run = dry_run if dry_run is not None else ARB_DRY_RUN

    if not KIS_APP_KEY or not KIS_APP_SECRET:
        log.error("KIS API 인증 정보 없음. .env 확인.")
        return
    if not USER_ID or not USER_PW:
        log.error("타임폴리오 인증 정보 없음. .env 확인.")
        return

    mode = "DRY_RUN" if effective_dry_run else "LIVE"
    t_start = time.perf_counter()

    print(f"\n{'=' * 60}")
    print(f"  FAST ARBITRAGE BOT [{mode}]")
    print(f"  Top {ARB_TOP_N} | min {MIN_ARB_PCT}% | max {MAX_SINGLE_WEIGHT}%")
    print(f"{'=' * 60}\n")

    # 1. 타임폴리오 로그인 (HTTP)
    t0 = time.perf_counter()
    tf_client = TimefolioApiClient(USER_ID, USER_PW)
    tf_client.login()
    log.info("[1] 로그인: %.2fs", time.perf_counter() - t0)

    # 2. 상위 N명 포트폴리오 조회 (HTTP)
    t0 = time.perf_counter()
    stocks = tf_client.get_top_n_stocks(ARB_TOP_N)
    log.info("[2] 포트폴리오 조회 (%d종목): %.2fs", len(stocks), time.perf_counter() - t0)

    if not stocks:
        log.warning("종목 없음.")
        return

    # 3. KIS 실시간 가격 비교
    t0 = time.perf_counter()
    kis_auth = KISAuth(
        app_key=KIS_APP_KEY,
        app_secret=KIS_APP_SECRET,
        account_number=KIS_ACCOUNT,
        is_paper=False,  # 시세 조회는 실전 API
    )
    kis_api = KISApi(kis_auth)
    comparator = PriceComparator(kis_api)
    opportunities = comparator.compare(stocks)
    log.info("[3] 가격 비교: %.2fs", time.perf_counter() - t0)

    # 4. 결과 출력
    print_comparison(stocks, opportunities)

    if not opportunities:
        elapsed = time.perf_counter() - t_start
        print(f"\n  총 소요시간: {elapsed:.2f}초")
        return

    # 5. 주문 실행
    if not effective_dry_run and not _check_market_hours():
        log.warning("장외 시간 - DRY_RUN으로 전환")
        effective_dry_run = True

    t0 = time.perf_counter()
    results: list[tuple[str, float, bool]] = []

    for opp in opportunities:
        weight = min(opp.suggested_weight, MAX_SINGLE_WEIGHT)
        if weight <= 0:
            weight = 1.0  # 최소 1%

        if effective_dry_run:
            log.info(
                "[DRY_RUN] %s: TF=%d KIS=%d diff=+%.2f%% -> 매수 %.1f%%",
                opp.stock_name, opp.tf_price, opp.kis_price, opp.diff_pct, weight,
            )
            results.append((opp.stock_name, opp.diff_pct, True))
        else:
            try:
                tf_client.add_order(
                    prod_id=f"A{opp.stock_code}" if not opp.stock_code.startswith("A") else opp.stock_code,
                    wei=weight,
                    ls="L",
                    ex="E",
                    limit_idx=5,
                )
                results.append((opp.stock_name, opp.diff_pct, True))
            except Exception as e:
                log.error("주문 실패 %s: %s", opp.stock_name, e)
                results.append((opp.stock_name, opp.diff_pct, False))

    log.info("[4] 주문 실행: %.2fs", time.perf_counter() - t0)

    # 6. 요약
    elapsed = time.perf_counter() - t_start
    succeeded = sum(1 for _, _, s in results if s)

    print(f"\n{'=' * 60}")
    print(f"  결과: {succeeded}/{len(results)} [{mode}]")
    for name, diff, ok in results:
        print(f"    {'OK' if ok else 'FAIL'} {name} (+{diff:.2f}%)")
    print(f"  총 소요시간: {elapsed:.2f}초")
    print(f"{'=' * 60}")

    # 텔레그램
    try:
        _send_telegram(opportunities, results, effective_dry_run, elapsed)
    except Exception as e:
        log.warning("텔레그램 실패: %s", e)


def _send_telegram(
    opportunities: list[ArbitrageOpportunity],
    results: list[tuple[str, float, bool]],
    dry_run: bool,
    elapsed: float,
) -> None:
    from timefolio.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    import asyncio
    import telegram

    mode = "DRY" if dry_run else "LIVE"
    lines = [f"*Fast Arb \\[{mode}\\] {elapsed:.1f}s*", ""]
    for opp in opportunities:
        name = opp.stock_name.replace("-", "\\-").replace(".", "\\.")
        ok = any(n == opp.stock_name and s for n, _, s in results)
        lines.append(f"{'OK' if ok else 'NG'} {name} \\+{opp.diff_pct:.2f}%")

    async def _send():
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="\n".join(lines),
            parse_mode=telegram.constants.ParseMode.MARKDOWN_V2,
        )
    asyncio.run(_send())
