import time
import sqlite3
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains

# --- 설정 ---
LOGIN_URL = "https://hankyung.timefolio.net/"
USER_ID = "shinshunghun0916@gmail.com"
USER_PW = "Tlstmdgns1!"
DB_NAME = "timefolio_data.db"
RANKS_TO_SCRAPE = 3 # 상위 몇 위까지 스크랩할지 설정

# --- 1. 데이터베이스 설정 ---
def setup_database():
    """데이터베이스 파일과 테이블을 초기화하는 함수"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rank INTEGER,
            user_nick TEXT,
            stock_name TEXT,
            scraped_at TEXT
        )
    ''')
    conn.commit()
    print(f"'{DB_NAME}' 데이터베이스가 준비되었습니다.")
    return conn

def save_portfolio(conn, rank, user_nick, portfolio_data):
    """추출한 포트폴리오 데이터를 DB에 저장하는 함수"""
    cur = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    for stock_name in portfolio_data:
        cur.execute('''
            INSERT INTO portfolio (rank, user_nick, stock_name, scraped_at)
            VALUES (?, ?, ?, ?)
        ''', (rank, user_nick, stock_name, today))
    
    conn.commit()
    print(f"  - {rank}위 {user_nick}님의 포트폴리오 {len(portfolio_data)}개 종목 DB 저장 완료.")

# --- 2. 셀레니움 스크립트 ---
def run_scraper():
    db_conn = setup_database()
    
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

        # --- 3. 1위부터 50위까지 순회 ---
        for i in range(RANKS_TO_SCRAPE):
            current_rank = i + 1
            print(f"\n{current_rank}위 사용자 데이터 추출을 시작합니다...")
            
            try:
                # stale element 오류를 피하기 위해 매번 랭킹 목록을 새로 찾음
                ranking_table = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.datagrid")))
                # [수정] style이 'position'으로 시작하는 tr(랭킹 행)만 선택
                rows = ranking_table.find_elements(By.XPATH, ".//tbody/tr[starts-with(@style, 'position')]")
                
                if i >= len(rows):
                    print("더 이상 랭킹 데이터가 없습니다. 스크랩을 종료합니다.")
                    break
                
                target_row = rows[i]

                # 등락이 파란색(순위 상승)인 경우만 제외
                rank_change_cell = target_row.find_element(By.XPATH, ".//td[2]")
                blue_rank_change = rank_change_cell.find_elements(By.XPATH, ".//span[contains(@style, 'color: blue')]")

                if blue_rank_change:
                    print(f" - {current_rank}위 사용자: 순위 상승. 건너뜁니다.")
                    continue
                
                print(f" - {current_rank}위 사용자: 순위 유지 또는 하락 확인. 포트폴리오를 확인합니다.")

                user_nick = target_row.find_element(By.XPATH, ".//td[3]").text
                
                # 'open' 버튼 클릭
                open_button = target_row.find_element(By.XPATH, ".//button[text()='open']")
                ActionChains(driver).move_to_element(open_button).perform()
                driver.execute_script("arguments[0].click();", open_button)
                print(f" - {current_rank}위 {user_nick}님의 'open' 버튼 클릭.")
                
                # 포트폴리오 모달(창)이 뜰 때까지 대기
                # [수정] dialog 태그를 직접 가리키도록 선택자 수정
                modal_selector = "dialog.dialog"
                modal = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, modal_selector)))
                print(" - 포트폴리오 창 확인.")
                
                # 모달 안의 '데이터 테이블'이 로드될 때까지 추가 대기
                modal_table_body_selector = ".//div[contains(@class, 'datagrid')]//tbody"
                wait.until(EC.presence_of_element_located((By.XPATH, modal_table_body_selector)))
                print(" - 포트폴리오 데이터 로드 확인.")

                portfolio_data = []
                stock_rows = modal.find_elements(By.XPATH, f"{modal_table_body_selector}/tr")
                
                for stock_row in stock_rows:
                    cols = stock_row.find_elements(By.TAG_NAME, "td")
                    # 두 번째 td(종목명)가 있는지 확인
                    if len(cols) > 1:
                        stock_name = cols[1].text
                        if stock_name: # 종목명이 비어있지 않으면 추가
                            portfolio_data.append(stock_name)

                if portfolio_data:
                    save_portfolio(db_conn, current_rank, user_nick, portfolio_data)
                else:
                    print("  - 보유 종목이 없습니다.")

                # 포트폴리오 모달 닫기 (btn-close 사용)
                close_button_selector = "button.btn-close"
                close_button = modal.find_element(By.CSS_SELECTOR, close_button_selector)
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
        driver.save_screenshot('final_error.png')
        print("final_error.png 로 스크린샷 저장")

    finally:
        db_conn.close()
        driver.quit()
        print("\n모든 작업이 완료되었습니다. 브라우저와 DB 연결을 종료합니다.")


# --- 스크립트 실행 ---
if __name__ == "__main__":
    run_scraper()