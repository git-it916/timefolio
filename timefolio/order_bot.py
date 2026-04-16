"""
타임폴리오 주문 자동화 봇.

Selenium으로 신규 주문 폼을 자동 조작한다.
모든 셀렉터는 probe.py로 실제 검증 완료.
"""

from __future__ import annotations

import csv
import logging
import os
import time
from datetime import datetime

from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from timefolio.config import (
    MAX_SINGLE_WEIGHT,
    ORDER_LOG_PATH,
    ORDER_SCREENSHOT_DIR,
    PAGE_LOAD_WAIT,
)

log = logging.getLogger(__name__)


class TimefolioOrderBot:
    """타임폴리오 주문 자동화."""

    def __init__(self, driver, wait: WebDriverWait):
        self.driver = driver
        self.wait = wait

    def _screenshot(self, name: str) -> str:
        os.makedirs(ORDER_SCREENSHOT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(ORDER_SCREENSHOT_DIR, f"{ts}_{name}.png")
        self.driver.save_screenshot(path)
        return path

    def _log_order(
        self, stock_name: str, weight: float, diff_pct: float,
        success: bool, dry_run: bool, note: str = "",
    ) -> None:
        os.makedirs(os.path.dirname(ORDER_LOG_PATH), exist_ok=True)
        is_new = not os.path.exists(ORDER_LOG_PATH)
        with open(ORDER_LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow([
                    "timestamp", "stock_name", "weight", "diff_pct",
                    "success", "dry_run", "note",
                ])
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                stock_name, weight, diff_pct, success, dry_run, note,
            ])

    def navigate_to_order_tab(self) -> None:
        """주문 탭(Tab[0])으로 이동."""
        tabs = self.driver.find_elements(By.CSS_SELECTOR, "ul#tabmenu li")
        if not tabs:
            raise RuntimeError("탭 메뉴를 찾을 수 없음")

        # Tab[0]이 주문 탭. 이미 선택되어 있을 수 있음.
        tabs[0].click()
        time.sleep(PAGE_LOAD_WAIT)
        log.info("주문 탭 이동 완료")

    def open_new_order_form(self) -> None:
        """'+ 신규 주문' 버튼 클릭."""
        buttons = self.driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            text = btn.text.strip()
            if "신규" in text and "주문" in text:
                self.driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)
                log.info("신규 주문 폼 열기 완료")
                return

        raise RuntimeError("'신규 주문' 버튼을 찾을 수 없음")

    def select_stock(self, stock_name: str) -> bool:
        """종목 자동완성으로 종목 선택.

        Returns:
            선택 성공 여부
        """
        try:
            stock_input = self.driver.find_element(
                By.CSS_SELECTOR, "input[placeholder='종목 선택']"
            )
        except NoSuchElementException:
            log.error("종목 선택 입력 필드를 찾을 수 없음")
            return False

        # 포커스 + 입력
        self.driver.execute_script("arguments[0].focus();", stock_input)
        time.sleep(0.3)
        stock_input.send_keys(stock_name)
        time.sleep(2)  # 드롭다운 출현 대기

        # 드롭다운에서 정확히 일치하는 항목 찾기
        # 드롭다운 항목은 stock_name을 포함하는 요소
        matches = self.driver.find_elements(
            By.XPATH,
            f"//*[contains(text(), '{stock_name}')]"
        )

        for match in matches:
            if not match.is_displayed():
                continue
            text = match.text.strip()
            # 드롭다운 항목 형식: "[A005930] 삼성전자 In"
            if stock_name in text and "[A" in text:
                self.driver.execute_script("arguments[0].click();", match)
                time.sleep(1)
                log.info("종목 선택 완료: %s → %s", stock_name, text)
                return True

        # 정확한 이름 매칭 실패 시, 첫 번째 매칭 항목 클릭
        for match in matches:
            if not match.is_displayed():
                continue
            tag = match.tag_name
            text = match.text.strip()
            # input이나 button이 아닌 실제 드롭다운 항목만
            if tag not in ("input", "button", "label") and stock_name in text:
                self.driver.execute_script("arguments[0].click();", match)
                time.sleep(1)
                log.info("종목 선택 (fallback): %s → %s", stock_name, text)
                return True

        log.warning("종목 '%s' 드롭다운에서 선택 실패", stock_name)
        # 입력 필드 정리
        stock_input.clear()
        stock_input.send_keys(Keys.ESCAPE)
        return False

    def set_buy(self) -> None:
        """매수 모드 설정."""
        try:
            buy_radio = self.driver.find_element(By.ID, "매수도_true")
            self.driver.execute_script("arguments[0].click();", buy_radio)
            log.debug("매수 모드 설정")
        except NoSuchElementException:
            log.warning("매수 라디오 버튼을 찾을 수 없음 (기본값 매수일 수 있음)")

    def set_weight(self, weight_pct: float) -> None:
        """주문 비중 설정."""
        capped = min(weight_pct, MAX_SINGLE_WEIGHT)

        # 매수도 라디오 다음의 number input 찾기
        number_inputs = self.driver.find_elements(
            By.CSS_SELECTOR, "input[type='number']"
        )
        visible_numbers = [inp for inp in number_inputs if inp.is_displayed()]

        if not visible_numbers:
            raise RuntimeError("비중 입력 필드를 찾을 수 없음")

        # 첫 번째 보이는 number input이 비중 필드
        weight_input = visible_numbers[0]
        weight_input.clear()
        weight_input.send_keys(str(capped))
        log.info("주문 비중 설정: %.1f%% (cap=%.1f%%)", capped, MAX_SINGLE_WEIGHT)

    def set_price_type(self, prc_type: str = "Opp") -> None:
        """가격 유형 설정. Opp=상대호가, My=자기호가, Limit=지정가, Stop=STOP."""
        try:
            radio = self.driver.find_element(By.ID, f"prcTy_{prc_type}")
            self.driver.execute_script("arguments[0].click();", radio)
        except NoSuchElementException:
            log.warning("가격 유형 '%s' 라디오를 찾을 수 없음", prc_type)

    def submit_order(self, dry_run: bool = True) -> bool:
        """주문 제출.

        dry_run=True: 스크린샷만 저장, 제출 안 함.
        """
        ss_path = self._screenshot("pre_submit")
        log.info("제출 직전 스크린샷: %s", ss_path)

        if dry_run:
            log.info("[DRY_RUN] 주문 제출 건너뜀")
            return True

        # 제출 버튼 클릭
        try:
            submit_btn = self.driver.find_element(
                By.XPATH, "//button[contains(text(), '주문 제출')]"
            )
            self.driver.execute_script("arguments[0].click();", submit_btn)
            time.sleep(2)
            self._screenshot("post_submit")
            log.info("주문 제출 완료")
            return True
        except NoSuchElementException:
            log.error("'주문 제출' 버튼을 찾을 수 없음")
            return False

    def close_form(self) -> None:
        """주문 폼 닫기."""
        try:
            close_btns = self.driver.find_elements(
                By.XPATH, "//button[contains(text(), '닫기')]"
            )
            for btn in close_btns:
                if btn.is_displayed():
                    btn.click()
                    time.sleep(1)
                    return
        except Exception:
            pass

        # ESC fallback
        try:
            body = self.driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ESCAPE)
            time.sleep(1)
        except Exception:
            pass

    def place_order(
        self,
        stock_name: str,
        weight: float,
        diff_pct: float = 0.0,
        dry_run: bool = True,
    ) -> bool:
        """전체 주문 플로우.

        Args:
            stock_name: 종목명
            weight: 주문 비중(%)
            diff_pct: 차익률(%) - 로깅용
            dry_run: True면 제출 안 함

        Returns:
            성공 여부
        """
        try:
            self.open_new_order_form()

            if not self.select_stock(stock_name):
                self.close_form()
                self._log_order(stock_name, weight, diff_pct, False, dry_run, "종목 선택 실패")
                return False

            self.set_buy()
            self.set_weight(weight)
            self.set_price_type("Opp")

            success = self.submit_order(dry_run)
            self.close_form()

            mode = "DRY_RUN" if dry_run else "LIVE"
            self._log_order(stock_name, weight, diff_pct, success, dry_run, mode)
            return success

        except Exception as e:
            log.error("주문 실패 (%s): %s", stock_name, e)
            self._screenshot("order_error")
            self.close_form()
            self._log_order(stock_name, weight, diff_pct, False, dry_run, str(e))
            return False
