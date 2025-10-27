import time
import csv
import os
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains

# --- 설정 ---
LOGIN_URL = "https://hankyung.timefolio.net/"
USER_ID = "shinshunghun0916@gmail.com"
USER_PW = "Tlstmdgns1!"
DB_DIR = "database"
BASE_NAME = "portfolio"      # 결과: portfolio_YYYYMMDD_1.csv ...
RANKS_TO_SCRAPE = 50

_num_pat = re.compile(r"-?\d+(?:\.\d+)?")

def next_available_csv_path_by_date(db_dir: str, base_name: str) -> str:
    """같은 날짜(YYYYMMDD) 안에서 _1, _2 ...로 증가하는 파일 경로 생성"""
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
        print(f"'{db_dir}' 폴더가 생성되었습니다.")
    date_str = datetime.now().strftime("%Y%m%d")
    n = 1
    while True:
        candidate = os.path.join(db_dir, f"{base_name}_{date_str}_{n}.csv")
        if not os.path.exists(candidate):
            return candidate
        n += 1

# 실행 시점에 고정된 파일 경로를 하나 선택
CSV_PATH = next_available_csv_path_by_date(DB_DIR, BASE_NAME)

def setup_csv_storage():
    """CSV 헤더 생성"""
    with open(CSV_PATH, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "user_nick", "stock_name", "weight", "scraped_at"])
    print(f"'{CSV_PATH}' 파일과 헤더가 준비되었습니다.")

def _to_number_or_str(x: str):
    """'15.3%' -> 15.3 로 정규화. 숫자 없으면 빈문자열 유지"""
    if not x:
        return ""
    m = _num_pat.search(x.replace(",", ""))
    return float(m.group(0)) if m else ""

def _smart_text(el) -> str:
    """가능한 모든 경로로 텍스트를 최대한 확보"""
    if el is None:
        return ""
    # 1) .text
    t = (el.text or "").strip()
    if t:
        return t
    # 2) 흔히 쓰이는 속성들
    for attr in ("textContent", "innerText", "value", "aria-valuenow", "data-value"):
        v = el.get_attribute(attr)
        if v and v.strip():
            return v.strip()
    # 3) 자식 요소들(frozen/span/div)에만 값이 있을 수 있음
    for sel in (".frozen", "span", "div"):
        try:
            child = el.find_element(By.CSS_SELECTOR, sel)
            v = (child.get_attribute("textContent") or "").strip()
            if v:
                return v
        except NoSuchElementException:
            pass
    # 4) 마지막 수단: innerHTML에서 숫자만 추출
    html = el.get_attribute("innerHTML") or ""
    hm = _num_pat.search(html.replace(",", ""))
    return hm.group(0) if hm else ""

def save_portfolio_csv(rank, user_nick, portfolio_rows):
    """
    portfolio_rows: [(stock_name, weight_text), ...]
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rows = []
    for stock_name, weight_text in portfolio_rows:
        stock_name = (stock_name or "").strip()
        if not stock_name:
            continue
        weight_val = _to_number_or_str((weight_text or "").strip())
        rows.append((rank, user_nick, stock_name, weight_val, now))

    if not rows:
        print("  - 저장할 종목이 없습니다.")
        return

    with open(CSV_PATH, mode="a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    print(f"  - {rank}위 {user_nick}님의 포트폴리오 {len(rows)}개 항목 CSV 저장 완료.")

def run_scraper():
    setup_csv_storage()

    # 드라이버 설정
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service)
        wait = WebDriverWait(driver, 30)
        print("Chrome 드라이버 설정 완료.")
    except Exception as e:
        print(f"드라이버 설정 중 오류 발생: {e}")
        return

    try:
        # 로그인 및 대회 탭 이동
        print("자동 로그인을 시작합니다...")
        driver.get(LOGIN_URL)
        wait.until(EC.visibility_of_element_located((By.ID, "email"))).send_keys(USER_ID)
        wait.until(EC.visibility_of_element_located((By.ID, "password"))).send_keys(USER_PW)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn.btn-primary"))).click()
        print("로그인 성공.")

        time.sleep(3)

        print("두 번째 메뉴('대회') 탭으로 이동합니다...")
        wait.until(EC.element_to_be_clickable((By.XPATH, "//ul[@id='tabmenu']/li[2]"))).click()
        print("'대회' 탭으로 이동 완료.")
        time.sleep(3)

        # --- 1위부터 RANKS_TO_SCRAPE까지 순회 ---
        for i in range(RANKS_TO_SCRAPE):
            current_rank = i + 1
            print(f"\n{current_rank}위 사용자 데이터 추출을 시작합니다...")

            try:
                # 매번 목록 새로 수집 (stale 방지)
                ranking_table = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.datagrid")))
                rows = ranking_table.find_elements(By.XPATH, ".//tbody/tr[starts-with(@style, 'position')]")

                if i >= len(rows):
                    print("더 이상 랭킹 데이터가 없습니다. 스크랩을 종료합니다.")
                    break

                target_row = rows[i]
                user_nick = target_row.find_element(By.XPATH, ".//td[3]").text.strip()

                # 'open' 버튼 클릭
                open_button = target_row.find_element(By.XPATH, ".//button[text()='open']")
                ActionChains(driver).move_to_element(open_button).perform()
                driver.execute_script("arguments[0].click();", open_button)
                print(f" - {current_rank}위 {user_nick}님의 'open' 버튼 클릭.")

                # 모달 대기
                modal_selector = "dialog.dialog"
                modal = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, modal_selector)))
                print(" - 포트폴리오 창 확인.")

                # 헤더 닉네임 일치 확인
                modal_header_selector = (By.CSS_SELECTOR, "dialog.dialog header")
                wait.until(EC.text_to_be_present_in_element(modal_header_selector, user_nick))
                print(f" - 포트폴리오 헤더 '{user_nick}'님으로 변경 확인.")

                # '전체 보유 종목' datagrid(2) 우선, 없으면 datagrid(1) fallback
                grid_xpath_2 = "(.//div[contains(@class, 'datagrid')])[2]"
                grid_xpath_1 = "(.//div[contains(@class, 'datagrid')])[1]"

                grid_elems = modal.find_elements(By.XPATH, grid_xpath_2)
                grid = grid_elems[0] if grid_elems else modal.find_element(By.XPATH, grid_xpath_1)

                stock_rows = grid.find_elements(By.XPATH, ".//tbody/tr")
                if not stock_rows:
                    # 가상 렌더링 대비 잠깐 대기 후 재시도
                    time.sleep(0.5)
                    stock_rows = grid.find_elements(By.XPATH, ".//tbody/tr")
                
                portfolio_rows = []
                for stock_row in stock_rows:
                    tds = stock_row.find_elements(By.TAG_NAME, "td")
                    if len(tds) < 2:
                        continue

                    # 종목명: _prodNm 우선, 없으면 2번째 td
                    try:
                        name_td = stock_row.find_element(By.XPATH, ".//td[contains(@id,'_prodNm')]")
                    except NoSuchElementException:
                        name_td = tds[1]
                    stock_name = _smart_text(name_td).strip()
                    if not stock_name:
                        continue

                    # 비중: _wei가 td/자식 어디에 있든 잡기 → 비면 6번째 td 폴백
                    weight_text = ""
                    try:
                        wei_any = stock_row.find_element(By.XPATH, ".//*[contains(@id,'_wei')]")
                        weight_text = _smart_text(wei_any).strip()
                    except NoSuchElementException:
                        pass
                    if not weight_text and len(tds) >= 6:
                        weight_text = _smart_text(tds[5]).strip()

                    portfolio_rows.append((stock_name, weight_text))

                if portfolio_rows:
                    save_portfolio_csv(current_rank, user_nick, portfolio_rows)
                else:
                    print("  - 보유 종목이 없습니다.")

                # 모달 닫기
                close_button = modal.find_element(By.CSS_SELECTOR, "button.btn-close")
                driver.execute_script("arguments[0].click();", close_button)
                print(" - 포트폴리오 창 닫기 완료.")

                wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, modal_selector)))
                time.sleep(1)

            except StaleElementReferenceException:
                print(f"  - StaleElement 오류 발생. {current_rank}위 사용자를 건너뛰고 재시도합니다.")
                continue
            except TimeoutException:
                print(f"  - Timeout 오류: {current_rank}위 사용자의 요소를 찾는 데 시간이 초과되었습니다.")
                print("  - 페이지를 새로고침하고 5초 후 다음 사용자로 넘어갑니다.")
                driver.refresh()
                time.sleep(5)
                continue
            except Exception as e:
                print(f"  - {current_rank}위 사용자 처리 중 예상치 못한 오류 발생: {e}")
                continue

    except Exception as e:
        print(f"\n작업 중 오류가 발생했습니다: {e}")
        try:
            driver.save_screenshot('final_error.png')
            print("final_error.png 로 스크린샷 저장")
        except Exception:
            pass

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        print(f"\n모든 작업이 완료되었습니다. 브라우저를 종료합니다.\n저장 파일: {CSV_PATH}")

if __name__ == "__main__":
    run_scraper()
