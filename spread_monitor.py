"""
타임폴리오 vs KIS 스프레드 실시간 모니터링.

1초 간격으로 120초간 데이터를 수집하여:
1. 스프레드 크기/방향/지속 시간 분석
2. 차익거래 시뮬레이션 (가상 주문 + P&L 계산)
"""

import csv
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

from timefolio.api_client import TimefolioApiClient
from timefolio.config import (
    KIS_APP_KEY,
    KIS_APP_SECRET,
    KIS_ACCOUNT,
    USER_ID,
    USER_PW,
)
from timefolio.kis_api import KISApi, KISAuth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DURATION_SEC = 120
INTERVAL_SEC = 1.0
# 유동성 높고 이전 분석에서 스프레드가 관찰된 종목
TARGET_STOCKS = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("047040", "대우건설"),
    ("095340", "ISC"),
    ("006650", "대한유화"),
]

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "database")
OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"spread_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")


@dataclass
class Tick:
    timestamp: float
    time_str: str
    code: str
    name: str
    tf_price: int
    kis_price: int
    spread: int        # kis - tf
    spread_bps: float  # basis points


@dataclass
class SimTrade:
    entry_tick: int
    exit_tick: int
    code: str
    name: str
    entry_tf_price: int
    entry_kis_price: int
    exit_tf_price: int
    spread_at_entry_bps: float
    pnl_bps: float
    hold_sec: float


def main():
    print("=" * 70)
    print("  SPREAD MONITOR + ARBITRAGE SIMULATION")
    print(f"  {len(TARGET_STOCKS)} stocks | {DURATION_SEC}s | ~{INTERVAL_SEC}s interval")
    print("=" * 70)

    # 1. 로그인
    t0 = time.perf_counter()
    tf = TimefolioApiClient(USER_ID, USER_PW)
    login_data = tf.login()

    kis_auth = KISAuth(
        app_key=KIS_APP_KEY,
        app_secret=KIS_APP_SECRET,
        account_number=KIS_ACCOUNT,
        is_paper=False,
    )
    kis = KISApi(kis_auth)
    # 토큰 미리 확보
    kis._refresh_token()
    print(f"  Init: {time.perf_counter() - t0:.2f}s\n")

    # 2. 타임폴리오에서 모니터링 대상 종목의 pfId 찾기
    rankings = tf.get_rankings()
    target_codes = {code for code, _ in TARGET_STOCKS}

    # 각 종목이 어떤 포트폴리오에 있는지 매핑
    code_to_pfid: dict[str, int] = {}
    for rank_entry in rankings[:20]:  # 상위 20명 탐색
        pf_id = rank_entry["Id"]
        positions = tf.get_portfolio(pf_id)
        for pos in positions:
            stripped = pos.prod_id.lstrip("A")
            if stripped in target_codes and stripped not in code_to_pfid:
                code_to_pfid[stripped] = pf_id
        if len(code_to_pfid) >= len(target_codes):
            break
        time.sleep(0.05)

    found = [(code, name) for code, name in TARGET_STOCKS if code in code_to_pfid]
    print(f"  모니터링 가능 종목: {len(found)}/{len(TARGET_STOCKS)}")
    for code, name in found:
        print(f"    {code} {name} (pfId={code_to_pfid[code]})")

    if not found:
        print("  ERROR: 모니터링할 종목이 없습니다.")
        return

    # 3. 데이터 수집 루프
    print(f"\n  수집 시작 ({DURATION_SEC}초)...\n")
    all_ticks: list[Tick] = []
    csv_rows: list[list] = []
    start_time = time.perf_counter()
    tick_num = 0

    # 헤더 출력
    header = f"{'tick':>4s} {'time':>12s}"
    for code, name in found:
        header += f" | {name:>8s}(TF) {'KIS':>8s} {'sprd':>5s}"
    print(header)
    print("-" * len(header))

    while time.perf_counter() - start_time < DURATION_SEC:
        tick_start = time.perf_counter()
        tick_num += 1
        now_str = datetime.now().strftime("%H:%M:%S.%f")[:12]

        # TF 가격: 각 종목이 속한 포트폴리오에서 조회 (병렬)
        tf_prices: dict[str, int] = {}
        pf_ids_needed = set(code_to_pfid.values())

        def fetch_tf(pf_id):
            positions = tf.get_portfolio(pf_id)
            return {pos.prod_id.lstrip("A"): pos.close for pos in positions}

        with ThreadPoolExecutor(max_workers=5) as executor:
            tf_futures = {executor.submit(fetch_tf, pid): pid for pid in pf_ids_needed}
            for f in as_completed(tf_futures):
                try:
                    result = f.result()
                    tf_prices.update(result)
                except Exception:
                    pass

        # KIS 가격 (병렬)
        codes = [code for code, _ in found]

        def fetch_kis(code):
            try:
                return code, kis.get_price(code)
            except Exception:
                return code, {"price": 0}

        kis_prices: dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            kis_futures = {executor.submit(fetch_kis, c): c for c in codes}
            for f in as_completed(kis_futures):
                code, data = f.result()
                kis_prices[code] = data.get("price", 0)

        # Tick 기록
        line = f"{tick_num:>4d} {now_str:>12s}"
        for code, name in found:
            tf_p = tf_prices.get(code, 0)
            kis_p = kis_prices.get(code, 0)
            spread = kis_p - tf_p
            spread_bps = (spread / tf_p * 10000) if tf_p > 0 else 0

            tick = Tick(
                timestamp=time.perf_counter() - start_time,
                time_str=now_str,
                code=code, name=name,
                tf_price=tf_p, kis_price=kis_p,
                spread=spread, spread_bps=round(spread_bps, 1),
            )
            all_ticks.append(tick)
            csv_rows.append([
                tick_num, now_str, code, name,
                tf_p, kis_p, spread, round(spread_bps, 1),
            ])

            # 색상 없이 간결하게
            sign = "+" if spread_bps > 0 else ""
            line += f" | {tf_p:>8,d} {kis_p:>8,d} {sign}{spread_bps:>4.0f}bp"

        print(line)

        # 1초 간격 맞추기
        elapsed = time.perf_counter() - tick_start
        sleep_time = max(0, INTERVAL_SEC - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

    # 4. CSV 저장
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["tick", "time", "code", "name", "tf_price", "kis_price", "spread", "spread_bps"])
        w.writerows(csv_rows)
    print(f"\n  데이터 저장: {OUTPUT_CSV}")

    # 5. 분석
    print(f"\n{'=' * 70}")
    print("  SPREAD ANALYSIS")
    print(f"{'=' * 70}")

    for code, name in found:
        ticks = [t for t in all_ticks if t.code == code]
        if not ticks:
            continue

        spreads = [t.spread_bps for t in ticks]
        pos_spreads = [s for s in spreads if s > 0]    # TF < KIS (매수 기회)
        neg_spreads = [s for s in spreads if s < 0]    # TF > KIS
        zero_spreads = [s for s in spreads if s == 0]

        avg = sum(spreads) / len(spreads)
        max_s = max(spreads)
        min_s = min(spreads)

        print(f"\n  {name} ({code}):")
        print(f"    틱 수: {len(ticks)}")
        print(f"    평균 스프레드: {avg:+.1f}bp")
        print(f"    최대: {max_s:+.1f}bp | 최소: {min_s:+.1f}bp")
        print(f"    양(TF<KIS): {len(pos_spreads)}틱 | 음(TF>KIS): {len(neg_spreads)}틱 | 0: {len(zero_spreads)}틱")

        # 연속 양의 스프레드 구간 분석
        runs = []
        current_run = 0
        for s in spreads:
            if s > 0:
                current_run += 1
            else:
                if current_run > 0:
                    runs.append(current_run)
                current_run = 0
        if current_run > 0:
            runs.append(current_run)

        if runs:
            print(f"    양의 스프레드 연속 구간: {len(runs)}회, 평균={sum(runs)/len(runs):.1f}틱, 최대={max(runs)}틱")

    # 6. 차익거래 시뮬레이션
    print(f"\n{'=' * 70}")
    print("  ARBITRAGE SIMULATION")
    print(f"{'=' * 70}")

    ENTRY_THRESHOLD_BPS = 5    # 5bp 이상이면 진입
    EXIT_THRESHOLD_BPS = 0     # 0bp 이하면 청산
    TRADE_WEIGHT_PCT = 1.0     # 1% 비중
    INITIAL_NAV = 10_000_000   # 1000만원 (시뮬레이션용)

    sim_trades: list[SimTrade] = []

    for code, name in found:
        ticks = [t for t in all_ticks if t.code == code]
        in_position = False
        entry_tick_idx = 0
        entry_tf = 0
        entry_kis = 0
        entry_bps = 0

        for i, tick in enumerate(ticks):
            if not in_position and tick.spread_bps >= ENTRY_THRESHOLD_BPS:
                # 진입
                in_position = True
                entry_tick_idx = i
                entry_tf = tick.tf_price
                entry_kis = tick.kis_price
                entry_bps = tick.spread_bps

            elif in_position and (tick.spread_bps <= EXIT_THRESHOLD_BPS or i == len(ticks) - 1):
                # 청산
                hold_time = tick.timestamp - ticks[entry_tick_idx].timestamp
                # PnL: TF에서 entry_tf에 사서, 현재 tf_price에 팔았다고 가정
                pnl_bps = (tick.tf_price - entry_tf) / entry_tf * 10000

                sim_trades.append(SimTrade(
                    entry_tick=entry_tick_idx,
                    exit_tick=i,
                    code=code, name=name,
                    entry_tf_price=entry_tf,
                    entry_kis_price=entry_kis,
                    exit_tf_price=tick.tf_price,
                    spread_at_entry_bps=entry_bps,
                    pnl_bps=round(pnl_bps, 1),
                    hold_sec=round(hold_time, 1),
                ))
                in_position = False

    if sim_trades:
        print(f"\n  총 거래: {len(sim_trades)}건")
        print(f"  {'종목':>8s} {'진입틱':>5s} {'청산틱':>5s} {'보유(초)':>7s} {'진입스프레드':>10s} {'PnL':>7s}")
        print("  " + "-" * 55)

        total_pnl_bps = 0
        for t in sim_trades:
            print(
                f"  {t.name:>8s} {t.entry_tick:>5d} {t.exit_tick:>5d}"
                f" {t.hold_sec:>7.1f}s {t.spread_at_entry_bps:>+9.1f}bp {t.pnl_bps:>+6.1f}bp"
            )
            total_pnl_bps += t.pnl_bps

        total_pnl_krw = INITIAL_NAV * total_pnl_bps / 10000
        print(f"\n  총 PnL: {total_pnl_bps:+.1f}bp ({total_pnl_krw:+,.0f}원 / {INITIAL_NAV:,d}원 기준)")
        wins = sum(1 for t in sim_trades if t.pnl_bps > 0)
        print(f"  승률: {wins}/{len(sim_trades)} ({wins/len(sim_trades)*100:.0f}%)")
    else:
        print(f"\n  {ENTRY_THRESHOLD_BPS}bp 이상 스프레드 미발생 — 거래 없음")
        print("  (임계값을 낮추거나 장 시작 직후에 다시 실행해보세요)")

    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    main()
