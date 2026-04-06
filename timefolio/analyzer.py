"""
Timefolio 따라잡기 전략 분석기.

두 시점의 포트폴리오 스냅샷을 비교하여 종목별로:
1. 컨센서스 점수  — 상위 유저 중 몇 명이 보유하는가
2. 순위 가중 점수 — 보유자의 순위가 높을수록 가중
3. 모멘텀 시그널  — 신규 매수 vs 이탈 흐름
4. 종합 스코어 & 매매 시그널 (STRONG_BUY / BUY / HOLD / CAUTION / NEUTRAL)
"""

import glob
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from timefolio.config import (
    BUY_THRESHOLD,
    DB_DIR,
    HOLD_THRESHOLD,
    MID_TIER,
    RANKS_TO_SCRAPE,
    REPORT_DIR,
    STRONG_BUY_THRESHOLD,
    TOP_TIER,
    W_BROAD,
    W_MID_TIER,
    W_MOMENTUM_DIR,
    W_MOMENTUM_MAG,
    W_TOP_TIER,
)

log = logging.getLogger(__name__)

_FILENAME_RE = re.compile(r"portfolio_(\d{8})_(\d+)\.csv$", re.IGNORECASE)
_KEY_RE = re.compile(r"^\d{8}_\d+$")


# ═══════════════════════════════════════════════════════
#  데이터 모델
# ═══════════════════════════════════════════════════════

@dataclass(frozen=True)
class StockSignal:
    """개별 종목 분석 결과."""
    stock_name: str
    signal: str
    score: float
    n_holders: int
    top_tier_holders: int
    mid_tier_holders: int
    n_new_buyers: int
    n_droppers: int
    momentum: int
    holder_ranks: tuple[int, ...]
    new_buyer_ranks: tuple[int, ...]
    dropper_ranks: tuple[int, ...]


# ═══════════════════════════════════════════════════════
#  파일 I/O
# ═══════════════════════════════════════════════════════

def _parse_filename(path: str) -> tuple[str, int] | None:
    m = _FILENAME_RE.search(os.path.basename(path))
    if not m:
        return None
    return m.group(1), int(m.group(2))


def _read_snapshot(path: str) -> pd.DataFrame:
    df = pd.read_csv(
        path,
        dtype={"rank": "Int64", "user_nick": str, "stock_name": str},
        encoding="utf-8-sig",
    )
    for col in ("user_nick", "stock_name"):
        df[col] = df[col].fillna("").astype(str).str.strip()
    df = df[(df["user_nick"] != "") & (df["stock_name"] != "")]
    return df.drop_duplicates(subset=["user_nick", "stock_name"])


def list_snapshots() -> list[tuple[str, int, str]]:
    """사용 가능한 스냅샷 목록: [(date, seq, path), ...]  시간순 정렬."""
    result = []
    for f in glob.glob(os.path.join(DB_DIR, "portfolio_*.csv")):
        info = _parse_filename(f)
        if info:
            result.append((info[0], info[1], f))
    result.sort(key=lambda x: (x[0], x[1]))
    return result


def pick_snapshots(
    curr_key: str | None = None, prev_key: str | None = None
) -> tuple[str, str]:
    """비교할 두 스냅샷 경로를 반환 (curr, prev)."""
    if curr_key and prev_key:
        for k in (curr_key, prev_key):
            if not _KEY_RE.match(k):
                raise ValueError(f"키 형식 오류 (예: 20251029_2): {k}")
        curr_path = os.path.join(DB_DIR, f"portfolio_{curr_key}.csv")
        prev_path = os.path.join(DB_DIR, f"portfolio_{prev_key}.csv")
        for p in (curr_path, prev_path):
            if not os.path.exists(p):
                raise FileNotFoundError(f"파일 없음: {p}")
        return curr_path, prev_path

    snapshots = list_snapshots()
    if len(snapshots) < 2:
        raise RuntimeError(
            f"스냅샷이 2개 이상 필요합니다 (현재 {len(snapshots)}개). "
            "스크래핑을 두 번 이상 실행하세요."
        )
    return snapshots[-1][2], snapshots[-2][2]


# ═══════════════════════════════════════════════════════
#  내부 매핑 빌더
# ═══════════════════════════════════════════════════════

def _stock_to_holders(df: pd.DataFrame) -> dict[str, list[tuple[int, str]]]:
    result: dict[str, list[tuple[int, str]]] = {}
    for _, row in df.iterrows():
        rank = int(row["rank"]) if pd.notna(row["rank"]) else 999
        result.setdefault(row["stock_name"], []).append((rank, row["user_nick"]))
    return result


def _user_to_stocks(df: pd.DataFrame) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for _, row in df.iterrows():
        result.setdefault(row["user_nick"], set()).add(row["stock_name"])
    return result


def _stock_to_users(user_map: dict[str, set[str]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for user, stocks in user_map.items():
        for s in stocks:
            result.setdefault(s, set()).add(user)
    return result


# ═══════════════════════════════════════════════════════
#  점수 & 시그널 계산
# ═══════════════════════════════════════════════════════

def _compute_score(
    n_holders: int, top_tier: int, mid_tier: int,
    n_new: int, momentum: int,
) -> float:
    top_score = W_TOP_TIER * min(top_tier / TOP_TIER, 1.0)
    mid_score = W_MID_TIER * min(mid_tier / MID_TIER, 1.0)
    broad_score = W_BROAD * min(n_holders / RANKS_TO_SCRAPE, 1.0)
    mag_score = W_MOMENTUM_MAG * min(n_new / 5, 1.0)

    if momentum > 0:
        dir_score = W_MOMENTUM_DIR * min(momentum / 3, 1.0)
    elif momentum == 0:
        dir_score = W_MOMENTUM_DIR * 0.5
    else:
        dir_score = max(0.0, W_MOMENTUM_DIR * (0.5 + momentum / 6))

    return round(top_score + mid_score + broad_score + mag_score + dir_score, 1)


def _classify(score: float, momentum: int) -> str:
    if score >= STRONG_BUY_THRESHOLD and momentum > 0:
        return "STRONG_BUY"
    if score >= BUY_THRESHOLD and momentum >= 0:
        return "BUY"
    if momentum <= -2:
        return "CAUTION"
    if score >= HOLD_THRESHOLD:
        return "HOLD"
    return "NEUTRAL"


# ═══════════════════════════════════════════════════════
#  핵심 분석 함수
# ═══════════════════════════════════════════════════════

def analyze(curr_path: str, prev_path: str) -> list[StockSignal]:
    """두 스냅샷을 비교하여 종목별 시그널을 생성한다."""
    log.info("[현재] %s", curr_path)
    log.info("[이전] %s", prev_path)

    curr_df = _read_snapshot(curr_path)
    prev_df = _read_snapshot(prev_path)

    curr_stock_holders = _stock_to_holders(curr_df)
    prev_user_stocks = _user_to_stocks(prev_df)
    prev_stock_users = _stock_to_users(prev_user_stocks)
    prev_stock_holders = _stock_to_holders(prev_df)

    signals: list[StockSignal] = []

    for stock, holders in curr_stock_holders.items():
        ranks = tuple(sorted(r for r, _ in holders))
        curr_users = {u for _, u in holders}

        n_holders = len(holders)
        top_tier = sum(1 for r in ranks if r <= TOP_TIER)
        mid_tier = sum(1 for r in ranks if r <= MID_TIER)

        prev_users = prev_stock_users.get(stock, set())
        new_buyer_users = curr_users - prev_users
        dropper_users = prev_users - curr_users

        new_buyer_ranks = tuple(sorted(
            r for r, u in holders if u in new_buyer_users
        ))
        dropper_ranks = tuple(sorted(
            r for r, u in prev_stock_holders.get(stock, []) if u in dropper_users
        ))

        n_new = len(new_buyer_users)
        n_dropped = len(dropper_users)
        momentum = n_new - n_dropped

        score = _compute_score(n_holders, top_tier, mid_tier, n_new, momentum)
        signal = _classify(score, momentum)

        signals.append(StockSignal(
            stock_name=stock, signal=signal, score=score,
            n_holders=n_holders, top_tier_holders=top_tier,
            mid_tier_holders=mid_tier, n_new_buyers=n_new,
            n_droppers=n_dropped, momentum=momentum,
            holder_ranks=ranks, new_buyer_ranks=new_buyer_ranks,
            dropper_ranks=dropper_ranks,
        ))

    # 이전에 있었지만 현재 완전히 사라진 종목
    all_curr_stocks = set(curr_stock_holders.keys())
    for stock, prev_users_set in prev_stock_users.items():
        if stock in all_curr_stocks:
            continue
        prev_holders_list = prev_stock_holders.get(stock, [])
        dropper_ranks = tuple(sorted(r for r, _ in prev_holders_list))
        n_dropped = len(prev_users_set)
        score = _compute_score(0, 0, 0, 0, -n_dropped)
        signals.append(StockSignal(
            stock_name=stock,
            signal="CAUTION" if n_dropped >= 2 else "NEUTRAL",
            score=score, n_holders=0, top_tier_holders=0,
            mid_tier_holders=0, n_new_buyers=0, n_droppers=n_dropped,
            momentum=-n_dropped, holder_ranks=(),
            new_buyer_ranks=(), dropper_ranks=dropper_ranks,
        ))

    signals.sort(key=lambda s: (-s.score, s.stock_name))
    return signals


# ═══════════════════════════════════════════════════════
#  TOP20 유저 매매 내역
# ═══════════════════════════════════════════════════════

@dataclass(frozen=True)
class UserTrade:
    """개별 유저의 매매 변동."""
    rank: int
    user_nick: str
    bought: tuple[str, ...]     # 신규 매수 종목
    sold: tuple[str, ...]       # 매도(이탈) 종목


def analyze_top20_trades(curr_path: str, prev_path: str) -> list[UserTrade]:
    """TOP20 유저의 매수/매도 종목을 추출한다."""
    curr_df = _read_snapshot(curr_path)
    prev_df = _read_snapshot(prev_path)

    # 현재 TOP20 유저 목록 (rank 기준)
    curr_top20 = curr_df[curr_df["rank"] <= MID_TIER]
    top20_users: dict[str, int] = {}
    for _, row in curr_top20.iterrows():
        rank = int(row["rank"]) if pd.notna(row["rank"]) else 999
        nick = row["user_nick"]
        if nick not in top20_users or rank < top20_users[nick]:
            top20_users[nick] = rank

    curr_user_stocks = _user_to_stocks(curr_df)
    prev_user_stocks = _user_to_stocks(prev_df)

    trades: list[UserTrade] = []
    for nick, rank in sorted(top20_users.items(), key=lambda x: x[1]):
        curr_stocks = curr_user_stocks.get(nick, set())
        prev_stocks = prev_user_stocks.get(nick, set())

        bought = tuple(sorted(curr_stocks - prev_stocks))
        sold = tuple(sorted(prev_stocks - curr_stocks))

        if bought or sold:
            trades.append(UserTrade(
                rank=rank, user_nick=nick, bought=bought, sold=sold,
            ))

    return trades


# ═══════════════════════════════════════════════════════
#  리포트 생성
# ═══════════════════════════════════════════════════════

def signals_to_dataframe(signals: list[StockSignal]) -> pd.DataFrame:
    rows = []
    for s in signals:
        rows.append({
            "종목": s.stock_name,
            "시그널": s.signal,
            "점수": s.score,
            "보유자수": s.n_holders,
            f"TOP{TOP_TIER}": s.top_tier_holders,
            f"TOP{MID_TIER}": s.mid_tier_holders,
            "신규매수": s.n_new_buyers,
            "이탈": s.n_droppers,
            "모멘텀": s.momentum,
            "보유자순위": ", ".join(str(r) for r in s.holder_ranks),
            "신규매수자순위": ", ".join(str(r) for r in s.new_buyer_ranks),
            "이탈자순위": ", ".join(str(r) for r in s.dropper_ranks),
        })
    return pd.DataFrame(rows)


def save_report(df: pd.DataFrame) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    ymd = datetime.now().strftime("%Y%m%d")
    n = 1
    while True:
        path = os.path.join(REPORT_DIR, f"signal_{ymd}_{n}.csv")
        if not os.path.exists(path):
            break
        n += 1
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def print_report(signals: list[StockSignal]) -> None:
    """콘솔에 구조화된 리포트를 출력한다."""
    df = signals_to_dataframe(signals)

    print(
        "\n"
        "======================================================================\n"
        "  TIMEFOLIO 따라잡기 전략 리포트\n"
        f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"  분석 대상: 상위 {RANKS_TO_SCRAPE}명\n"
        "======================================================================"
    )

    signal_order = ["STRONG_BUY", "BUY", "HOLD", "CAUTION", "NEUTRAL"]
    labels = {
        "STRONG_BUY": "[STRONG BUY] 강력 매수",
        "BUY":        "[BUY] 매수 추천",
        "HOLD":       "[HOLD] 보유/관망",
        "CAUTION":    "[CAUTION] 주의",
        "NEUTRAL":    "[NEUTRAL] 중립",
    }
    display_cols = ["종목", "점수", "보유자수", f"TOP{TOP_TIER}", f"TOP{MID_TIER}",
                    "신규매수", "이탈", "모멘텀"]

    for sig in signal_order:
        subset = df[df["시그널"] == sig]
        if subset.empty:
            continue
        available = [c for c in display_cols if c in subset.columns]
        print(f"\n--- {labels[sig]} ({len(subset)}종목) ---")
        print(subset[available].to_string(index=False))

    print("\n" + "=" * 70)

    buys = [s for s in signals if s.signal in ("STRONG_BUY", "BUY")]
    if buys:
        print(f"\n** 매수 추천 종목 ({len(buys)}개) **")
        for s in buys:
            holders_str = f"보유 {s.n_holders}명 (TOP{TOP_TIER}: {s.top_tier_holders})"
            momentum_str = ""
            if s.n_new_buyers > 0:
                rank_str = ",".join(str(r) for r in s.new_buyer_ranks)
                momentum_str = f" | 신규매수 {s.n_new_buyers}명(순위: {rank_str})"
            print(f"  -> {s.stock_name:12s}  점수 {s.score:5.1f}  {holders_str}{momentum_str}")

    cautions = [s for s in signals if s.signal == "CAUTION"]
    if cautions:
        print(f"\n** 주의 종목 ({len(cautions)}개) **")
        for s in cautions:
            if s.n_holders > 0:
                print(f"  -> {s.stock_name:12s}  이탈 {s.n_droppers}명, 잔여 {s.n_holders}명")
            else:
                print(f"  -> {s.stock_name:12s}  전원 이탈 ({s.n_droppers}명)")

    top_consensus = sorted(signals, key=lambda s: -s.n_holders)[:10]
    print(f"\n** 컨센서스 Top 10 (가장 많은 유저가 보유) **")
    for i, s in enumerate(top_consensus, 1):
        pct = s.n_holders / RANKS_TO_SCRAPE * 100
        bar = "#" * int(pct / 5)
        print(f"  {i:2d}. {s.stock_name:12s}  {s.n_holders:2d}명 ({pct:4.1f}%) {bar}")

    print("\n" + "=" * 70)


def print_top20_trades(trades: list[UserTrade]) -> None:
    """TOP20 유저 매매 내역을 콘솔에 출력한다."""
    if not trades:
        print("\n** TOP20 유저 매매 변동 없음 **")
        return

    print(f"\n** TOP20 유저 매매 내역 ({len(trades)}명 변동) **")
    for t in trades:
        parts = [f"  {t.rank:2d}위 {t.user_nick}"]
        if t.bought:
            parts.append(f"    + 매수: {', '.join(t.bought)}")
        if t.sold:
            parts.append(f"    - 매도: {', '.join(t.sold)}")
        print("\n".join(parts))

    print("\n" + "=" * 70)


def run(curr_key: str | None = None, prev_key: str | None = None) -> pd.DataFrame:
    """분석 실행 → 리포트 출력 → CSV 저장."""
    curr_path, prev_path = pick_snapshots(curr_key, prev_key)
    signals = analyze(curr_path, prev_path)
    print_report(signals)

    df = signals_to_dataframe(signals)
    report_path = save_report(df)
    print(f"\n>> 상세 리포트 저장: {report_path}")
    return df
