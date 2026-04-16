"""
Probe: 타임폴리오 내부 API 엔드포인트 캡처.

브라우저 네트워크 로그를 캡처하여 주문/시세 관련 XHR/fetch 호출을 식별한다.
이 API를 직접 호출하면 Selenium 없이 밀리초 단위 주문이 가능.
"""

import json
import logging
import os
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
log = logging.getLogger(__name__)

SDIR = os.path.join(os.path.dirname(__file__), "probe_screenshots")
os.makedirs(SDIR, exist_ok=True)


def main():
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")

    # Performance logging 활성화 (네트워크 트래픽 캡처)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        # 1. 로그인
        print("=" * 70)
        print("  API ENDPOINT PROBE")
        print("=" * 70)

        driver.get(LOGIN_URL)
        wait.until(EC.visibility_of_element_located((By.ID, "email"))).send_keys(USER_ID)
        wait.until(EC.visibility_of_element_located((By.ID, "password"))).send_keys(USER_PW)

        # 로그인 전 네트워크 로그 비우기
        driver.get_log("performance")

        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn.btn-primary"))).click()
        time.sleep(PAGE_LOAD_WAIT)
        print("\n[1] LOGIN - capturing auth flow")

        # 로그인 관련 네트워크 호출 캡처
        _dump_network(driver, "LOGIN")

        # 2. 주문 탭 (기본 탭) - 시세/잔고 관련 API
        print("\n[2] ORDER TAB - capturing price/balance API")
        time.sleep(3)
        _dump_network(driver, "ORDER_TAB_LOAD")

        # 3. 대회 탭 이동 - 랭킹/포트폴리오 API
        print("\n[3] COMPETITION TAB - capturing ranking API")
        driver.get_log("performance")  # flush
        tabs = driver.find_elements(By.CSS_SELECTOR, "ul#tabmenu li")
        if len(tabs) >= 2:
            tabs[1].click()
            time.sleep(PAGE_LOAD_WAIT + 2)
        _dump_network(driver, "COMPETITION_TAB")

        # 4. 1위 포트폴리오 open - 포트폴리오 상세 API
        print("\n[4] OPEN PORTFOLIO - capturing portfolio detail API")
        driver.get_log("performance")  # flush
        ranking_table = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "div.datagrid"))
        )
        rows = ranking_table.find_elements(
            By.XPATH, ".//tbody/tr[starts-with(@style, 'position')]"
        )
        if rows:
            try:
                open_btn = rows[0].find_element(By.XPATH, ".//button[text()='open']")
                driver.execute_script("arguments[0].click();", open_btn)
                time.sleep(3)
            except Exception:
                pass
        _dump_network(driver, "PORTFOLIO_OPEN")

        # 모달 닫기
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ESCAPE)
            time.sleep(1)
        except Exception:
            pass

        # 5. 주문 탭으로 돌아와서 신규 주문 폼 열기
        print("\n[5] NEW ORDER FORM - capturing order API")
        tabs = driver.find_elements(By.CSS_SELECTOR, "ul#tabmenu li")
        if tabs:
            tabs[0].click()
            time.sleep(PAGE_LOAD_WAIT)

        driver.get_log("performance")  # flush
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if "신규" in btn.text and "주문" in btn.text:
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)
                break

        _dump_network(driver, "NEW_ORDER_FORM")

        # 6. 종목 검색 입력 - 검색 API
        print("\n[6] STOCK SEARCH - capturing search API")
        driver.get_log("performance")  # flush
        try:
            stock_input = driver.find_element(
                By.CSS_SELECTOR, "input[placeholder='종목 선택']"
            )
            driver.execute_script("arguments[0].focus();", stock_input)
            time.sleep(0.3)
            stock_input.send_keys("삼성")
            time.sleep(3)
        except Exception as e:
            print(f"  Stock input error: {e}")

        _dump_network(driver, "STOCK_SEARCH")

        # 7. WebSocket 연결 확인
        print("\n[7] WEBSOCKET CONNECTIONS")
        _check_websockets(driver)

        # 8. 쿠키/세션 정보
        print("\n[8] COOKIES & SESSION")
        cookies = driver.get_cookies()
        for c in cookies:
            print(f"  Cookie: {c['name']} = {c['value'][:50]}... (domain={c.get('domain', '')})")

        # 9. localStorage/sessionStorage
        print("\n[9] LOCAL/SESSION STORAGE")
        try:
            ls_keys = driver.execute_script(
                "return Object.keys(localStorage);"
            )
            for k in ls_keys:
                val = driver.execute_script(f"return localStorage.getItem('{k}');")
                if val:
                    print(f"  localStorage[{k}] = {str(val)[:100]}...")
        except Exception:
            pass

        try:
            ss_keys = driver.execute_script(
                "return Object.keys(sessionStorage);"
            )
            for k in ss_keys:
                val = driver.execute_script(f"return sessionStorage.getItem('{k}');")
                if val:
                    print(f"  sessionStorage[{k}] = {str(val)[:100]}...")
        except Exception:
            pass

        print("\n" + "=" * 70)
        print("  PROBE COMPLETE")
        print("=" * 70)

    except Exception as e:
        print(f"\nFATAL: {e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()


def _dump_network(driver, label: str):
    """Performance 로그에서 네트워크 요청을 추출."""
    logs = driver.get_log("performance")
    requests_found = []

    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            method = msg.get("method", "")

            # XHR/Fetch 요청 캡처
            if method == "Network.requestWillBeSent":
                params = msg.get("params", {})
                req = params.get("request", {})
                url = req.get("url", "")
                http_method = req.get("method", "")
                req_type = params.get("type", "")
                initiator = params.get("initiator", {}).get("type", "")

                # 관심 있는 요청만 (XHR, Fetch, WebSocket)
                if req_type in ("XHR", "Fetch", "WebSocket") or "api" in url.lower() or "graphql" in url.lower():
                    post_data = req.get("postData", "")
                    headers = req.get("headers", {})

                    requests_found.append({
                        "url": url,
                        "method": http_method,
                        "type": req_type,
                        "postData": post_data[:500] if post_data else "",
                        "content_type": headers.get("Content-Type", ""),
                        "auth": headers.get("Authorization", headers.get("authorization", ""))[:50],
                    })

            # 응답 캡처
            elif method == "Network.responseReceived":
                params = msg.get("params", {})
                resp = params.get("response", {})
                url = resp.get("url", "")
                status = resp.get("status", 0)
                mime = resp.get("mimeType", "")

                if any(kw in url.lower() for kw in ["api", "graphql", "ws", "socket"]):
                    requests_found.append({
                        "url": url,
                        "status": status,
                        "mime": mime,
                        "type": "RESPONSE",
                    })

            # WebSocket
            elif method in ("Network.webSocketCreated", "Network.webSocketFrameReceived"):
                params = msg.get("params", {})
                url = params.get("url", "")
                payload = params.get("response", {}).get("payloadData", "")[:200]
                requests_found.append({
                    "url": url or "websocket",
                    "type": "WebSocket",
                    "method": method.split(".")[-1],
                    "payload": payload,
                })

        except Exception:
            continue

    if requests_found:
        print(f"\n  [{label}] {len(requests_found)} API calls:")
        for r in requests_found:
            rtype = r.get("type", "")
            url = r.get("url", "")
            method = r.get("method", "")
            status = r.get("status", "")

            if rtype == "RESPONSE":
                print(f"    <- {status} {url[:120]}")
            elif rtype == "WebSocket":
                print(f"    WS {method}: {url[:120]}")
                if r.get("payload"):
                    print(f"       payload: {r['payload'][:150]}")
            else:
                print(f"    -> {method} [{rtype}] {url[:120]}")
                if r.get("postData"):
                    print(f"       body: {r['postData'][:200]}")
                if r.get("auth"):
                    print(f"       auth: {r['auth']}")
    else:
        print(f"\n  [{label}] No API calls captured")


def _check_websockets(driver):
    """WebSocket 연결 확인."""
    logs = driver.get_log("performance")
    ws_found = set()

    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            method = msg.get("method", "")

            if "webSocket" in method:
                params = msg.get("params", {})
                url = params.get("url", "")
                if url:
                    ws_found.add(url)

                payload = params.get("response", {}).get("payloadData", "")
                if payload:
                    print(f"  WS frame: {payload[:200]}")

        except Exception:
            continue

    if ws_found:
        for url in ws_found:
            print(f"  WebSocket URL: {url}")
    else:
        print("  No WebSocket connections found")


if __name__ == "__main__":
    main()
