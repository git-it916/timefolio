"""
타임폴리오 차익거래 봇 통합 오케스트레이터.

실행 흐름:
1. Chrome 드라이버 초기화
2. 타임폴리오 로그인
3. 대회 탭 → 상위 N명 포트폴리오 스크래핑 (종목코드 + 현재가)
4. KIS API 실시간 가격 조회
5. 가격 비교 → 차익 기회 식별
6. 주문 탭 → 차익 종목 매수 주문
7. 텔레그램 요약 전송
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from timefolio.comparator import ArbitrageOpportunity, PriceComparator, print_comparison
from timefolio.config import (
    ARB_DRY_RUN,
    ARB_TOP_N,
    KIS_ACCOUNT,
    KIS_APP_KEY,
    KIS_APP_SECRET,
    KIS_IS_PAPER,
    LOGIN_URL,
    MAX_SINGLE_WEIGHT,
    MIN_ARB_PCT,
    PAGE_LOAD_WAIT,
    USER_ID,
    USER_PW,
    WAIT_TIMEOUT,
)
from timefolio.kis_api import KISApi, KISAuth
from timefolio.order_bot import TimefolioOrderBot

log = logging.getLogger(__name__)

_NUM_PAT = re.compile(r"-?\d+(?:\.\d+)?")
_MODAL_SEL = "div[role='dialog']"


def _smart_text(el) -> str:
    """Selenium 요소에서 텍스트 추출."""
    if el is None:
        return ""
    t = (el.text or "").strip()
    if t:
        return t
    for attr in ("textContent", "innerText", "value"):
        v = el.get_attribute(attr)
        if v and v.strip():
            return v.strip()
    return ""


def _scrape_top_n_portfolios(
    driver, wait: WebDriverWait, n: int,
) -> list[dict]:
    """상위 N명의 포트폴리오에서 종목 정보를 추출.

    Returns:
        [{"code": "A005930", "name": "삼성전자",
          "tf_price": "217,000", "weight": "34.0"}, ...]
    """
    all_stocks: list[dict] = []

    ranking_table = wait.until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "div.datagrid"))
    )

    for i in range(n):
        rank = i + 1
        try:
            # 행 찾기
            rows = ranking_table.find_elements(
                By.XPATH, ".//tbody/tr[starts-with(@style, 'position')]"
            )
            target_row = None
            for row in rows:
                try:
                    rank_text = row.find_element(By.XPATH, ".//td[1]").text.strip()
                    if rank_text.isdigit() and int(rank_text) == rank:
                        target_row = row
                        break
                except Exception:
                    continue

            if target_row is None and i < len(rows):
                target_row = rows[i]

            if target_row is None:
                log.warning("랭킹 %d위 행을 찾을 수 없음", rank)
                continue

            # open 버튼 클릭
            open_btn = target_row.find_element(By.XPATH, ".//button[text()='open']")
            ActionChains(driver).move_to_element(open_btn).perform()
            driver.execute_script("arguments[0].click();", open_btn)

            # 모달 대기
            modal = wait.until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, _MODAL_SEL))
            )
            time.sleep(1)

            # 모달 내 데이터그리드
            grids = modal.find_elements(By.CSS_SELECTOR, "div.datagrid")
            grid = grids[0] if grids else modal

            stock_rows = grid.find_elements(By.XPATH, ".//tbody/tr")
            for sr in stock_rows:
                tds = sr.find_elements(By.TAG_NAME, "td")
                if len(tds) < 3:
                    continue

                code = ""
                try:
                    code_td = sr.find_element(By.CSS_SELECTOR, "td[id$='_prodId']")
                    code = _smart_text(code_td).strip()
                except NoSuchElementException:
                    code = _smart_text(tds[0]).strip()

                name = ""
                try:
                    name_td = sr.find_element(By.CSS_SELECTOR, "td[id$='_prodNm']")
                    name = _smart_text(name_td).strip()
                except NoSuchElementException:
                    name = _smart_text(tds[1]).strip()

                price = ""
                try:
                    price_td = sr.find_element(By.CSS_SELECTOR, "td[id$='_close']")
                    price = _smart_text(price_td).strip()
                except NoSuchElementException:
                    if len(tds) >= 3:
                        price = _smart_text(tds[2]).strip()

                weight = ""
                try:
                    wei_td = sr.find_element(By.CSS_SELECTOR, "td[id$='_wei']")
                    weight = _smart_text(wei_td).strip()
                except NoSuchElementException:
                    pass

                if name and code:
                    all_stocks.append({
                        "code": code, "name": name,
                        "tf_price": price, "weight": weight,
                    })

            log.info("%d위 포트폴리오 스크래핑 완료 (%d종목)", rank, len(stock_rows))

            # 모달 닫기
            try:
                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.ESCAPE)
                WebDriverWait(driver, 5).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, _MODAL_SEL))
                )
            except (TimeoutException, Exception):
                driver.refresh()
                time.sleep(PAGE_LOAD_WAIT)
                tabs = driver.find_elements(By.CSS_SELECTOR, "ul#tabmenu li")
                if len(tabs) >= 2:
                    tabs[1].click()
                    time.sleep(PAGE_LOAD_WAIT)
                ranking_table = wait.until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "div.datagrid"))
                )

            time.sleep(0.5)

        except StaleElementReferenceException:
            log.warning("%d위 StaleElement - 테이블 재탐색", rank)
            ranking_table = wait.until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "div.datagrid"))
            )
        except Exception as e:
            log.error("%d위 스크래핑 오류: %s", rank, e)

    return all_stocks


def _check_market_hours() -> bool:
    """장 운영 시간 확인 (09:00~15:20)."""
    now = datetime.now()
    start = now.replace(hour=9, minute=0, second=0)
    end = now.replace(hour=15, minute=20, second=0)
    return start <= now <= end


def run_arbitrage(dry_run: bool | None = None) -> None:
    """차익거래 봇 1회 실행.

    Args:
        dry_run: None이면 config 값 사용, True/False면 직접 지정
    """
    effective_dry_run = dry_run if dry_run is not None else ARB_DRY_RUN

    if not KIS_APP_KEY or not KIS_APP_SECRET:
        log.error("KIS API 인증 정보가 없습니다. .env에 KIS_APP_KEY/KIS_APP_SECRET을 설정하세요.")
        return

    if not USER_ID or not USER_PW:
        log.error("타임폴리오 인증 정보가 없습니다. .env에 TIMEFOLIO_ID/TIMEFOLIO_PW를 설정하세요.")
        return

    mode_str = "DRY_RUN" if effective_dry_run else "LIVE"
    print(f"\n{'=' * 70}")
    print(f"  TIMEFOLIO 차익거래 봇 [{mode_str}]")
    print(f"  상위 {ARB_TOP_N}명 | 최소차익 {MIN_ARB_PCT}% | 최대비중 {MAX_SINGLE_WEIGHT}%")
    print(f"{'=' * 70}\n")

    # Chrome 드라이버
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        # 1. 로그인
        log.info("[1/6] 타임폴리오 로그인")
        driver.get(LOGIN_URL)
        wait.until(EC.visibility_of_element_located((By.ID, "email"))).send_keys(USER_ID)
        wait.until(EC.visibility_of_element_located((By.ID, "password"))).send_keys(USER_PW)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn.btn-primary"))).click()
        time.sleep(PAGE_LOAD_WAIT)
        log.info("  로그인 완료")

        # 2. 대회 탭 → 포트폴리오 스크래핑
        log.info("[2/6] 대회 탭 → 상위 %d명 포트폴리오 스크래핑", ARB_TOP_N)
        tabs = driver.find_elements(By.CSS_SELECTOR, "ul#tabmenu li")
        if len(tabs) >= 2:
            tabs[1].click()  # 대회 탭 = Tab[1]
            time.sleep(PAGE_LOAD_WAIT)

        stocks = _scrape_top_n_portfolios(driver, wait, ARB_TOP_N)
        log.info("  총 %d개 종목 수집", len(stocks))

        if not stocks:
            log.warning("스크래핑된 종목이 없습니다.")
            return

        # 3. KIS API 가격 비교
        log.info("[3/6] KIS API 실시간 가격 조회")
        # 시세 조회는 실전 API 엔드포인트 사용 (읽기 전용, paper 불필요)
        kis_auth = KISAuth(
            app_key=KIS_APP_KEY,
            app_secret=KIS_APP_SECRET,
            account_number=KIS_ACCOUNT,
            is_paper=False,
        )
        kis_api = KISApi(kis_auth)
        comparator = PriceComparator(kis_api)
        opportunities = comparator.compare(stocks)

        # 4. 결과 출력
        log.info("[4/6] 비교 결과 출력")
        print_comparison(stocks, opportunities)

        if not opportunities:
            log.info("차익 기회가 없습니다.")
            return

        # 5. 장 시간 확인
        if not effective_dry_run and not _check_market_hours():
            log.warning("장 운영 시간(09:00~15:20)이 아닙니다. DRY_RUN으로 전환합니다.")
            effective_dry_run = True

        # 6. 주문 실행
        log.info("[5/6] 주문 실행 (%s)", "DRY_RUN" if effective_dry_run else "LIVE")
        tabs = driver.find_elements(By.CSS_SELECTOR, "ul#tabmenu li")
        if tabs:
            tabs[0].click()  # 주문 탭 = Tab[0]
            time.sleep(PAGE_LOAD_WAIT)

        order_bot = TimefolioOrderBot(driver, wait)
        results: list[tuple[str, bool]] = []

        for opp in opportunities:
            log.info(
                "  주문 시도: %s (차익 %.2f%%, 비중 %.1f%%)",
                opp.stock_name, opp.diff_pct, opp.suggested_weight,
            )
            success = order_bot.place_order(
                stock_name=opp.stock_name,
                weight=opp.suggested_weight,
                diff_pct=opp.diff_pct,
                dry_run=effective_dry_run,
            )
            results.append((opp.stock_name, success))
            time.sleep(1)

        # 결과 요약
        log.info("[6/6] 결과 요약")
        succeeded = sum(1 for _, s in results if s)
        print(f"\n  주문 결과: {succeeded}/{len(results)} 성공 [{mode_str}]")
        for name, success in results:
            status = "OK" if success else "FAIL"
            print(f"    {name}: {status}")

        # 텔레그램 알림
        try:
            _send_arb_telegram(opportunities, results, effective_dry_run)
        except Exception as e:
            log.warning("텔레그램 전송 실패: %s", e)

    except Exception as e:
        log.exception("차익거래 봇 오류: %s", e)
        try:
            driver.save_screenshot("arb_error.png")
        except Exception:
            pass
    finally:
        driver.quit()
        log.info("차익거래 봇 종료")


def _send_arb_telegram(
    opportunities: list[ArbitrageOpportunity],
    results: list[tuple[str, bool]],
    dry_run: bool,
) -> None:
    """차익거래 결과를 텔레그램으로 전송."""
    from timefolio.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    import asyncio
    import telegram

    mode = "DRY\\_RUN" if dry_run else "LIVE"
    now = datetime.now().strftime("%Y\\-%-m\\-%d %H:%M")

    lines = [
        f"*Timefolio 차익거래 \\[{mode}\\]*",
        f"{now}",
        "",
    ]

    for opp in opportunities:
        name = opp.stock_name.replace("-", "\\-").replace(".", "\\.")
        ok = any(n == opp.stock_name and s for n, s in results)
        status = "OK" if ok else "FAIL"
        lines.append(
            f"  {name} \\| TF:{opp.tf_price:,d} KIS:{opp.kis_price:,d}"
            f" \\| \\+{opp.diff_pct:.1f}% \\| {status}"
        )

    text = "\n".join(lines)

    async def _send():
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID, text=text,
            parse_mode=telegram.constants.ParseMode.MARKDOWN_V2,
        )

    asyncio.run(_send())
    log.info("텔레그램 차익거래 알림 전송 완료")
