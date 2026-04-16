"""
CDP 기반 주문 API 캡처.
실제 주문을 Selenium으로 제출하면서 Chrome DevTools Protocol로
정확한 request body를 캡처한다.
"""

import json
import logging
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
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
        # Login
        driver.get(LOGIN_URL)
        wait.until(EC.visibility_of_element_located((By.ID, "email"))).send_keys(USER_ID)
        wait.until(EC.visibility_of_element_located((By.ID, "password"))).send_keys(USER_PW)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn.btn-primary"))).click()
        time.sleep(PAGE_LOAD_WAIT)
        print("Login OK")

        # Open new order
        time.sleep(2)
        for btn in driver.find_elements(By.TAG_NAME, "button"):
            if "신규" in btn.text and "주문" in btn.text:
                driver.execute_script("arguments[0].click();", btn)
                break
        time.sleep(2)
        print("Order form opened")

        # Select stock via autocomplete
        stock_input = driver.find_element(By.CSS_SELECTOR, "input[placeholder='종목 선택']")
        driver.execute_script("arguments[0].focus();", stock_input)
        time.sleep(0.3)
        stock_input.send_keys("삼성전자")
        time.sleep(3)

        # Click matching item
        for m in driver.find_elements(By.XPATH, "//*[contains(text(), '삼성전자')]"):
            if m.is_displayed() and "[A" in m.text:
                driver.execute_script("arguments[0].click();", m)
                print(f"Selected: {m.text.strip()}")
                time.sleep(1)
                break

        # Set weight
        numbers = [i for i in driver.find_elements(By.CSS_SELECTOR, "input[type='number']") if i.is_displayed()]
        if numbers:
            numbers[0].clear()
            numbers[0].send_keys("0.1")
        print("Weight set")

        # Take screenshot before submit
        driver.save_screenshot("probe_screenshots/cdp_pre_submit.png")

        # Inject XHR interceptor BEFORE clicking submit
        driver.execute_script("""
            window.__captured_requests = [];
            const origOpen = XMLHttpRequest.prototype.open;
            const origSend = XMLHttpRequest.prototype.send;
            const origFetch = window.fetch;

            XMLHttpRequest.prototype.open = function(method, url) {
                this.__url = url;
                this.__method = method;
                return origOpen.apply(this, arguments);
            };
            XMLHttpRequest.prototype.send = function(body) {
                window.__captured_requests.push({
                    type: 'XHR',
                    method: this.__method,
                    url: this.__url,
                    body: body,
                    timestamp: Date.now()
                });
                return origSend.apply(this, arguments);
            };

            window.fetch = function(url, opts) {
                window.__captured_requests.push({
                    type: 'Fetch',
                    method: (opts && opts.method) || 'GET',
                    url: typeof url === 'string' ? url : url.url,
                    body: opts && opts.body,
                    headers: opts && opts.headers,
                    timestamp: Date.now()
                });
                return origFetch.apply(this, arguments);
            };
            console.log('XHR/Fetch interceptor installed');
        """)
        print("XHR interceptor installed")

        # Flush performance log
        driver.get_log("performance")

        # Click submit
        try:
            submit_btn = driver.find_element(By.XPATH, "//button[contains(text(), '주문 제출')]")
            driver.execute_script("arguments[0].click();", submit_btn)
            print("SUBMIT CLICKED!")
        except Exception as e:
            # Try finding by partial text
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                if btn.is_displayed() and "제출" in btn.text:
                    driver.execute_script("arguments[0].click();", btn)
                    print(f"SUBMIT CLICKED (fallback): {btn.text}")
                    break
            else:
                print(f"Submit button not found: {e}")
                # List all visible buttons
                for btn in driver.find_elements(By.TAG_NAME, "button"):
                    if btn.is_displayed() and btn.text.strip():
                        print(f"  Button: '{btn.text.strip()}'")

        time.sleep(3)
        driver.save_screenshot("probe_screenshots/cdp_post_submit.png")

        # Capture intercepted requests
        print(f"\n{'='*70}")
        print("  CAPTURED XHR/FETCH REQUESTS")
        print(f"{'='*70}")

        captured = driver.execute_script("return window.__captured_requests || [];")
        for req in captured:
            print(f"\n  {req.get('type')} {req.get('method')} {req.get('url')}")
            body = req.get('body')
            if body:
                try:
                    parsed = json.loads(body) if isinstance(body, str) else body
                    print(f"  BODY: {json.dumps(parsed, indent=2, ensure_ascii=False)}")
                except (json.JSONDecodeError, TypeError):
                    print(f"  BODY (raw): {body[:500]}")
            hdrs = req.get('headers')
            if hdrs:
                print(f"  HEADERS: {json.dumps(dict(hdrs) if not isinstance(hdrs, dict) else hdrs, indent=2)}")

        # Also check performance log
        print(f"\n{'='*70}")
        print("  PERFORMANCE LOG")
        print(f"{'='*70}")

        logs = driver.get_log("performance")
        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
                method = msg.get("method", "")
                if method == "Network.requestWillBeSent":
                    params = msg.get("params", {})
                    req = params.get("request", {})
                    url = req.get("url", "")
                    if "api" in url.lower() and "Order" in url:
                        print(f"\n  -> {req.get('method')} {url}")
                        if req.get('postData'):
                            print(f"  Body: {req['postData'][:800]}")
                elif method == "Network.responseReceived":
                    params = msg.get("params", {})
                    resp = params.get("response", {})
                    url = resp.get("url", "")
                    if "api" in url.lower() and "Order" in url:
                        print(f"\n  <- {resp.get('status')} {url}")
            except Exception:
                continue

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        driver.save_screenshot("probe_screenshots/cdp_error.png")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
