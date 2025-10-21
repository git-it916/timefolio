import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException 

# --- 로그인 정보 ---
LOGIN_URL = "https://hankyung.timefolio.net/"
USER_ID = "shinshunghun0916@gmail.com"
USER_PW = "Tlstmdgns1!"

# 0. 웹 드라이버 설정
try:
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service)
    wait = WebDriverWait(driver, 20) # 대기 시간 20초
    print("Chrome 드라이버 설정 완료.")
except Exception as e:
    print(f"드라이버 설정 중 오류 발생: {e}")
    exit()

# 1. 페이지 접속 및 로그인
try:
    # 1. 페이지 접속
    print(f"{LOGIN_URL} 페이지에 접속합니다...")
    driver.get(LOGIN_URL)
    print("페이지 접속 완료.")

    # 2. 로그인 시도
    print("로그인을 시도합니다...")
    
    # E-mail 입력 (id='email')
    print("1. ID 입력 필드(id='email')를 찾는 중...")
    id_field = wait.until(EC.visibility_of_element_located((By.ID, "email")))
    id_field.send_keys(USER_ID)
    print("ID 입력 완료.")

    # PW 입력 (id='password')
    print("2. PW 입력 필드(id='password')를 찾는 중...")
    pw_field = wait.until(EC.visibility_of_element_located((By.ID, "password")))
    pw_field.send_keys(USER_PW)
    print("PW 입력 완료.")
    
    # Submit 버튼 클릭 (CSS Selector: .btn.btn-primary)
    css_selector_for_login = ".btn.btn-primary" 
    print(f"3. 로그인 버튼(CSS Selector='{css_selector_for_login}')을 찾는 중...")
    login_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector_for_login)))
    login_button.click()
    print("로그인 버튼 클릭 완료.")
    
    print("\n로그인 성공! 🤖")
    
    # -----------------------------------------------------------------
    # 3. "대회" 탭 (두 번째 탭) 클릭
    print("로그인 후 페이지 로딩을 3초 대기합니다...")
    time.sleep(3) 

    print("두 번째 메뉴 탭 (id='tabmenu'의 2번째 <li>)을 찾습니다...")
    second_menu_item = wait.until(EC.element_to_be_clickable((By.XPATH, "//ul[@id='tabmenu']/li[2]")))
    second_menu_item.click()
    print("두 번째 메뉴 탭 클릭 완료.")
    # -----------------------------------------------------------------

    