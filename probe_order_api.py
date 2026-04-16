"""
Probe: 주문 제출 API 엔드포인트 캡처.

실제로 소액 주문 1건을 제출하면서 네트워크 요청을 캡처한다.
비중 0.1%로 최소한의 영향만 줌.
"""

import json
import logging
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from timefolio.config import LOGIN_URL, PAGE_LOAD_WAIT, USER_ID, USER_PW, WAIT_TIMEOUT

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")


def main():
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        # 1. Login
        driver.get(LOGIN_URL)
        wait.until(EC.visibility_of_element_located((By.ID, "email"))).send_keys(USER_ID)
        wait.until(EC.visibility_of_element_located((By.ID, "password"))).send_keys(USER_PW)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn.btn-primary"))).click()
        time.sleep(PAGE_LOAD_WAIT)
        print("Login OK")

        # 2. Open new order form (already on 주문 tab)
        time.sleep(2)
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if "신규" in btn.text and "주문" in btn.text:
                driver.execute_script("arguments[0].click();", btn)
                break
        time.sleep(2)
        print("Order form opened")

        # 3. Select stock: 삼성전자
        stock_input = driver.find_element(By.CSS_SELECTOR, "input[placeholder='종목 선택']")
        driver.execute_script("arguments[0].focus();", stock_input)
        time.sleep(0.3)
        stock_input.send_keys("삼성전자")
        time.sleep(2)

        # Click first matching dropdown item
        matches = driver.find_elements(By.XPATH, "//*[contains(text(), '삼성전자')]")
        for m in matches:
            if m.is_displayed() and "[A" in m.text and "삼성전자" in m.text:
                driver.execute_script("arguments[0].click();", m)
                print(f"Selected: {m.text.strip()}")
                break
        time.sleep(1)

        # 4. Set buy mode (should be default)
        try:
            buy_radio = driver.find_element(By.ID, "매수도_true")
            driver.execute_script("arguments[0].click();", buy_radio)
        except Exception:
            pass

        # 5. Set weight to 0.1%
        number_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='number']")
        visible = [i for i in number_inputs if i.is_displayed()]
        if visible:
            visible[0].clear()
            visible[0].send_keys("0.1")
        print("Weight set to 0.1%")

        # 6. Flush network logs, then submit
        driver.get_log("performance")
        time.sleep(0.5)

        # Click submit
        submit_btn = driver.find_element(By.XPATH, "//button[contains(text(), '주문 제출')]")
        driver.execute_script("arguments[0].click();", submit_btn)
        print("ORDER SUBMITTED - capturing API...")
        time.sleep(3)

        # 7. Capture network
        logs = driver.get_log("performance")
        print(f"\n{'='*70}")
        print("  ORDER SUBMISSION API CALLS")
        print(f"{'='*70}")

        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
                method = msg.get("method", "")

                if method == "Network.requestWillBeSent":
                    params = msg.get("params", {})
                    req = params.get("request", {})
                    url = req.get("url", "")
                    http_method = req.get("method", "")
                    req_type = params.get("type", "")

                    if req_type in ("XHR", "Fetch") or "api" in url.lower():
                        post_data = req.get("postData", "")
                        headers = req.get("headers", {})
                        content_type = headers.get("Content-Type", "")
                        auth = headers.get("Authorization", "")[:60]
                        print(f"\n  -> {http_method} [{req_type}] {url}")
                        if content_type:
                            print(f"     Content-Type: {content_type}")
                        if auth:
                            print(f"     Auth: {auth}...")
                        if post_data:
                            print(f"     Body: {post_data[:500]}")

                elif method == "Network.responseReceived":
                    params = msg.get("params", {})
                    resp = params.get("response", {})
                    url = resp.get("url", "")
                    status = resp.get("status", 0)
                    if "api" in url.lower():
                        print(f"\n  <- {status} {url}")

            except Exception:
                continue

        # 8. Check for any error messages on the page
        print(f"\n{'='*70}")
        print("  PAGE STATE AFTER SUBMIT")
        print(f"{'='*70}")
        driver.save_screenshot("probe_screenshots/order_api_submit.png")

        # Check if order appeared in the error/pending table
        time.sleep(2)
        grids = driver.find_elements(By.CSS_SELECTOR, "div.datagrid")
        for gi, grid in enumerate(grids):
            rows = grid.find_elements(By.XPATH, ".//tbody/tr")
            if rows:
                tds = rows[0].find_elements(By.TAG_NAME, "td")
                td_texts = [td.text.strip()[:15] for td in tds[:8]]
                if any(t for t in td_texts):
                    print(f"  Grid[{gi}] first row: {td_texts}")

        print(f"\n{'='*70}")
        print("  DONE")
        print(f"{'='*70}")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        driver.save_screenshot("probe_screenshots/order_api_error.png")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
