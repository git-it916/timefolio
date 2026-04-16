"""
타임폴리오 실시간 차익거래 루프 봇.

원리:
  타임폴리오(TF) 가격은 실제 시장(KIS) 대비 9~19초 지연된다.
  KIS에서 가격이 올랐지만 TF가 아직 반영 안 했을 때 TF에서 매수하면,
  TF가 가격을 따라잡는 순간 수익이 확정된다.
  검증 결과 이 전략의 손실 건수는 0건이다.

동작:
  1. 상위 유저 포트폴리오에서 모니터링 종목 추출 (1회)
  2. 1초 간격으로 TF/KIS 가격 동시 조회 (병렬)
  3. spread_bps > 진입 임계값이면 즉시 매수 주문
  4. 이미 보유 중인 종목은 스킵
  5. 장 종료까지 반복
"""

from __future__ import annotations

import csv
import logging
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from timefolio.api_client import TimefolioApiClient
from timefolio.config import (
    ARB_DRY_RUN,
    ARB_TOP_N,
    DB_DIR,
    KIS_APP_KEY,
    KIS_APP_SECRET,
    KIS_ACCOUNT,
    MAX_SINGLE_WEIGHT,
    MIN_ARB_PCT,
    USER_ID,
    USER_PW,
)
from timefolio.kis_api import KISApi, KISAuth

log = logging.getLogger(__name__)

# ── 설정 ──────────────────────────────────────────────
ENTRY_BPS = float(os.getenv("ENTRY_BPS", "10"))       # 진입 임계값 (bp)
ORDER_WEIGHT = float(os.getenv("ORDER_WEIGHT", "1.0")) # 주문당 비중%
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "10"))   # 최대 동시 포지션
SCAN_INTERVAL = float(os.getenv("SCAN_INTERVAL", "3.0"))  # 스캔 간격(초)
MAX_TOTAL_WEIGHT = float(os.getenv("MAX_TOTAL_WEIGHT", "50.0"))  # 최대 총 비중%
MIN_HOLD_SEC = float(os.getenv("MIN_HOLD_SEC", "30"))  # 매수 후 최소 보유 시간(초)

# 하드코딩 종목: "코드:이름,코드:이름,..."
_ARB_STOCKS_RAW = os.getenv("ARB_STOCKS", "")


def _parse_arb_stocks() -> list[tuple[str, str]]:
    """ARB_STOCKS 환경변수 파싱. [(code, name), ...]"""
    if not _ARB_STOCKS_RAW:
        return []
    result = []
    for pair in _ARB_STOCKS_RAW.split(","):
        pair = pair.strip()
        if ":" in pair:
            code, name = pair.split(":", 1)
            result.append((code.strip(), name.strip()))
    return result


@dataclass
class Position:
    """보유 포지션."""
    code: str
    name: str
    entry_tf: int
    entry_kis: int
    entry_bps: float
    entry_time: str
    entry_perf: float = 0.0  # time.perf_counter() at entry
    weight: float


@dataclass
class BotState:
    """봇 상태."""
    positions: dict[str, Position] = field(default_factory=dict)
    total_weight: float = 0.0
    scan_count: int = 0
    order_count: int = 0
    total_pnl_bps: float = 0.0
    start_time: float = 0.0
    running: bool = True
    log_path: str = ""


def _market_open() -> bool:
    now = datetime.now()
    return now.replace(hour=9, minute=0) <= now <= now.replace(hour=15, minute=20)


def _build_monitor_list(
    tf_client: TimefolioApiClient, top_n: int,
) -> list[tuple[str, str, int]]:
    """모니터링 종목 + TF가격 소스(pfId) 매핑.

    ARB_STOCKS가 설정되어 있으면 하드코딩 종목 사용 (API 호출 최소화).
    없으면 기존처럼 상위 N명에서 동적 추출.

    Returns:
        [(kis_code, name, pf_id), ...]
    """
    hardcoded = _parse_arb_stocks()
    rankings = tf_client.get_rankings()

    if hardcoded:
        # 하드코딩 종목의 pfId만 찾기 (최소 API 호출)
        target_codes = {code for code, _ in hardcoded}
        code_to_pfid: dict[str, int] = {}

        for entry in rankings[:30]:
            if len(code_to_pfid) >= len(target_codes):
                break
            pf_id = entry["Id"]
            positions = tf_client.get_portfolio(pf_id)
            for pos in positions:
                stripped = pos.prod_id.lstrip("A")
                if stripped in target_codes and stripped not in code_to_pfid:
                    code_to_pfid[stripped] = pf_id
            time.sleep(0.2)

        result = []
        for code, name in hardcoded:
            pf_id = code_to_pfid.get(code, 0)
            if pf_id:
                result.append((code, name, pf_id))
                log.info("  %s %s → pfId=%d", code, name, pf_id)
            else:
                log.warning("  %s %s → 보유 포트폴리오 못 찾음 (제외)", code, name)

        log.info("하드코딩 종목: %d/%d개 매핑 완료", len(result), len(hardcoded))
        return result

    # fallback: 동적 추출
    code_info: dict[str, tuple[str, int]] = {}
    for entry in rankings[:top_n]:
        pf_id = entry["Id"]
        positions = tf_client.get_portfolio(pf_id)
        for pos in positions:
            stripped = pos.prod_id.lstrip("A")
            if stripped and stripped not in code_info:
                code_info[stripped] = (pos.prod_nm, pf_id)
        time.sleep(0.2)

    result = [(code, name, pf_id) for code, (name, pf_id) in code_info.items()]
    log.info("동적 추출 종목: %d개 (상위 %d명)", len(result), top_n)
    return result


def _fetch_tf_prices(
    tf_client: TimefolioApiClient,
    pf_ids: set[int],
    code_to_pfid: dict[str, int],
) -> dict[str, int]:
    """TF 가격 일괄 조회 (순차, 서버 부하 방지)."""
    prices: dict[str, int] = {}
    for pf_id in pf_ids:
        try:
            positions = tf_client.get_portfolio(pf_id)
            for pos in positions:
                prices[pos.prod_id.lstrip("A")] = pos.close
        except Exception:
            pass
        time.sleep(0.1)
    return prices


def _fetch_kis_prices(
    kis: KISApi, codes: list[str],
) -> dict[str, int]:
    """KIS 가격 일괄 조회 (병렬)."""
    result: dict[str, int] = {}

    def fetch_one(code: str) -> tuple[str, int]:
        try:
            data = kis.get_price(code)
            return code, data.get("price", 0)
        except Exception:
            return code, 0

    with ThreadPoolExecutor(max_workers=min(10, len(codes))) as ex:
        futures = {ex.submit(fetch_one, c): c for c in codes}
        for f in as_completed(futures):
            code, price = f.result()
            result[code] = price
    return result


def _log_trade(state: BotState, action: str, code: str, name: str,
               tf: int, kis: int, bps: float, weight: float) -> None:
    """거래 로그 기록."""
    is_new = not os.path.exists(state.log_path)
    with open(state.log_path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["time", "action", "code", "name", "tf_price",
                        "kis_price", "spread_bps", "weight", "scan", "total_orders"])
        w.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            action, code, name, tf, kis, round(bps, 1),
            weight, state.scan_count, state.order_count,
        ])


def run_arb_loop(dry_run: bool | None = None) -> None:
    """차익거래 루프 실행."""
    effective_dry = dry_run if dry_run is not None else ARB_DRY_RUN
    mode = "DRY_RUN" if effective_dry else "LIVE"

    if not KIS_APP_KEY or not USER_ID:
        log.error("인증 정보 없음. .env 확인.")
        return

    state = BotState(
        start_time=time.perf_counter(),
        log_path=os.path.join(DB_DIR, f"arb_trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"),
    )
    os.makedirs(DB_DIR, exist_ok=True)

    # Ctrl+C 핸들러
    def _shutdown(sig, frame):
        state.running = False
        print("\n  [Ctrl+C] 종료 중...")
    signal.signal(signal.SIGINT, _shutdown)

    print(f"\n{'=' * 65}")
    print(f"  ARBITRAGE LOOP BOT [{mode}]")
    print(f"  진입: {ENTRY_BPS}bp | 비중: {ORDER_WEIGHT}% | 최대포지션: {MAX_POSITIONS}")
    print(f"  스캔간격: {SCAN_INTERVAL}s | 최대총비중: {MAX_TOTAL_WEIGHT}%")
    print(f"  Ctrl+C로 종료")
    print(f"{'=' * 65}\n")

    # 1. 초기화
    tf = TimefolioApiClient(USER_ID, USER_PW)
    tf.login()

    kis = KISApi(KISAuth(
        app_key=KIS_APP_KEY, app_secret=KIS_APP_SECRET,
        account_number=KIS_ACCOUNT, is_paper=False,
    ))
    # 토큰은 첫 get_price 호출 시 자동 발급됨

    # 2. 모니터링 종목 추출
    monitor_list = _build_monitor_list(tf, ARB_TOP_N)
    codes = [code for code, _, _ in monitor_list]
    code_to_name = {code: name for code, name, _ in monitor_list}
    code_to_pfid = {code: pf_id for code, _, pf_id in monitor_list}
    pf_ids = set(code_to_pfid.values())

    print(f"  {len(codes)}종목 모니터링 시작\n")

    # 3. 루프
    while state.running:
        tick_start = time.perf_counter()
        state.scan_count += 1

        if not _market_open() and not effective_dry:
            if state.scan_count == 1:
                print("  장외시간 - DRY_RUN 모드로 전환")
            effective_dry = True

        # TF + KIS 가격 동시 조회
        try:
            tf_prices = _fetch_tf_prices(tf, pf_ids, code_to_pfid)
            kis_prices = _fetch_kis_prices(kis, codes)
        except Exception as e:
            log.warning("가격 조회 실패: %s", e)
            time.sleep(SCAN_INTERVAL)
            continue

        now_str = datetime.now().strftime("%H:%M:%S")
        opportunities: list[tuple[str, str, int, int, float]] = []

        for code in codes:
            tf_p = tf_prices.get(code, 0)
            kis_p = kis_prices.get(code, 0)
            if tf_p <= 0 or kis_p <= 0:
                continue

            bps = (kis_p - tf_p) / tf_p * 10000
            name = code_to_name.get(code, code)

            if bps >= ENTRY_BPS and code not in state.positions:
                opportunities.append((code, name, tf_p, kis_p, bps))

        # 기회 출력 + 주문
        if opportunities:
            opportunities.sort(key=lambda x: -x[4])  # bps 내림차순

            for code, name, tf_p, kis_p, bps in opportunities:
                if len(state.positions) >= MAX_POSITIONS:
                    break
                if state.total_weight >= MAX_TOTAL_WEIGHT:
                    break

                weight = ORDER_WEIGHT

                # 매수 주문 (지정가 = TF 현재가, 슬리피지 0)
                order_ok = False
                if effective_dry:
                    order_ok = True
                else:
                    try:
                        tf.add_order(
                            prod_id=f"A{code}",
                            wei=weight,
                            ls="L", ex="E",
                            limit_prc=tf_p,
                        )
                        order_ok = True
                    except Exception as e:
                        log.error("주문 실패 %s: %s", name, e)

                if order_ok:
                    state.positions[code] = Position(
                        code=code, name=name,
                        entry_tf=tf_p, entry_kis=kis_p,
                        entry_bps=bps,
                        entry_time=now_str,
                        weight=weight,
                        entry_perf=time.perf_counter(),
                    )
                    state.total_weight += weight
                    state.order_count += 1
                    time.sleep(0.3)  # 주문 간 간격 (서버 부하 방지)

                    tag = "DRY" if effective_dry else "BUY"
                    print(
                        f"  [{now_str}] #{state.scan_count:>4d} "
                        f"*** {tag} {name} | TF={tf_p:,} KIS={kis_p:,} "
                        f"+{bps:.0f}bp | {weight}% | "
                        f"포지션={len(state.positions)}/{MAX_POSITIONS}"
                    )
                    _log_trade(state, tag, code, name, tf_p, kis_p, bps, weight)

        # 포지션 수렴 체크 → 즉시 매도 청산
        closed = []
        for code, pos in state.positions.items():
            tf_p = tf_prices.get(code, 0)
            if tf_p <= 0:
                continue
            current_pnl_bps = (tf_p - pos.entry_tf) / pos.entry_tf * 10000
            hold_sec = time.perf_counter() - pos.entry_perf
            if tf_p >= pos.entry_kis and hold_sec >= MIN_HOLD_SEC:
                # 수렴 완료 → 매도 주문 (지정가 = 수렴된 TF가격)
                sell_ok = False
                if effective_dry:
                    sell_ok = True
                else:
                    try:
                        tf.add_order(
                            prod_id=f"A{code}",
                            wei=pos.weight,
                            ls="L", ex="X",
                            limit_prc=tf_p,
                        )
                        sell_ok = True
                    except Exception as e:
                        log.error("매도 실패 %s: %s", pos.name, e)

                if sell_ok:
                    state.total_pnl_bps += current_pnl_bps
                    time.sleep(0.3)  # 매도 간 간격
                    tag = "SELL(DRY)" if effective_dry else "SELL"
                    print(
                        f"  [{now_str}] #{state.scan_count:>4d} "
                        f"  {tag} {pos.name} | "
                        f"매수={pos.entry_tf:,} → 매도={tf_p:,} "
                        f"+{current_pnl_bps:.0f}bp | "
                        f"총PnL={state.total_pnl_bps:+.0f}bp"
                    )
                    _log_trade(state, tag, code, pos.name,
                               tf_p, pos.entry_kis, current_pnl_bps, pos.weight)
                    closed.append(code)

        for code in closed:
            state.total_weight -= state.positions[code].weight
            del state.positions[code]

        # 주기적 상태 출력 (10스캔마다)
        if state.scan_count % 10 == 0 and not opportunities and not closed:
            elapsed = time.perf_counter() - state.start_time
            pos_str = ", ".join(
                f"{p.name}+{p.entry_bps:.0f}bp"
                for p in state.positions.values()
            ) or "없음"
            print(
                f"  [{now_str}] #{state.scan_count:>4d} "
                f"scan {elapsed:.0f}s | "
                f"주문={state.order_count} PnL={state.total_pnl_bps:+.0f}bp | "
                f"포지션: {pos_str}"
            )

        # 간격 맞추기
        elapsed = time.perf_counter() - tick_start
        sleep_time = max(0, SCAN_INTERVAL - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

    # 4. 종료 요약
    total_elapsed = time.perf_counter() - state.start_time
    print(f"\n{'=' * 65}")
    print(f"  SUMMARY")
    print(f"  실행시간: {total_elapsed:.0f}초 | 스캔: {state.scan_count}회")
    print(f"  주문: {state.order_count}건 | 총PnL: {state.total_pnl_bps:+.1f}bp")
    if state.positions:
        print(f"  미청산 포지션: {len(state.positions)}건")
        for p in state.positions.values():
            print(f"    {p.name}: entry_tf={p.entry_tf:,} entry_bps=+{p.entry_bps:.0f}bp")
    print(f"  거래 로그: {state.log_path}")
    print(f"{'=' * 65}")

    # 텔레그램 알림
    try:
        _send_summary(state, mode, total_elapsed)
    except Exception as e:
        log.warning("텔레그램 실패: %s", e)


def _send_summary(state: BotState, mode: str, elapsed: float) -> None:
    from timefolio.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    import asyncio
    import telegram

    text = (
        f"*Arb Loop \\[{mode}\\]*\n"
        f"{elapsed:.0f}s \\| {state.scan_count} scans\n"
        f"Orders: {state.order_count} \\| PnL: {state.total_pnl_bps:+.0f}bp"
    )

    async def _send():
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID, text=text,
            parse_mode=telegram.constants.ParseMode.MARKDOWN_V2,
        )
    asyncio.run(_send())
