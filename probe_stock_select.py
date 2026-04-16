"""
Timefolio 종목 선택 팝업 프로브.

신규 주문 폼에서 '종목 선택' 클릭 후 나타나는 팝업 구조를 확인한다.
읽기 전용 - 주문 제출 절대 안 함.
"""

import logging
import os
import time

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
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


def main() -> None:
    print("=" * 70)
    print("  PROBE: STOCK SELECTION POPUP")
    print("=" * 70)

    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        # 1. 로그인
        print("\n[1] LOGIN")
        driver.get(LOGIN_URL)
        wait.until(EC.visibility_of_element_located((By.ID, "email"))).send_keys(USER_ID)
        wait.until(EC.visibility_of_element_located((By.ID, "password"))).send_keys(USER_PW)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn.btn-primary"))).click()
        time.sleep(PAGE_LOAD_WAIT)
        print("  OK")

        # 2. 주문 탭은 기본 탭 (Tab[0])이므로 이미 주문 탭에 있음
        print("\n[2] ORDER TAB (default tab)")
        _screenshot(driver, "stock_01_order_tab")

        # 3. '+ 신규 주문' 버튼 찾기 및 클릭
        print("\n[3] CLICK '+ 신규 주문'")
        new_order_btn = None
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            text = btn.text.strip()
            if "신규" in text and "주문" in text:
                new_order_btn = btn
                print(f"  Found: '{text}'")
                break

        if not new_order_btn:
            # 링크나 다른 요소로 시도
            links = driver.find_elements(By.TAG_NAME, "a")
            for link in links:
                text = link.text.strip()
                if "신규" in text:
                    new_order_btn = link
                    print(f"  Found (link): '{text}'")
                    break

        if not new_order_btn:
            print("  ERROR: '신규 주문' 버튼을 찾을 수 없음")
            return

        driver.execute_script("arguments[0].click();", new_order_btn)
        time.sleep(2)
        _screenshot(driver, "stock_02_new_order_dialog")
        print("  OK - dialog opened")

        # 4. 종목 선택 영역 탐색
        print("\n[4] STOCK SELECTION AREA")

        # 방법 A: placeholder='종목 선택' input 찾기
        stock_inputs = driver.find_elements(By.CSS_SELECTOR, "input[placeholder='종목 선택']")
        print(f"  input[placeholder='종목 선택'] found: {len(stock_inputs)}")
        for i, inp in enumerate(stock_inputs):
            visible = inp.is_displayed()
            cls = inp.get_attribute("class") or ""
            print(f"    [{i}] visible={visible} | class='{cls}'")

        # 방법 B: '종목 선택' 텍스트가 있는 버튼/요소
        all_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '종목 선택') or contains(text(), '종목선택')]")
        print(f"\n  '종목 선택' 텍스트 포함 요소: {len(all_elements)}개")
        for i, el in enumerate(all_elements):
            tag = el.tag_name
            text = el.text.strip()[:50]
            cls = el.get_attribute("class") or ""
            visible = el.is_displayed()
            clickable = el.is_enabled()
            print(f"    [{i}] tag={tag} | text='{text}' | class='{cls}' | visible={visible} | enabled={clickable}")

        # 5. 종목 선택 버튼/인풋 클릭 시도
        print("\n[5] CLICKING STOCK SELECTION")
        clicked = False

        # 먼저 보이는 input 시도
        for inp in stock_inputs:
            if inp.is_displayed():
                driver.execute_script("arguments[0].click();", inp)
                time.sleep(2)
                _screenshot(driver, "stock_03_after_input_click")
                print("  Clicked input[placeholder='종목 선택']")
                clicked = True
                break

        if not clicked:
            # 녹색 버튼 등 클릭 가능한 요소 시도
            for el in all_elements:
                if el.is_displayed() and el.tag_name in ("button", "div", "span", "a"):
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(2)
                    _screenshot(driver, "stock_03_after_button_click")
                    print(f"  Clicked {el.tag_name} with '종목 선택'")
                    clicked = True
                    break

        if not clicked:
            print("  WARNING: Could not click stock selection element")

        # 6. 클릭 후 나타난 팝업/모달/드롭다운 확인
        print("\n[6] POPUP/MODAL AFTER CLICK")

        # 새 다이얼로그 확인
        dialogs = driver.find_elements(By.CSS_SELECTOR, "div[role='dialog'], .modal, [role='listbox']")
        for i, d in enumerate(dialogs):
            visible = d.is_displayed()
            cls = d.get_attribute("class") or ""
            role = d.get_attribute("role") or ""
            inner = d.text.strip()[:200]
            print(f"  Dialog[{i}]: role='{role}' | class='{cls}' | visible={visible}")
            if visible and inner:
                print(f"    text: {inner}")

        # 드롭다운/자동완성 확인
        dropdowns = driver.find_elements(By.CSS_SELECTOR, "[role='option'], .dropdown-item, .autocomplete-item, .suggestion, li[role='option']")
        if dropdowns:
            print(f"\n  Dropdown items: {len(dropdowns)}")
            for i, dd in enumerate(dropdowns[:10]):
                text = dd.text.strip()
                print(f"    [{i}] '{text}'")

        # datagrid 확인 (종목 검색용 테이블?)
        grids = driver.find_elements(By.CSS_SELECTOR, "div.datagrid")
        visible_grids = [g for g in grids if g.is_displayed()]
        print(f"\n  Visible datagrids: {len(visible_grids)}")
        for i, g in enumerate(visible_grids):
            headers = g.find_elements(By.CSS_SELECTOR, "thead th, thead td")
            h_texts = [h.text.strip() for h in headers]
            rows = g.find_elements(By.XPATH, ".//tbody/tr")
            print(f"  Grid[{i}]: headers={h_texts} | rows={len(rows)}")
            if rows:
                first_tds = rows[0].find_elements(By.TAG_NAME, "td")
                for j, td in enumerate(first_tds):
                    text = td.text.strip()[:50]
                    tid = td.get_attribute("id") or ""
                    print(f"    TD[{j}]: text='{text}' | id='{tid}'")

        # 7. 종목 검색 시도 (텍스트 입력)
        print("\n[7] STOCK SEARCH TEST")
        # 보이는 모든 input 중 text/search 타입 찾기
        visible_text_inputs = []
        all_inputs = driver.find_elements(By.TAG_NAME, "input")
        for inp in all_inputs:
            if inp.is_displayed():
                itype = inp.get_attribute("type") or "text"
                placeholder = inp.get_attribute("placeholder") or ""
                name = inp.get_attribute("name") or ""
                iid = inp.get_attribute("id") or ""
                if itype in ("text", "search"):
                    visible_text_inputs.append(inp)
                    print(f"  Visible text input: type={itype} | placeholder='{placeholder}' | name='{name}' | id='{iid}'")

        # 종목 관련 입력 필드에 '삼성전자' 입력 시도
        for inp in visible_text_inputs:
            placeholder = inp.get_attribute("placeholder") or ""
            if "종목" in placeholder or "검색" in placeholder or "stock" in placeholder.lower() or placeholder == "":
                print(f"\n  Typing '삼성전자' into: placeholder='{placeholder}'")
                inp.clear()
                inp.send_keys("")
                time.sleep(0.5)
                inp.send_keys("삼성")
                time.sleep(2)
                _screenshot(driver, "stock_04_after_typing")

                # 검색 결과 확인
                print("\n  After typing '삼성':")

                # 새로 나타난 팝업 확인
                new_popups = driver.find_elements(By.CSS_SELECTOR, "[role='listbox'], [role='option'], .search-results, .dropdown, ul, .popover, div[class*='absolute'], div[class*='fixed']")
                for p in new_popups:
                    if p.is_displayed() and p.text.strip():
                        text = p.text.strip()[:300]
                        cls = p.get_attribute("class") or ""
                        tag = p.tag_name
                        print(f"    Popup: tag={tag} | class='{cls}'")
                        print(f"    text: {text}")

                # datagrid에 변화가 있는지 확인
                for gi, g in enumerate(visible_grids):
                    try:
                        rows = g.find_elements(By.XPATH, ".//tbody/tr")
                        if rows:
                            print(f"\n    Grid[{gi}] rows after search: {len(rows)}")
                            for ri, row in enumerate(rows[:5]):
                                tds = row.find_elements(By.TAG_NAME, "td")
                                td_texts = [td.text.strip()[:20] for td in tds[:5]]
                                print(f"      Row[{ri}]: {td_texts}")
                    except Exception:
                        pass

                # 전체 입력 후 다시 확인
                inp.send_keys("전자")
                time.sleep(2)
                _screenshot(driver, "stock_05_full_search")

                # 최종 결과 확인
                all_visible = driver.find_elements(By.XPATH, "//*[contains(text(), '삼성전자')]")
                clickable_results = []
                for el in all_visible:
                    if el.is_displayed():
                        tag = el.tag_name
                        text = el.text.strip()[:50]
                        cls = el.get_attribute("class") or ""
                        parent_tag = ""
                        try:
                            parent = el.find_element(By.XPATH, "..")
                            parent_tag = parent.tag_name
                        except Exception:
                            pass
                        print(f"    Match: tag={tag} | parent={parent_tag} | text='{text}' | class='{cls}'")
                        clickable_results.append(el)

                # ESC로 정리
                inp.send_keys(Keys.ESCAPE)
                time.sleep(1)
                break

        # 8. 폼 닫기
        print("\n[8] CLOSING FORM")
        try:
            # 닫기 버튼 찾기
            close_btns = driver.find_elements(By.XPATH, "//button[contains(text(), '닫기')]")
            for btn in close_btns:
                if btn.is_displayed():
                    btn.click()
                    print("  Clicked '닫기' button")
                    break
            else:
                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.ESCAPE)
                print("  Pressed ESC")
        except Exception as e:
            print(f"  Close error: {e}")

        # 9. 주문 타겟 테이블의 '+' 버튼 구조
        print("\n[9] ORDER TARGET TABLE '+' BUTTON")
        time.sleep(1)
        _screenshot(driver, "stock_06_order_target")

        # + 버튼들 찾기
        plus_buttons = driver.find_elements(By.XPATH, "//button[text()='+'] | //td/button")
        visible_plus = [b for b in plus_buttons if b.is_displayed()]
        print(f"  Visible + buttons: {len(visible_plus)}")
        if visible_plus:
            # 첫 번째 + 버튼의 부모 행 확인
            try:
                first_plus = visible_plus[0]
                parent_row = first_plus.find_element(By.XPATH, "./ancestor::tr")
                tds = parent_row.find_elements(By.TAG_NAME, "td")
                td_texts = [td.text.strip()[:20] for td in tds]
                print(f"  First + row: {td_texts}")
                btn_text = first_plus.text.strip()
                btn_cls = first_plus.get_attribute("class") or ""
                print(f"  Button: text='{btn_text}' | class='{btn_cls}'")
            except Exception as e:
                print(f"  Error reading + button row: {e}")

        print("\n" + "=" * 70)
        print("  PROBE COMPLETE")
        print("=" * 70)
        _screenshot(driver, "stock_07_final")

    except Exception as e:
        print(f"\nFATAL: {e}")
        import traceback
        traceback.print_exc()
        _screenshot(driver, "stock_error")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
