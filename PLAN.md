# Timefolio 차익거래 봇 구현 계획 (PLAN.md)

## 1. Context

타임폴리오(한경 모의투자대회, hankyung.timefolio.net) 웹사이트에 표시되는 종목 현재가와 한국투자증권(KIS) Open API의 실시간 가격 사이에 괴리가 존재한다. 이 가격 차이를 감지하여, 타임폴리오에서 저평가된 종목을 자동 매수함으로써 대회 내 수익률 우위를 확보하는 봇을 구현한다.

공매도가 불가하므로 **타임폴리오 가격 < KIS 실시간 가격**인 종목만 롱(매수) 진입한다.

---

## 2. Selenium 프로브로 확인한 사실 (Ground Truth)

### 2.1 탭 메뉴 구조
```
ul#tabmenu li:
  [0] 주문    ← 기본 탭 (로그인 후 랜딩), XPath li[1]
  [1] 대회    ← 기존 스크래퍼 사용 중, XPath li[2]  
  [2] 복기
  [3] 게시판
  [4] 설정
```

### 2.2 포트폴리오 모달 컬럼 (대회 탭 → 유저 open)
```
모달: div[role='dialog']
데이터그리드: div.datagrid 내부 tbody/tr

TD[0]  td[id$='_prodId']    종목코드    "A005930" (A + 6자리)
TD[1]  td[id$='_prodNm']    종목명      "삼성전자"
TD[2]  td[id$='_close']     현재가      "217,000"
TD[3]  td[id$='_chPct']     당일등락%   "2.7"
TD[4]  td[id$='_pos']       잔고(수량)  "2,079"
TD[5]  td[id$='_wei']       비중%       "34.0"
TD[6]  td[id$='_posAmt']    평가액(만원) "45,114"
TD[7]  td[id$='_avgPrc']    평단가
TD[8]  td[id$='_prftRate']  수익률%
TD[9]  td[id$='_prftAmt']   수익(만원)
```
**핵심**: 종목코드(`A005930`)가 모달에서 직접 제공됨. `A` 접두사 제거 → KIS API 코드. **별도 종목 매퍼 불필요.**

### 2.3 주문 탭 구조 (Tab[0])
```
주문 탭 상단:
  - NAV, 순위, KOSPI/KOSDAQ 지수

미접수/에러 주문:
  Grid headers: 종목코드, 종목명, 조건, 시간, 상태, 정정, 취소

주문 타겟:
  버튼: "+ 신규 주문" (class='px-2 py-1 rounded bg-gray-600 text-white...')

보유 잔고 테이블:
  Grid headers: 코드, 종목명, 현재가, 당일%, 전일(비중), 주문, 미체결, 타겟, (만원), 추가
  예시 행:
    A082920 | 비츠로셀 | 52,500 | 4.17 | 15.4 | 0 | 16.1 | 719
    A007810 | 코리아써키트 | 89,000 | 2.42 | 13.8 | 0 | 14.1 | 374
```

### 2.4 신규 주문 폼 (확인된 셀렉터)
```
폼 모달: div[role='dialog'] (class에 'fixed', 'z-50', 'bg-white' 포함)

필드 순서:
  1. 주문 기준일: input[name='d'] (자동 채워짐)
  2. 종목 선택:   input[placeholder='종목 선택']
                   → 타이핑 시 자동완성 드롭다운 출현
                   → 항목 형식: "[A028050] 삼성E&A In"
                   → 클릭하여 선택
  3. 매수/매도:   input[id='매수도_true'] (매수) / input[id='매수도_false'] (매도)
  4. 주문 비중(%): input[type='number'] (매수도 라디오 다음의 첫 번째 number input)
  5. 가격 유형:   input[id='prcTy_Opp'] (상대호가, 기본값)
                   input[id='prcTy_My']  (자기호가)
                   input[id='prcTy_Limit'] (지정가)
                   input[id='prcTy_Stop']  (STOP)
  6. 상대호가 틱: input[type='number'] (기본값 5, 1~10)
  7. 실행 방식:   input[id='isSlice_false'] (즉시 실행, 기본값)
                   input[id='isSlice_true']  (시간 분할)
  8. 주문 시작:   input[id='hm0'] (한국 시간, 자동 채워짐)

버튼:
  - "닫기": X 닫기 버튼 (XPath: //button[contains(text(), '닫기')])
  - "주문 제출": 최종 제출 버튼 (XPath: //button[contains(text(), '주문 제출')])
```

### 2.5 종목 자동완성 드롭다운 (스크린샷 확인)
```
input[placeholder='종목 선택']에 "삼성" 입력 시 드롭다운 출현:
  [A028050] 삼성E&A In
  [A006400] 삼성SDI IT
  [A006660] 삼성공조 CD
  [A028260] 삼성물산 In
  [A207940] 삼성바이오로직
  [A032830] 삼성생명 FI
  [A018260] 삼성에스디에스 IT

형식: [A{6자리코드}] {종목명} {섹터약어}
선택: 드롭다운 항목 클릭 → "종목 미선택" 텍스트가 선택된 종목으로 변경
```

---

## 3. 기존 코드 자산

| 파일 | 재사용할 것 |
|------|-----------|
| `timefolio/scraper.py` | 로그인, 대회 탭 네비게이션, 모달 열기/닫기, 가상스크롤, CSV 저장 패턴 |
| `timefolio/config.py` | .env 기반 설정, 경로/임계값 관리 패턴 |
| `timefolio/notifier.py` | 텔레그램 MarkdownV2 전송 패턴 |
| `timefolio/analyzer.py` | 데이터 모델 패턴 (frozen dataclass) |
| `strategy_ensemble/.../kis_api.py` | KIS API 래퍼 (get_price, buy_stock, OAuth) |
| `strategy_ensemble/config/keys.yaml` | KIS 인증정보 (app_key, app_secret, account_number) |

---

## 4. 구현 계획

### Phase 1: KIS API 통합 + 설정 확장

**목적**: KIS 실시간 가격 조회 기능을 timefolio 프로젝트에 추가

**파일 변경**:

1. **`timefolio/kis_api.py`** (새 파일 - `strategy_ensemble`에서 복사 + 경량화)
   - `KISAuth`, `KISApi` 클래스 복사
   - 이 프로젝트에서 필요한 메서드만 유지: `get_price()`, `_refresh_token()`, `_get_headers()`
   - 매수/매도/잔고 메서드는 불필요 (타임폴리오 주문은 Selenium으로)

2. **`timefolio/config.py`** (수정)
   ```python
   # 추가할 설정
   KIS_APP_KEY: str = os.getenv("KIS_APP_KEY", "")
   KIS_APP_SECRET: str = os.getenv("KIS_APP_SECRET", "")
   KIS_ACCOUNT: str = os.getenv("KIS_ACCOUNT", "")
   KIS_IS_PAPER: bool = os.getenv("KIS_IS_PAPER", "true").lower() in ("true", "1")
   
   MIN_ARB_PCT: float = float(os.getenv("MIN_ARB_PCT", "0.5"))     # 최소 차익 %
   MAX_SINGLE_WEIGHT: float = float(os.getenv("MAX_SINGLE_WEIGHT", "15.0"))
   ARB_TOP_N: int = int(os.getenv("ARB_TOP_N", "5"))               # 상위 N명
   ARB_DRY_RUN: bool = os.getenv("ARB_DRY_RUN", "true").lower() in ("true", "1")
   ```

3. **`.env`** (수정 - KIS 인증정보 추가)
   ```
   KIS_APP_KEY=PSCshVVXCPUsP6jzNm6u10S2jmC9GSb4p2tq
   KIS_APP_SECRET=GQIQQJAgRM...
   KIS_ACCOUNT=43984255
   KIS_IS_PAPER=true
   ARB_DRY_RUN=true
   ```

4. **`requirements.txt`** (수정)
   ```
   requests    # KIS API HTTP 호출용 (추가)
   pyyaml      # keys.yaml 로드 대안 (선택)
   ```

---

### Phase 2: 가격 스크래핑 확장

**목적**: 기존 스크래퍼에서 종목코드 + 현재가를 추가 추출

**파일 변경**:

1. **`timefolio/scraper.py`** (수정)

   `_scrape_one_user()` 함수 변경:
   ```python
   # 기존: portfolio.append((stock_name, weight_text))
   # 변경: portfolio.append((stock_code, stock_name, price_text, weight_text))
   
   # 종목코드 추출
   try:
       code_td = stock_row.find_element(By.CSS_SELECTOR, "td[id$='_prodId']")
       stock_code = _smart_text(code_td).strip()  # "A005930"
   except NoSuchElementException:
       stock_code = ""
   
   # 현재가 추출
   try:
       price_td = stock_row.find_element(By.CSS_SELECTOR, "td[id$='_close']")
       price_text = _smart_text(price_td).strip()  # "217,000"
   except NoSuchElementException:
       price_text = ""
   ```

   `_init_csv()` 헤더 변경:
   ```python
   # 기존: ["rank", "user_nick", "stock_name", "weight", "scraped_at"]
   # 변경: ["rank", "user_nick", "stock_code", "stock_name", "tf_price", "weight", "scraped_at"]
   ```

   `_save_portfolio()` 업데이트: 새 컬럼 포함

   **하위 호환성**: 기존 CSV 파일은 `analyzer.py`에서 계속 읽을 수 있도록, `stock_code`/`tf_price` 컬럼이 없는 경우 graceful fallback

   새 함수 `run_scraper_top_n(n: int)` 추가:
   - 상위 N명만 스크래핑 (차익거래용 경량 버전)
   - 종목코드 + 현재가 포함

---

### Phase 3: 가격 비교기

**목적**: 타임폴리오 가격 vs KIS 실시간 가격 비교, 차익 기회 식별

**파일 변경**:

1. **`timefolio/comparator.py`** (새 파일)

   ```python
   @dataclass(frozen=True)
   class ArbitrageOpportunity:
       stock_code: str          # "005930"
       stock_name: str          # "삼성전자"
       tf_price: int            # 타임폴리오 현재가
       kis_price: int           # KIS 실시간 가격
       diff: int                # kis_price - tf_price
       diff_pct: float          # (kis - tf) / tf * 100
       suggested_weight: float  # 추천 비중%
   
   class PriceComparator:
       def __init__(self, kis_api: KISApi):
           self.kis = kis_api
       
       def compare(self, stocks: list[dict]) -> list[ArbitrageOpportunity]:
           """
           stocks: [{"code": "A005930", "name": "삼성전자", "tf_price": "217,000", "weight": "34.0"}, ...]
           
           1. A 접두사 제거 → KIS 코드
           2. KIS get_price()로 실시간 가격 조회 (0.05초 간격)
           3. 차익 계산: diff_pct = (kis - tf) / tf * 100
           4. diff_pct > MIN_ARB_PCT인 종목만 필터
           5. diff_pct 내림차순 정렬
           """
   
       def _parse_tf_price(self, price_str: str) -> int:
           """'217,000' → 217000"""
           return int(price_str.replace(",", ""))
       
       def _strip_code(self, code: str) -> str:
           """'A005930' → '005930'"""
           return code.lstrip("A")
   ```

---

### Phase 4: 주문 자동화

**목적**: 차익 기회 발견 시 타임폴리오에서 자동 매수 주문

**파일 변경**:

1. **`timefolio/order_bot.py`** (새 파일)

   ```python
   class TimefolioOrderBot:
       def __init__(self, driver, wait: WebDriverWait):
           self.driver = driver
           self.wait = wait
       
       def navigate_to_order_tab(self):
           """주문 탭(Tab[0])으로 이동."""
           # ul#tabmenu li[1] 클릭 (XPath 1-indexed)
           # 이미 주문 탭이면 스킵
       
       def open_new_order_form(self):
           """'+ 신규 주문' 버튼 클릭."""
           # button with text '신규 주문' 클릭
           # div[role='dialog'] 출현 대기
       
       def select_stock(self, stock_name: str) -> bool:
           """종목 선택 자동완성.
           
           1. input[placeholder='종목 선택'] 찾기
           2. stock_name 입력 (예: "삼성전자")
           3. 드롭다운 출현 대기 (최대 3초)
           4. 정확히 일치하는 항목 클릭
           5. 선택 확인: "종목 미선택" 텍스트가 사라졌는지 확인
           반환: 성공 여부
           """
       
       def set_buy(self):
           """매수 모드 설정."""
           # input[id='매수도_true'] 클릭
       
       def set_weight(self, weight_pct: float):
           """주문 비중 설정."""
           # 매수도 라디오 다음의 input[type='number'] 찾기
           # clear() + send_keys(str(weight_pct))
       
       def set_price_type(self, prc_type: str = "Opp"):
           """가격 유형 설정. 기본: 상대호가"""
           # input[id='prcTy_{prc_type}'] 클릭
       
       def submit_order(self, dry_run: bool = True) -> bool:
           """주문 제출.
           
           dry_run=True: 스크린샷만 저장하고 제출 안 함
           dry_run=False: '주문 제출' 버튼 클릭
           """
           # 제출 직전 스크린샷 저장 (감사 추적)
           # dry_run이면 여기서 멈춤
           # //button[contains(text(), '주문 제출')] 클릭
       
       def close_form(self):
           """주문 폼 닫기."""
           # //button[contains(text(), '닫기')] 클릭 또는 ESC
       
       def place_order(self, stock_name: str, weight: float, dry_run: bool = True) -> bool:
           """전체 주문 플로우 (원자적 실행).
           
           1. open_new_order_form()
           2. select_stock(stock_name) → 실패 시 close_form() + return False
           3. set_buy()
           4. set_weight(min(weight, MAX_SINGLE_WEIGHT))
           5. set_price_type("Opp")  # 상대호가 기본
           6. submit_order(dry_run)
           7. close_form()
           8. order_log에 기록
           """
   ```

**안전 장치**:
- `ARB_DRY_RUN=true` 기본값: 제출 버튼 클릭 안 함
- `MAX_SINGLE_WEIGHT=15.0`: 단일 종목 최대 비중 캡
- 제출 직전 스크린샷: `database/order_screenshots/` 저장
- 주문 로그: `database/order_log.csv` (시각, 종목, 비중, 차익%, 성공여부)
- 종목명 검증: 드롭다운 선택 후 표시 텍스트와 의도 종목 일치 확인
- 장 시간 확인: 09:00~15:20 외에는 주문 불가

---

### Phase 5: 통합 오케스트레이터

**목적**: 전체 파이프라인을 하나로 연결

**파일 변경**:

1. **`timefolio/arbitrage.py`** (새 파일)

   ```python
   def run_arbitrage(dry_run: bool | None = None) -> None:
       """차익거래 봇 1회 실행.
       
       실행 흐름:
       1. Chrome 드라이버 초기화 (화면 표시)
       2. 타임폴리오 로그인 (기존 scraper 패턴)
       3. 대회 탭 → 상위 ARB_TOP_N명 포트폴리오 스크래핑
          - 종목코드, 종목명, 현재가, 비중 추출
          - 중복 종목 제거 (여러 유저가 같은 종목 보유 시)
       4. KIS API 초기화 + OAuth 토큰
       5. 각 종목 KIS 실시간 가격 조회
          - time.sleep(0.05) 간격 (20 req/sec)
       6. 가격 비교 + 차익 기회 필터링
          - diff_pct > MIN_ARB_PCT
          - diff_pct 내림차순 정렬
       7. 주문 탭 이동
       8. 각 기회에 대해:
          a. place_order(stock_name, weight, dry_run)
          b. 결과 로깅
       9. 텔레그램 요약 전송
       10. 드라이버 종료
       """
   ```

2. **`run.py`** (수정 - 커맨드 추가)
   ```python
   # 추가할 커맨드:
   "arb": cmd_arb        # 차익거래 봇 1회 실행
   "arb-dry": cmd_arb_dry  # DRY_RUN 강제 (안전 테스트)
   "probe": cmd_probe    # DOM 프로브만 실행
   ```

3. **`scheduler.py`** (수정 - 선택적)
   - 차익거래 봇 스케줄 추가 가능 (09:00~15:00, 5분 간격 등)
   - 기존 스크래핑 스케줄과 분리

---

## 5. 파일 변경 요약

| 파일 | 작업 | 설명 |
|------|------|------|
| `timefolio/kis_api.py` | **새 파일** | KIS API 래퍼 (get_price만) |
| `timefolio/comparator.py` | **새 파일** | 가격 비교 + 차익 식별 |
| `timefolio/order_bot.py` | **새 파일** | Selenium 주문 자동화 |
| `timefolio/arbitrage.py` | **새 파일** | 통합 오케스트레이터 |
| `timefolio/config.py` | **수정** | KIS/차익거래 설정 추가 |
| `timefolio/scraper.py` | **수정** | 종목코드+현재가 추출 추가 |
| `run.py` | **수정** | arb 커맨드 추가 |
| `.env` | **수정** | KIS 인증정보 추가 |
| `requirements.txt` | **수정** | requests 추가 |

---

## 6. 구현 순서 + 의존성

```
Phase 1 (KIS API + 설정)     독립, 먼저 완료
    ↓
Phase 2 (스크래퍼 확장)       Phase 1 필요 (config 변경)
    ↓
Phase 3 (가격 비교기)         Phase 1 + 2 필요
    ↓
Phase 4 (주문 봇)             독립 (셀렉터 확인 완료)
    ↓
Phase 5 (통합)                전체 필요
```

**예상 작업량**: Phase 1~5 순차 구현, 각 Phase 완료 시 단위 테스트

---

## 7. 리스크 및 대응

| 리스크 | 확률 | 대응 |
|--------|------|------|
| 종목 자동완성 드롭다운 셀렉터 변경 | 낮음 | XPath fallback + 텍스트 매칭 |
| 가격 차이가 시간 지연일 뿐 실질 차익 아님 | 중간 | MIN_ARB_PCT 임계값으로 필터 |
| 주문 제출 후 체결 실패 | 중간 | 미접수/에러 주문 테이블 확인 로직 |
| KIS API 토큰 만료/속도 제한 | 낮음 | 자동 갱신 구현됨 + sleep(0.05) |
| React SPA 리렌더링으로 StaleElement | 중간 | 재시도 로직 (기존 scraper 패턴) |
| 타임폴리오 UI 업데이트 | 낮음 | probe.py로 재검증 가능 |

---

## 8. 검증 방법

1. **Phase 1**: KIS API `get_price("005930")` 호출 → 삼성전자 가격 반환 확인
2. **Phase 2**: `run.py scrape` 실행 → CSV에 stock_code, tf_price 컬럼 포함 확인
3. **Phase 3**: 비교기 실행 → 타임폴리오 vs KIS 가격 비교표 출력, diff_pct 계산 확인
4. **Phase 4**: `ARB_DRY_RUN=true`로 주문 폼까지만 진행 → 스크린샷 확인
5. **Phase 5**: `python run.py arb` 전체 파이프라인 → DRY_RUN 모드로 end-to-end 확인

---

## 9. 향후 확장 (현재 스코프 외)

- 장중 5분 간격 자동 스케줄링
- 보유 포지션 관리 (매도 자동화)
- 차익 히스토리 분석 + 백테스트
- 텔레그램 실시간 알림 (차익 발견 즉시)
