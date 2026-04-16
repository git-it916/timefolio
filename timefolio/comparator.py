"""
타임폴리오 vs KIS 실시간 가격 비교기.

포트폴리오 모달에서 추출한 종목코드/현재가와
KIS API 실시간 시세를 비교하여 차익 기회를 식별한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from timefolio.config import MIN_ARB_PCT
from timefolio.kis_api import KISApi

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArbitrageOpportunity:
    """차익 기회 데이터."""
    stock_code: str       # "005930"
    stock_name: str       # "삼성전자"
    tf_price: int         # 타임폴리오 현재가
    kis_price: int        # KIS 실시간 가격
    diff: int             # kis_price - tf_price
    diff_pct: float       # (kis - tf) / tf * 100
    suggested_weight: float  # 추천 비중%


def _parse_price(price_str: str) -> int:
    """'217,000' -> 217000, '' -> 0."""
    cleaned = (price_str or "").replace(",", "").strip()
    if not cleaned:
        return 0
    try:
        return int(float(cleaned))
    except ValueError:
        return 0


def _strip_code(code: str) -> str:
    """'A005930' -> '005930'."""
    return code.lstrip("A").strip()


class PriceComparator:
    """타임폴리오 vs KIS 가격 비교."""

    def __init__(self, kis_api: KISApi):
        self.kis = kis_api

    def compare(
        self,
        stocks: list[dict],
        min_arb_pct: float | None = None,
    ) -> list[ArbitrageOpportunity]:
        """종목 리스트의 가격을 비교하여 차익 기회를 반환.

        Args:
            stocks: [{"code": "A005930", "name": "삼성전자",
                       "tf_price": "217,000", "weight": "34.0"}, ...]
            min_arb_pct: 최소 차익률 % (None이면 config 기본값)

        Returns:
            diff_pct 내림차순 정렬된 차익 기회 리스트
        """
        threshold = min_arb_pct if min_arb_pct is not None else MIN_ARB_PCT

        # 중복 종목 제거 (코드 기준)
        seen_codes: set[str] = set()
        unique_stocks: list[dict] = []
        for s in stocks:
            code = _strip_code(s.get("code", ""))
            if code and code not in seen_codes:
                seen_codes.add(code)
                unique_stocks.append(s)

        if not unique_stocks:
            log.warning("비교할 종목이 없습니다.")
            return []

        # KIS 일괄 시세 조회 (병렬)
        codes = [_strip_code(s["code"]) for s in unique_stocks]
        log.info("KIS 시세 조회: %d종목 (병렬)", len(codes))
        kis_prices = self.kis.get_prices_concurrent(codes)

        opportunities: list[ArbitrageOpportunity] = []
        for s in unique_stocks:
            code = _strip_code(s["code"])
            name = s.get("name", "")
            tf_price = _parse_price(s.get("tf_price", ""))
            weight = float(s.get("weight", 0) or 0)

            kis_data = kis_prices.get(code, {})
            kis_price = kis_data.get("price", 0)

            if tf_price <= 0 or kis_price <= 0:
                log.debug("가격 없음: %s (tf=%d, kis=%d)", name, tf_price, kis_price)
                continue

            diff = kis_price - tf_price
            diff_pct = round(diff / tf_price * 100, 2)

            log.info(
                "  %s(%s): TF=%d KIS=%d diff=%+d (%.2f%%)",
                name, code, tf_price, kis_price, diff, diff_pct,
            )

            if diff_pct > threshold:
                opportunities.append(ArbitrageOpportunity(
                    stock_code=code,
                    stock_name=name,
                    tf_price=tf_price,
                    kis_price=kis_price,
                    diff=diff,
                    diff_pct=diff_pct,
                    suggested_weight=weight,
                ))

        opportunities.sort(key=lambda o: -o.diff_pct)
        log.info("차익 기회: %d종목 (임계값 %.1f%%)", len(opportunities), threshold)
        return opportunities


def print_comparison(
    stocks: list[dict],
    opportunities: list[ArbitrageOpportunity],
) -> None:
    """비교 결과를 콘솔에 출력."""
    print("\n" + "=" * 70)
    print("  TIMEFOLIO vs KIS 가격 비교")
    print("=" * 70)

    if not opportunities:
        print("  차익 기회 없음")
        print("=" * 70)
        return

    print(f"\n  차익 기회 {len(opportunities)}건 (TF 가격 < KIS 가격):\n")
    print(f"  {'종목':>10s}  {'코드':>6s}  {'TF가격':>10s}  {'KIS가격':>10s}  {'차이':>8s}  {'차익%':>6s}  {'비중':>5s}")
    print("  " + "-" * 62)
    for o in opportunities:
        print(
            f"  {o.stock_name:>10s}  {o.stock_code:>6s}"
            f"  {o.tf_price:>10,d}  {o.kis_price:>10,d}"
            f"  {o.diff:>+8,d}  {o.diff_pct:>+5.2f}%"
            f"  {o.suggested_weight:>5.1f}"
        )
    print("\n" + "=" * 70)
