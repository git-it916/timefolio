"""
Timefolio 모의투자대회 포트폴리오 스크래퍼.

상위 N명의 보유종목을 CSV로 저장한다.
"""

import csv
import logging
import os
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

from timefolio.config import (
    DB_DIR,
    HEADLESS,
    LOGIN_URL,
    MODAL_CLOSE_WAIT,
    PAGE_LOAD_WAIT,
    PORTFOLIO_PREFIX,
    RANKS_TO_SCRAPE,
    USER_ID,
    USER_PW,
    WAIT_TIMEOUT,
)

log = logging.getLogger(__name__)

_NUM_PAT = re.compile(r"-?\d+(?:\.\d+)?")

# ── CSV 경로 생성 ─────────────────────────────────────

def _next_csv_path(db_dir: str, prefix: str) -> str:
    """portfolio_YYYYMMDD_N.csv — 같은 날짜 안에서 시퀀스 자동 증가."""
    os.makedirs(db_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    n = 1
    while True:
        path = os.path.join(db_dir, f"{prefix}_{date_str}_{n}.csv")
        if not os.path.exists(path):
            return path
        n += 1


def _init_csv(path: str) -> None:
    with open(path, mode="w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow([
            "rank", "user_nick", "stock_code", "stock_name",
            "tf_price", "weight", "scraped_at",
        ])
    log.info("CSV 준비: %s", path)


# ── 텍스트 추출 헬퍼 ──────────────────────────────────

def _to_number(text: str) -> float | str:
    """'15.3%' → 15.3, 숫자 없으면 빈 문자열."""
    if not text:
        return ""
    m = _NUM_PAT.search(text.replace(",", ""))
    return float(m.group(0)) if m else ""


def _smart_text(el) -> str:
    """Selenium 요소에서 최대한 텍스트를 뽑아내는 다단계 폴백."""
    if el is None:
        return ""
    t = (el.text or "").strip()
    if t:
        return t
    for attr in ("textContent", "innerText", "value", "aria-valuenow", "data-value"):
        v = el.get_attribute(attr)
        if v and v.strip():
            return v.strip()
    for sel in (".frozen", "span", "div"):
        try:
            child = el.find_element(By.CSS_SELECTOR, sel)
            v = (child.get_attribute("textContent") or "").strip()
            if v:
                return v
        except NoSuchElementException:
            pass
    html = el.get_attribute("innerHTML") or ""
    hm = _NUM_PAT.search(html.replace(",", ""))
    return hm.group(0) if hm else ""


# ── 포트폴리오 저장 ───────────────────────────────────

def _save_portfolio(csv_path: str, rank: int, user_nick: str,
                    portfolio_rows: list[tuple[str, str, str, str]]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for stock_code, stock_name, price_text, weight_text in portfolio_rows:
        stock_name = (stock_name or "").strip()
        if not stock_name:
            continue
        stock_code = (stock_code or "").strip()
        price_val = _to_number((price_text or "").strip())
        weight_val = _to_number((weight_text or "").strip())
        rows.append((rank, user_nick, stock_code, stock_name, price_val, weight_val, now))

    if not rows:
        log.warning("  %d위 %s — 저장할 종목 없음", rank, user_nick)
        return

    with open(csv_path, mode="a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)
    log.info("  %d위 %s — %d종목 저장", rank, user_nick, len(rows))


# ── 모달 닫기 ─────────────────────────────────────────

_MODAL_SEL = "div[role='dialog']"


def _close_modal(driver, short_wait) -> None:
    """Radix UI 모달 닫기. ESC → 오버레이 클릭 → 새로고침 순으로 시도."""
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ESCAPE)
        short_wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, _MODAL_SEL)))
        return
    except (TimeoutException, Exception):
        pass

    try:
        overlay = driver.find_element(By.CSS_SELECTOR, "div.fixed.inset-0.z-50")
        driver.execute_script("arguments[0].click();", overlay)
        short_wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, _MODAL_SEL)))
        return
    except (TimeoutException, NoSuchElementException, Exception):
        pass

    log.warning("  모달 닫기 실패 — 새로고침으로 대체")
    driver.refresh()
    time.sleep(PAGE_LOAD_WAIT)
    try:
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
            (By.XPATH, "//ul[@id='tabmenu']/li[2]")
        )).click()
        time.sleep(PAGE_LOAD_WAIT)
    except Exception as e:
        log.warning("  대회 탭 재이동 실패: %s", e)


# ── 단일 유저 스크래핑 ────────────────────────────────

def _scroll_to_rank(driver, ranking_table, row_index: int) -> None:
    """가상 스크롤 datagrid에서 특정 행이 보이도록 스크롤."""
    tbody = ranking_table.find_element(By.TAG_NAME, "tbody")
    rows = tbody.find_elements(By.XPATH, "./tr[starts-with(@style, 'position')]")
    if not rows:
        return

    # 현재 보이는 행들의 rank 범위 확인
    visible_ranks = []
    for r in rows:
        try:
            rank_text = r.find_element(By.XPATH, ".//td[1]").text.strip()
            if rank_text.isdigit():
                visible_ranks.append(int(rank_text))
        except Exception:
            pass

    target_rank = row_index + 1
    if visible_ranks and target_rank in visible_ranks:
        return  # 이미 보이는 상태

    # datagrid의 스크롤 컨테이너를 찾아 스크롤
    scroll_container = ranking_table.find_element(
        By.CSS_SELECTOR, "div.datagrid-body, div.datagrid-view, .datagrid"
    )
    # 행 높이 추정 (보통 30~40px) × 목표 인덱스만큼 스크롤
    scroll_y = row_index * 35
    driver.execute_script(
        "arguments[0].scrollTop = arguments[1];", scroll_container, scroll_y
    )
    time.sleep(0.5)


def _find_row_by_rank(ranking_table, target_rank: int):
    """가상 스크롤 테이블에서 순위 번호로 행을 찾는다."""
    rows = ranking_table.find_elements(
        By.XPATH, ".//tbody/tr[starts-with(@style, 'position')]"
    )
    for row in rows:
        try:
            rank_text = row.find_element(By.XPATH, ".//td[1]").text.strip()
            if rank_text.isdigit() and int(rank_text) == target_rank:
                return row
        except Exception:
            continue
    return None


def _scrape_one_user(
    driver, wait: WebDriverWait, ranking_table, row_index: int, csv_path: str,
    saved_ranks: set[int],
) -> bool:
    """한 명의 포트폴리오를 스크래핑. 성공 시 True 반환."""
    rank = row_index + 1

    # 가상 스크롤: 해당 행이 보이도록 스크롤
    _scroll_to_rank(driver, ranking_table, row_index)

    # 순위 번호로 행을 찾기 (가상 스크롤에서는 index != DOM 위치)
    target_row = _find_row_by_rank(ranking_table, rank)
    if target_row is None:
        # 폴백: 기존 index 기반 탐색
        rows = ranking_table.find_elements(
            By.XPATH, ".//tbody/tr[starts-with(@style, 'position')]"
        )
        if row_index >= len(rows):
            log.warning("랭킹 행 부족 (rank=%d, rows=%d). 스크래핑 종료.", rank, len(rows))
            return False
        target_row = rows[row_index]

    user_nick = target_row.find_element(By.XPATH, ".//td[3]").text.strip()

    open_btn = target_row.find_element(By.XPATH, ".//button[text()='open']")
    ActionChains(driver).move_to_element(open_btn).perform()
    driver.execute_script("arguments[0].click();", open_btn)
    log.info("%d위 %s — 포트폴리오 열기", rank, user_nick)

    modal = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, _MODAL_SEL)))
    try:
        WebDriverWait(driver, 5).until(EC.text_to_be_present_in_element(
            (By.CSS_SELECTOR, f"{_MODAL_SEL} h2"), user_nick
        ))
    except TimeoutException:
        actual = modal.find_element(By.CSS_SELECTOR, "h2").text.strip()
        log.warning("  헤더 불일치: 기대='%s' 실제='%s' — 실제 기준으로 진행", user_nick, actual)
        user_nick = actual

    if rank in saved_ranks:
        log.info("  %d위 이미 저장됨 — 모달 닫기만 수행", rank)
        _close_modal(driver, WebDriverWait(driver, 5))
        time.sleep(MODAL_CLOSE_WAIT)
        return True

    grids = modal.find_elements(By.CSS_SELECTOR, "div.datagrid")
    grid = grids[0] if grids else modal.find_element(By.CSS_SELECTOR, "div.datagrid")

    stock_rows = grid.find_elements(By.XPATH, ".//tbody/tr")
    if not stock_rows:
        time.sleep(0.5)
        stock_rows = grid.find_elements(By.XPATH, ".//tbody/tr")

    portfolio: list[tuple[str, str, str, str]] = []
    for stock_row in stock_rows:
        tds = stock_row.find_elements(By.TAG_NAME, "td")
        if len(tds) < 2:
            continue

        # 종목코드 (A005930 형식)
        stock_code = ""
        try:
            code_td = stock_row.find_element(By.CSS_SELECTOR, "td[id$='_prodId']")
            stock_code = _smart_text(code_td).strip()
        except NoSuchElementException:
            if tds:
                stock_code = _smart_text(tds[0]).strip()

        # 종목명
        try:
            name_td = stock_row.find_element(By.CSS_SELECTOR, "td[id$='_prodNm']")
        except NoSuchElementException:
            name_td = tds[1]
        stock_name = _smart_text(name_td).strip()
        if not stock_name:
            continue

        # 현재가
        price_text = ""
        try:
            price_td = stock_row.find_element(By.CSS_SELECTOR, "td[id$='_close']")
            price_text = _smart_text(price_td).strip()
        except NoSuchElementException:
            if len(tds) >= 3:
                price_text = _smart_text(tds[2]).strip()

        # 비중
        weight_text = ""
        try:
            wei_td = stock_row.find_element(By.CSS_SELECTOR, "td[id$='_wei']")
            weight_text = _smart_text(wei_td).strip()
        except NoSuchElementException:
            if len(tds) >= 6:
                weight_text = _smart_text(tds[5]).strip()

        portfolio.append((stock_code, stock_name, price_text, weight_text))

    if portfolio:
        _save_portfolio(csv_path, rank, user_nick, portfolio)
        saved_ranks.add(rank)
    else:
        log.warning("  %d위 %s — 보유 종목 없음", rank, user_nick)

    _close_modal(driver, WebDriverWait(driver, 5))
    time.sleep(MODAL_CLOSE_WAIT)
    return True


# ── 메인 스크래퍼 ─────────────────────────────────────

def run_scraper() -> str:
    """스크래핑 실행. 저장된 CSV 경로를 반환."""
    if not USER_ID or not USER_PW:
        log.error(".env에 TIMEFOLIO_ID / TIMEFOLIO_PW를 설정하세요.")
        raise SystemExit(1)

    csv_path = _next_csv_path(DB_DIR, PORTFOLIO_PREFIX)
    _init_csv(csv_path)

    options = Options()
    if HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    log.info("Chrome 드라이버 준비 완료")

    try:
        driver.get(LOGIN_URL)
        wait.until(EC.visibility_of_element_located((By.ID, "email"))).send_keys(USER_ID)
        wait.until(EC.visibility_of_element_located((By.ID, "password"))).send_keys(USER_PW)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn.btn-primary"))).click()
        log.info("로그인 성공")
        time.sleep(PAGE_LOAD_WAIT)

        wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//ul[@id='tabmenu']/li[2]")
        )).click()
        log.info("대회 탭 이동 완료")
        time.sleep(PAGE_LOAD_WAIT)

        max_retries = 2
        saved_ranks: set[int] = set()
        for i in range(RANKS_TO_SCRAPE):
            for attempt in range(max_retries + 1):
                try:
                    ranking_table = wait.until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, "div.datagrid"))
                    )
                    success = _scrape_one_user(
                        driver, wait, ranking_table, i, csv_path, saved_ranks
                    )
                    if not success:
                        log.info("스크래핑 종료 (데이터 부족)")
                        return csv_path
                    break
                except StaleElementReferenceException:
                    if attempt < max_retries:
                        log.warning("  %d위 StaleElement — 재시도 (%d/%d)",
                                    i + 1, attempt + 1, max_retries)
                        time.sleep(1)
                    else:
                        log.error("  %d위 StaleElement — 건너뜀", i + 1)
                except TimeoutException:
                    if attempt < max_retries:
                        log.warning("  %d위 Timeout — 새로고침 후 재시도 (%d/%d)",
                                    i + 1, attempt + 1, max_retries)
                        driver.refresh()
                        time.sleep(PAGE_LOAD_WAIT + 2)
                        try:
                            wait.until(EC.element_to_be_clickable(
                                (By.XPATH, "//ul[@id='tabmenu']/li[2]")
                            )).click()
                            time.sleep(PAGE_LOAD_WAIT)
                        except Exception as nav_err:
                            log.warning("  대회 탭 재이동 실패: %s", nav_err)
                    else:
                        log.error("  %d위 Timeout — 재시도 초과, 건너뜀", i + 1)
                except Exception as e:
                    log.error("  %d위 예외: %s", i + 1, e)
                    break

    except Exception as e:
        log.exception("치명적 오류: %s", e)
        try:
            driver.save_screenshot("final_error.png")
            log.info("스크린샷 저장: final_error.png")
        except Exception:
            pass
    finally:
        driver.quit()
        log.info("완료. 저장 파일: %s", csv_path)

    return csv_path
