"""
Timefolio 웹사이트 DOM 구조 프로브.

목적: 실제 UI 요소를 확인하여 차익거래 봇 구현에 필요한 셀렉터를 검증한다.
읽기 전용 — submit/확인 버튼은 절대 클릭하지 않음.
"""

import logging
import os
import time

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
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

from timefolio.config import LOGIN_URL, PAGE_LOAD_WAIT, USER_ID, USER_PW, WAIT_TIMEOUT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "probe_screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def _screenshot(driver, name: str) -> None:
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    driver.save_screenshot(path)
    log.info("  [screenshot] %s", path)


def _probe_tab_menu(driver) -> None:
    """프로브 1: ul#tabmenu 전체 탭 목록 덤프."""
    print("\n" + "=" * 70)
    print("  PROBE 1: TAB MENU STRUCTURE")
    print("=" * 70)

    try:
        tabs = driver.find_elements(By.CSS_SELECTOR, "ul#tabmenu li")
        if not tabs:
            # fallback: 다른 네비게이션 구조 탐색
            tabs = driver.find_elements(By.CSS_SELECTOR, "nav li, .tab-menu li, [role='tablist'] [role='tab']")
            print(f"  ul#tabmenu 없음. 대체 탐색 결과: {len(tabs)}개")

        for i, tab in enumerate(tabs):
            text = tab.text.strip().replace("\n", " ")
            cls = tab.get_attribute("class") or ""
            tag = tab.tag_name
            aria = tab.get_attribute("aria-selected") or ""
            data_state = tab.get_attribute("data-state") or ""
            print(f"  Tab[{i}]: text='{text}' | tag={tag} | class='{cls}' | aria-selected='{aria}' | data-state='{data_state}'")

        _screenshot(driver, "01_tab_menu")
    except Exception as e:
        print(f"  ERROR: {e}")


def _probe_modal_columns(driver, wait) -> None:
    """프로브 2: 1위 유저 포트폴리오 모달의 전체 컬럼 구조."""
    print("\n" + "=" * 70)
    print("  PROBE 2: PORTFOLIO MODAL COLUMN STRUCTURE")
    print("=" * 70)

    try:
        # 대회 탭으로 이동
        tabs = driver.find_elements(By.CSS_SELECTOR, "ul#tabmenu li")
        if len(tabs) >= 2:
            tabs[1].click()
            time.sleep(PAGE_LOAD_WAIT)
            print("  대회 탭 클릭 완료")
        _screenshot(driver, "02_competition_tab")

        # 랭킹 테이블 찾기
        ranking_table = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "div.datagrid"))
        )
        print("  랭킹 테이블 발견")

        # 랭킹 테이블 자체의 헤더 컬럼 확인
        print("\n  --- 랭킹 테이블 헤더 ---")
        headers = ranking_table.find_elements(By.CSS_SELECTOR, "thead th, thead td")
        for i, h in enumerate(headers):
            text = h.text.strip().replace("\n", " ")
            hid = h.get_attribute("id") or ""
            print(f"    Header[{i}]: text='{text}' | id='{hid}'")

        # 랭킹 테이블의 첫 번째 행 컬럼 확인
        print("\n  --- 랭킹 테이블 첫 번째 행 ---")
        first_rows = ranking_table.find_elements(
            By.XPATH, ".//tbody/tr[starts-with(@style, 'position')]"
        )
        if first_rows:
            tds = first_rows[0].find_elements(By.TAG_NAME, "td")
            for i, td in enumerate(tds):
                text = (td.text or "").strip().replace("\n", " ")
                tid = td.get_attribute("id") or ""
                cls = td.get_attribute("class") or ""
                inner = (td.get_attribute("textContent") or "").strip()[:50]
                print(f"    TD[{i}]: text='{text}' | id='{tid}' | class='{cls}' | textContent='{inner}'")

        # 1위 유저의 open 버튼 클릭
        if first_rows:
            try:
                open_btn = first_rows[0].find_element(By.XPATH, ".//button[text()='open']")
                ActionChains(driver).move_to_element(open_btn).perform()
                driver.execute_script("arguments[0].click();", open_btn)
                print("\n  1위 유저 'open' 버튼 클릭")
            except NoSuchElementException:
                # open 버튼이 없으면 행 자체를 클릭
                first_rows[0].click()
                print("\n  1위 유저 행 클릭 (open 버튼 없음)")

            # 모달 대기
            modal = wait.until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "div[role='dialog']"))
            )
            time.sleep(1)
            _screenshot(driver, "03_portfolio_modal")

            # 모달 헤더
            try:
                h2 = modal.find_element(By.CSS_SELECTOR, "h2")
                print(f"  모달 헤더: '{h2.text.strip()}'")
            except NoSuchElementException:
                print("  모달 헤더(h2) 없음")

            # 모달 내 데이터그리드 컬럼 구조
            print("\n  --- 모달 데이터그리드 헤더 ---")
            modal_grids = modal.find_elements(By.CSS_SELECTOR, "div.datagrid")
            for gi, grid in enumerate(modal_grids):
                print(f"\n  [Grid {gi}]")
                m_headers = grid.find_elements(By.CSS_SELECTOR, "thead th, thead td")
                for i, h in enumerate(m_headers):
                    text = h.text.strip().replace("\n", " ")
                    hid = h.get_attribute("id") or ""
                    print(f"    Header[{i}]: text='{text}' | id='{hid}'")

                # 첫 번째 종목 행의 모든 td
                print(f"\n  [Grid {gi}] 첫 번째 종목 행:")
                m_rows = grid.find_elements(By.XPATH, ".//tbody/tr")
                if m_rows:
                    tds = m_rows[0].find_elements(By.TAG_NAME, "td")
                    for i, td in enumerate(tds):
                        text = (td.text or "").strip().replace("\n", " ")
                        tid = td.get_attribute("id") or ""
                        cls = td.get_attribute("class") or ""
                        inner = (td.get_attribute("textContent") or "").strip()[:80]
                        print(f"    TD[{i}]: text='{text}' | id='{tid}' | class='{cls}' | textContent='{inner}'")

                    # 두 번째 행도 확인 (패턴 확인용)
                    if len(m_rows) >= 2:
                        print(f"\n  [Grid {gi}] 두 번째 종목 행:")
                        tds2 = m_rows[1].find_elements(By.TAG_NAME, "td")
                        for i, td in enumerate(tds2):
                            text = (td.text or "").strip().replace("\n", " ")
                            tid = td.get_attribute("id") or ""
                            inner = (td.get_attribute("textContent") or "").strip()[:80]
                            print(f"    TD[{i}]: text='{text}' | id='{tid}' | textContent='{inner}'")

            # 모달 닫기
            try:
                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.ESCAPE)
                WebDriverWait(driver, 5).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, "div[role='dialog']"))
                )
                print("\n  모달 닫기 완료 (ESC)")
            except Exception:
                driver.refresh()
                time.sleep(PAGE_LOAD_WAIT)
                print("\n  모달 닫기 실패 — 새로고침")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()


def _probe_order_tab(driver, wait) -> None:
    """프로브 3: 주문 탭 구조."""
    print("\n" + "=" * 70)
    print("  PROBE 3: ORDER TAB STRUCTURE")
    print("=" * 70)

    try:
        # 탭 메뉴에서 '주문' 탭 찾기
        tabs = driver.find_elements(By.CSS_SELECTOR, "ul#tabmenu li")
        order_tab = None
        order_tab_idx = None

        for i, tab in enumerate(tabs):
            text = tab.text.strip()
            if "주문" in text or "order" in text.lower() or "매매" in text:
                order_tab = tab
                order_tab_idx = i
                print(f"  주문 탭 발견: Tab[{i}] = '{text}'")
                break

        if order_tab is None:
            print("  주문 탭을 찾을 수 없음. 모든 탭 텍스트:")
            for i, tab in enumerate(tabs):
                print(f"    Tab[{i}]: '{tab.text.strip()}'")
            # 다른 곳에서 주문 관련 요소 탐색
            print("\n  주문 관련 버튼/링크 전체 탐색:")
            all_buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in all_buttons:
                text = btn.text.strip()
                if any(kw in text for kw in ["주문", "매수", "매도", "신규", "order"]):
                    cls = btn.get_attribute("class") or ""
                    print(f"    Button: text='{text}' | class='{cls}'")
            return

        # 주문 탭 클릭
        order_tab.click()
        time.sleep(PAGE_LOAD_WAIT)
        _screenshot(driver, "04_order_tab")
        print(f"  주문 탭 클릭 완료 (index={order_tab_idx})")

        # 주문 탭 내부 전체 구조 덤프
        print("\n  --- 주문 탭: 모든 버튼 ---")
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for i, btn in enumerate(buttons):
            text = btn.text.strip()
            if text:  # 빈 버튼 제외
                cls = btn.get_attribute("class") or ""
                bid = btn.get_attribute("id") or ""
                print(f"    Button[{i}]: text='{text}' | id='{bid}' | class='{cls}'")

        print("\n  --- 주문 탭: 모든 input ---")
        inputs = driver.find_elements(By.TAG_NAME, "input")
        for i, inp in enumerate(inputs):
            itype = inp.get_attribute("type") or ""
            placeholder = inp.get_attribute("placeholder") or ""
            iid = inp.get_attribute("id") or ""
            name = inp.get_attribute("name") or ""
            cls = inp.get_attribute("class") or ""
            print(f"    Input[{i}]: type='{itype}' | placeholder='{placeholder}' | id='{iid}' | name='{name}' | class='{cls}'")

        print("\n  --- 주문 탭: select 요소 ---")
        selects = driver.find_elements(By.TAG_NAME, "select")
        for i, sel in enumerate(selects):
            sid = sel.get_attribute("id") or ""
            name = sel.get_attribute("name") or ""
            options = sel.find_elements(By.TAG_NAME, "option")
            opts_text = [o.text.strip() for o in options[:5]]
            print(f"    Select[{i}]: id='{sid}' | name='{name}' | options={opts_text}")

        # 데이터그리드 (기존 주문 목록?)
        print("\n  --- 주문 탭: 데이터그리드 ---")
        grids = driver.find_elements(By.CSS_SELECTOR, "div.datagrid, table")
        for i, grid in enumerate(grids):
            headers = grid.find_elements(By.CSS_SELECTOR, "thead th, thead td")
            h_texts = [h.text.strip() for h in headers]
            print(f"    Grid[{i}]: headers={h_texts}")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()


def _probe_new_order_form(driver, wait) -> None:
    """프로브 4: + 신규주문 버튼 클릭 후 폼 구조 (제출 버튼 절대 클릭 안 함)."""
    print("\n" + "=" * 70)
    print("  PROBE 4: NEW ORDER FORM STRUCTURE")
    print("=" * 70)

    try:
        # '+ 신규주문' 또는 유사한 버튼 찾기
        new_order_btn = None
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            text = btn.text.strip()
            if "신규" in text or "새 주문" in text or "+ " in text or "추가" in text:
                new_order_btn = btn
                print(f"  '신규주문' 버튼 발견: text='{text}'")
                break

        if new_order_btn is None:
            print("  '신규주문' 버튼을 찾을 수 없음.")
            print("  현재 페이지의 모든 버튼:")
            for btn in buttons:
                text = btn.text.strip()
                if text:
                    print(f"    '{text}'")
            return

        # 신규주문 버튼 클릭
        driver.execute_script("arguments[0].click();", new_order_btn)
        time.sleep(2)
        _screenshot(driver, "05_new_order_form")
        print("  신규주문 버튼 클릭 완료")

        # 새로 나타난 모달/폼 확인
        print("\n  --- 주문 폼: 모달/다이얼로그 ---")
        dialogs = driver.find_elements(By.CSS_SELECTOR, "div[role='dialog'], .modal, .popup, div.fixed")
        for i, d in enumerate(dialogs):
            cls = d.get_attribute("class") or ""
            role = d.get_attribute("role") or ""
            visible = d.is_displayed()
            print(f"    Dialog[{i}]: role='{role}' | class='{cls}' | visible={visible}")

        # 폼 내부 구조
        print("\n  --- 주문 폼: input 필드 ---")
        inputs = driver.find_elements(By.TAG_NAME, "input")
        for i, inp in enumerate(inputs):
            if not inp.is_displayed():
                continue
            itype = inp.get_attribute("type") or ""
            placeholder = inp.get_attribute("placeholder") or ""
            iid = inp.get_attribute("id") or ""
            name = inp.get_attribute("name") or ""
            label_text = ""
            # 가까운 label 찾기
            try:
                parent = inp.find_element(By.XPATH, "./..")
                labels = parent.find_elements(By.TAG_NAME, "label")
                if labels:
                    label_text = labels[0].text.strip()
            except Exception:
                pass
            print(f"    Input[{i}]: type='{itype}' | placeholder='{placeholder}' | id='{iid}' | name='{name}' | label='{label_text}'")

        print("\n  --- 주문 폼: 보이는 버튼 ---")
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for i, btn in enumerate(buttons):
            if not btn.is_displayed():
                continue
            text = btn.text.strip()
            if text:
                cls = btn.get_attribute("class") or ""
                bid = btn.get_attribute("id") or ""
                disabled = btn.get_attribute("disabled") or ""
                btype = btn.get_attribute("type") or ""
                print(f"    Button[{i}]: text='{text}' | id='{bid}' | class='{cls}' | type='{btype}' | disabled='{disabled}'")

        print("\n  --- 주문 폼: select/dropdown ---")
        selects = driver.find_elements(By.TAG_NAME, "select")
        for i, sel in enumerate(selects):
            if not sel.is_displayed():
                continue
            sid = sel.get_attribute("id") or ""
            options = sel.find_elements(By.TAG_NAME, "option")
            opts_text = [o.text.strip() for o in options[:10]]
            print(f"    Select[{i}]: id='{sid}' | options={opts_text}")

        # Radix UI 커스텀 select (button[role='combobox']) 확인
        print("\n  --- 주문 폼: 커스텀 드롭다운 (Radix/Headless) ---")
        combos = driver.find_elements(By.CSS_SELECTOR, "[role='combobox'], [role='listbox'], [data-radix-select-trigger]")
        for i, c in enumerate(combos):
            text = c.text.strip()
            cls = c.get_attribute("class") or ""
            role = c.get_attribute("role") or ""
            print(f"    Combo[{i}]: text='{text}' | role='{role}' | class='{cls}'")

        # 종목 검색 테스트 (입력만, 제출 안 함)
        print("\n  --- 종목 입력 테스트 ---")
        visible_inputs = [inp for inp in driver.find_elements(By.TAG_NAME, "input") if inp.is_displayed()]
        for inp in visible_inputs:
            placeholder = inp.get_attribute("placeholder") or ""
            iid = inp.get_attribute("id") or ""
            if any(kw in placeholder for kw in ["종목", "검색", "stock", "search"]) or any(kw in iid for kw in ["stock", "prod", "search"]):
                print(f"  종목 입력 필드 발견: placeholder='{placeholder}' | id='{iid}'")
                # 테스트 입력
                inp.clear()
                inp.send_keys("삼성전자")
                time.sleep(2)
                _screenshot(driver, "06_stock_search_popup")

                # 팝업/자동완성 확인
                popups = driver.find_elements(By.CSS_SELECTOR, "[role='listbox'], [role='option'], .autocomplete, .search-result, .dropdown-menu, ul.suggestions")
                if popups:
                    for pi, p in enumerate(popups):
                        ptext = p.text.strip()[:200]
                        pcls = p.get_attribute("class") or ""
                        print(f"    Popup[{pi}]: class='{pcls}' | text='{ptext}'")
                else:
                    # 더 넓은 범위로 탐색
                    new_elements = driver.find_elements(By.CSS_SELECTOR, "div[style*='position: absolute'], div[style*='position: fixed'], .popup, .popover")
                    for ne in new_elements:
                        if ne.is_displayed() and ne.text.strip():
                            print(f"    NewElement: class='{ne.get_attribute('class')}' | text='{ne.text.strip()[:200]}'")

                # 입력 지우기
                inp.clear()
                inp.send_keys(Keys.ESCAPE)
                break

        _screenshot(driver, "07_order_form_final")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()


def main() -> None:
    print("=" * 70)
    print("  TIMEFOLIO WEBSITE DOM PROBE")
    print("  읽기 전용 — submit 버튼 클릭 없음")
    print("=" * 70)

    options = Options()
    # 화면 표시 모드 (headless 아님)
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        # 로그인
        print("\n[LOGIN]")
        driver.get(LOGIN_URL)
        wait.until(EC.visibility_of_element_located((By.ID, "email"))).send_keys(USER_ID)
        wait.until(EC.visibility_of_element_located((By.ID, "password"))).send_keys(USER_PW)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn.btn-primary"))).click()
        time.sleep(PAGE_LOAD_WAIT)
        print("  로그인 성공")
        _screenshot(driver, "00_after_login")

        # 프로브 1: 탭 메뉴
        _probe_tab_menu(driver)

        # 프로브 2: 포트폴리오 모달 컬럼
        _probe_modal_columns(driver, wait)

        # 프로브 3: 주문 탭
        _probe_order_tab(driver, wait)

        # 프로브 4: 신규주문 폼
        _probe_new_order_form(driver, wait)

        print("\n" + "=" * 70)
        print("  PROBE COMPLETE")
        print("=" * 70)

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        _screenshot(driver, "error_fatal")
    finally:
        input("\n[Enter를 누르면 브라우저를 닫습니다...]")
        driver.quit()


if __name__ == "__main__":
    main()
