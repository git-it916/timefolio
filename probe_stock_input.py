"""
Probe: input[placeholder='종목 선택']에 직접 타이핑 후 팝업 확인.
"""

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


def ss(driver, name):
    driver.save_screenshot(os.path.join(SDIR, f"{name}.png"))


def main():
    options = Options()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
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

        # Click '신규 주문'
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if "신규" in btn.text and "주문" in btn.text:
                driver.execute_script("arguments[0].click();", btn)
                break
        time.sleep(2)
        print("New order dialog opened")
        ss(driver, "inp_01_dialog")

        # Find and interact with stock input
        stock_input = driver.find_element(By.CSS_SELECTOR, "input[placeholder='종목 선택']")
        print(f"Stock input found: displayed={stock_input.is_displayed()}, enabled={stock_input.is_enabled()}")
        print(f"  tag={stock_input.tag_name}, type={stock_input.get_attribute('type')}")
        print(f"  class={stock_input.get_attribute('class')}")
        print(f"  readonly={stock_input.get_attribute('readonly')}")
        print(f"  disabled={stock_input.get_attribute('disabled')}")

        # Try JavaScript click first
        driver.execute_script("arguments[0].focus();", stock_input)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", stock_input)
        time.sleep(1)
        ss(driver, "inp_02_after_focus")

        # Try typing with JavaScript (bypass readonly)
        driver.execute_script("""
            var el = arguments[0];
            el.value = '';
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        """, stock_input)
        time.sleep(0.5)

        # Try send_keys
        try:
            stock_input.send_keys("삼성")
            time.sleep(2)
            ss(driver, "inp_03_after_sendkeys")
            print(f"After send_keys: value='{stock_input.get_attribute('value')}'")
        except Exception as e:
            print(f"send_keys failed: {e}")
            # Try JS value set
            driver.execute_script("""
                var el = arguments[0];
                var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(el, '삼성');
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            """, stock_input)
            time.sleep(2)
            ss(driver, "inp_03_after_js_input")
            print(f"After JS input: value='{stock_input.get_attribute('value')}'")

        # Check for popup/dropdown/autocomplete
        print("\n--- After typing, checking for popups ---")

        # Check all visible elements containing search text
        results = driver.find_elements(By.XPATH, "//*[contains(text(), '삼성')]")
        for r in results:
            if r.is_displayed():
                print(f"  Match: tag={r.tag_name} class='{r.get_attribute('class') or ''}' text='{r.text.strip()[:60]}'")

        # Check for any new popover/dropdown
        for sel in ["[role='listbox']", "[role='option']", ".dropdown", ".popover",
                     "div.absolute", "div[class*='absolute']", "ul[class*='list']",
                     "div[class*='dropdown']", "div[class*='popup']", "div[class*='search']"]:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            visible = [e for e in elements if e.is_displayed()]
            if visible:
                for v in visible:
                    print(f"  Popup ({sel}): text='{v.text.strip()[:100]}'")

        # Maybe the green '종목 선택' is a button, not the input
        # Let's look for it more carefully
        print("\n--- Looking for green '종목 선택' button ---")
        # In the screenshot, it looks like a styled button/div
        greens = driver.find_elements(By.CSS_SELECTOR, "button, span, div, a")
        for g in greens:
            if g.is_displayed():
                text = g.text.strip()
                cls = g.get_attribute("class") or ""
                if text == "종목 선택" or (text == "종목 선택" and "green" in cls) or ("bg-green" in cls or "bg-teal" in cls or "bg-emerald" in cls):
                    tag = g.tag_name
                    print(f"  FOUND: tag={tag} text='{text}' class='{cls}'")
                    # Try clicking this element
                    driver.execute_script("arguments[0].click();", g)
                    time.sleep(2)
                    ss(driver, "inp_04_after_green_click")
                    print("  Clicked green element!")

                    # Check what appeared
                    new_dialogs = driver.find_elements(By.CSS_SELECTOR, "div[role='dialog']")
                    for d in new_dialogs:
                        if d.is_displayed():
                            inner = d.text.strip()[:500]
                            cls2 = d.get_attribute("class") or ""
                            print(f"  New dialog: class='{cls2}'")
                            print(f"  Content: {inner}")

                    # Check for new inputs
                    new_inputs = driver.find_elements(By.TAG_NAME, "input")
                    for ni in new_inputs:
                        if ni.is_displayed():
                            ph = ni.get_attribute("placeholder") or ""
                            ntype = ni.get_attribute("type") or ""
                            nid = ni.get_attribute("id") or ""
                            print(f"  Input: placeholder='{ph}' type='{ntype}' id='{nid}'")
                    break

        # Also check: maybe the input IS the selector and we just need to type properly
        # Let's try clicking the input area that's styled as green
        print("\n--- Trying all matching patterns ---")
        # Look for elements near the input
        parent = stock_input.find_element(By.XPATH, "./..")
        siblings = parent.find_elements(By.XPATH, "./*")
        for s in siblings:
            tag = s.tag_name
            text = s.text.strip()[:30]
            cls = s.get_attribute("class") or ""
            print(f"  Sibling: tag={tag} text='{text}' class='{cls}'")

        # Go up one more level
        grandparent = parent.find_element(By.XPATH, "./..")
        gp_children = grandparent.find_elements(By.XPATH, "./*")
        for gc in gp_children:
            tag = gc.tag_name
            text = gc.text.strip()[:30]
            cls = gc.get_attribute("class") or ""
            print(f"  GP child: tag={tag} text='{text}' class='{cls}'")
            if "종목" in text:
                inner_html = gc.get_attribute("innerHTML")[:300]
                print(f"    innerHTML: {inner_html}")

        ss(driver, "inp_05_final")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        ss(driver, "inp_error")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
