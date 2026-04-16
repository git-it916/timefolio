"""
중앙 설정 모듈.
- .env에서 인증정보 로드
- 경로, 스크래핑, 전략 파라미터 정의
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트 기준으로 .env 로드 (패키지 안에서 호출되어도 정상 동작)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ── 인증 ──────────────────────────────────────────────
LOGIN_URL: str = os.getenv("TIMEFOLIO_URL", "https://hankyung.timefolio.net/")
USER_ID: str = os.getenv("TIMEFOLIO_ID", "")
USER_PW: str = os.getenv("TIMEFOLIO_PW", "")

# ── 경로 (프로젝트 루트 기준 상대경로) ────────────────
DB_DIR: str = str(_PROJECT_ROOT / "database")
REPORT_DIR: str = str(_PROJECT_ROOT / "reports")
PORTFOLIO_PREFIX: str = "portfolio"

# ── 스크래핑 ──────────────────────────────────────────
RANKS_TO_SCRAPE: int = 50
WAIT_TIMEOUT: int = 30        # Selenium WebDriverWait 타임아웃(초)
PAGE_LOAD_WAIT: float = 3.0   # 페이지 전환 후 대기(초)
MODAL_CLOSE_WAIT: float = 1.0 # 모달 닫기 후 대기(초)
HEADLESS: bool = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")

# ── 텔레그램 ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ── 스케줄러 ─────────────────────────────────────────
SCHEDULE_START_HOUR: int = int(os.getenv("SCHEDULE_START_HOUR", "8"))
SCHEDULE_END_HOUR: int = int(os.getenv("SCHEDULE_END_HOUR", "18"))
SCHEDULE_INTERVAL_MIN: int = int(os.getenv("SCHEDULE_INTERVAL_MIN", "30"))

# ── KIS API (한국투자증권) ────────────────────────────
KIS_APP_KEY: str = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET: str = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT: str = os.getenv("KIS_ACCOUNT", "")
KIS_IS_PAPER: bool = os.getenv("KIS_IS_PAPER", "true").lower() in ("true", "1", "yes")

# ── 차익거래 봇 ──────────────────────────────────────
MIN_ARB_PCT: float = float(os.getenv("MIN_ARB_PCT", "0.5"))
MAX_SINGLE_WEIGHT: float = float(os.getenv("MAX_SINGLE_WEIGHT", "15.0"))
ARB_TOP_N: int = int(os.getenv("ARB_TOP_N", "5"))
ARB_DRY_RUN: bool = os.getenv("ARB_DRY_RUN", "true").lower() in ("true", "1", "yes")
ORDER_SCREENSHOT_DIR: str = str(_PROJECT_ROOT / "database" / "order_screenshots")
ORDER_LOG_PATH: str = str(_PROJECT_ROOT / "database" / "order_log.csv")

# ── 전략 파라미터 ─────────────────────────────────────
TOP_TIER: int = 10             # 상위 10명 = "엘리트" 그룹
MID_TIER: int = 20             # 상위 20명 = "상위권" 그룹

# 시그널 점수 임계값 (100점 만점)
STRONG_BUY_THRESHOLD: float = 55.0
BUY_THRESHOLD: float = 35.0
HOLD_THRESHOLD: float = 20.0

# 점수 가중치 (합계 = 100)
W_TOP_TIER: float = 30.0      # 엘리트 보유 비중
W_MID_TIER: float = 20.0      # 상위권 보유 비중
W_BROAD: float = 20.0         # 전체 컨센서스
W_MOMENTUM_MAG: float = 20.0  # 신규 매수자 수
W_MOMENTUM_DIR: float = 10.0  # 모멘텀 방향성
