"""
타임폴리오 HTTP API 클라이언트.

Selenium 없이 순수 HTTP로 로그인, 랭킹 조회, 포트폴리오 조회, 주문 제출.
모든 엔드포인트는 probe_api.py + JS 소스 분석으로 검증 완료.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://hankyung.timefolio.net"


@dataclass(frozen=True)
class StockPosition:
    """상위 유저 포트폴리오의 종목 정보."""
    prod_id: str       # "A005930"
    prod_nm: str       # "삼성전자"
    close: int         # 현재가
    wei: float         # 비중%
    ch_pct: float      # 당일등락%
    pos: int           # 보유수량
    avg_prc: float     # 평단가
    prft: int          # 수익금


class TimefolioApiClient:
    """타임폴리오 REST API 클라이언트."""

    def __init__(self, email: str, password: str):
        self._email = email
        self._password = password
        self._session = requests.Session()
        self._token: str | None = None
        self._pf_id: int | None = None
        self._ctst_id: int | None = None

    @property
    def headers(self) -> dict[str, str]:
        if not self._token:
            raise RuntimeError("로그인이 필요합니다.")
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def login(self) -> dict[str, Any]:
        """로그인 후 JWT 토큰과 포트폴리오 ID를 설정."""
        r = self._session.post(
            f"{BASE_URL}/api/Auth/Login",
            json={"email": self._email, "password": self._password},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        self._token = data["accessToken"]
        self._session.cookies.update(r.cookies)

        pfs = data.get("pfs", [])
        if pfs:
            self._pf_id = pfs[0]["Id"]
            self._ctst_id = pfs[0].get("ctstId")

        log.info(
            "타임폴리오 로그인 성공: pfId=%s, ctstId=%s",
            self._pf_id, self._ctst_id,
        )
        return data

    def get_rankings(self, date: str | None = None, ctst_id: int | None = None) -> list[dict]:
        """대회 랭킹 목록 조회.

        Returns:
            [{"Id": pfId, "userNick": "강서윤", "currNav": 1323.47, "rank": 1, ...}, ...]
        """
        d = date or datetime.now().strftime("%Y-%m-%d")
        cid = ctst_id or self._ctst_id or 86
        r = self._session.get(
            f"{BASE_URL}/api/Contest/PfList",
            params={"ctstId": cid, "d": d},
            headers=self.headers,
            timeout=10,
        )
        r.raise_for_status()
        rankings = r.json()
        log.info("랭킹 조회: %d명", len(rankings))
        return rankings

    def get_portfolio(self, pf_id: int, date: str | None = None) -> list[StockPosition]:
        """상위 유저 포트폴리오 상세 조회 (50등 이내만 가능).

        Returns:
            [StockPosition(prod_id="A005930", ...), ...]
        """
        d = date or datetime.now().strftime("%Y-%m-%d")
        r = self._session.get(
            f"{BASE_URL}/api/Contest/TopRankDetail",
            params={"d": d, "pfId": pf_id},
            headers=self.headers,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        if isinstance(data, dict) and "msg" in data:
            log.warning("포트폴리오 조회 실패 (pfId=%d): %s", pf_id, data["msg"])
            return []

        positions = []
        for p in data.get("pos", []):
            positions.append(StockPosition(
                prod_id=p.get("prodId", ""),
                prod_nm=p.get("prodNm", ""),
                close=int(p.get("close", 0)),
                wei=float(p.get("wei", 0)),
                ch_pct=float(p.get("chPct", 0)),
                pos=int(p.get("pos", 0)),
                avg_prc=float(p.get("avgPrc", 0)),
                prft=int(p.get("prft", 0)),
            ))
        return positions

    def get_top_n_stocks(self, n: int = 5, date: str | None = None) -> list[dict]:
        """상위 N명의 포트폴리오에서 고유 종목 리스트 추출.

        Returns:
            [{"code": "A005930", "name": "삼성전자",
              "tf_price": "217000", "weight": "34.0"}, ...]
        """
        rankings = self.get_rankings(date)
        seen_codes: set[str] = set()
        stocks: list[dict] = []

        for rank_entry in rankings[:n]:
            pf_id = rank_entry["Id"]
            nick = rank_entry.get("userNick", "?")
            positions = self.get_portfolio(pf_id, date)

            for pos in positions:
                if pos.prod_id and pos.prod_id not in seen_codes:
                    seen_codes.add(pos.prod_id)
                    stocks.append({
                        "code": pos.prod_id,
                        "name": pos.prod_nm,
                        "tf_price": str(pos.close),
                        "weight": str(pos.wei),
                    })

            log.info(
                "  %d위 %s: %d종목 (%d신규)",
                rank_entry.get("rank", "?"), nick,
                len(positions), sum(1 for p in positions if p.prod_id not in seen_codes),
            )
            time.sleep(0.1)  # 속도 제한

        log.info("총 %d개 고유 종목 수집 (상위 %d명)", len(stocks), n)
        return stocks

    def search_stock(self, term: str) -> list[dict]:
        """종목 검색.

        Returns:
            [{"Id": "A005930", "nm": "삼성전자", "sec": "45"}, ...]
        """
        r = self._session.get(
            f"{BASE_URL}/api/Util/SearchProducts",
            params={"term": term},
            headers=self.headers,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def add_order(
        self,
        prod_id: str,
        wei: float,
        ls: str = "L",
        ex: str = "E",
        limit_idx: int = 5,
        limit_prc: int | None = None,
        stop_prc: int | None = None,
        hm0: str | None = None,
        hm1: str | None = None,
        date: str | None = None,
    ) -> dict[str, Any]:
        """주문 제출.

        Args:
            prod_id: 종목코드 (예: "A005930")
            wei: 비중 %
            ls: "L"(Long) or "S"(Short)
            ex: "E"(Entry/매수) or "X"(Exit/매도)
            limit_idx: 상대호가 틱수 (기본 5)
            limit_prc: 지정가 (None이면 상대호가)
            stop_prc: STOP 가격 (None이면 미사용)
            hm0: 시작 시간 "HH:MM" (None이면 현재 시간)
            hm1: 종료 시간 (None이면 즉시 실행)
            date: 주문일 (None이면 오늘)

        Returns:
            {"data": "", "warnings": []}
        """
        d = date or datetime.now().strftime("%Y-%m-%d")
        start_time = hm0 or datetime.now().strftime("%H:%M")

        # JS 소스 기준: 미사용 필드는 null (0이 아님)
        # limitPrc: E==="Limit" ? A : null
        # limitIdx: E==="Opp" ? k : E==="My" ? -(P) : null
        # stopPrc: E==="Stop" ? B : null
        if limit_prc is not None:
            lp, li = limit_prc, None
        elif stop_prc is not None:
            lp, li = None, None
        else:
            lp, li = None, limit_idx  # 상대호가

        order_body = {
            "d": d,
            "pfId": self._pf_id,
            "prodId": prod_id,
            "ls": ls,
            "ex": ex,
            "wei": wei,
            "exitAll": False,
            "limitPrc": lp,
            "limitIdx": li,
            "stopPrc": stop_prc,
            "hm0": start_time,
            "hm1": hm1,
        }

        log.info(
            "주문 제출: %s %s%s wei=%.1f%% limitIdx=%d",
            prod_id, ls, ex, wei, limit_idx,
        )

        r = self._session.post(
            f"{BASE_URL}/api/Portfolio/AddOrder",
            headers=self.headers,
            json=order_body,
            timeout=10,
        )

        if r.status_code != 200:
            # 에러 본문 캡처
            try:
                err_body = r.json()
            except Exception:
                err_body = r.text[:200]
            log.error("주문 HTTP %d: %s (body=%s)", r.status_code, err_body, order_body)
            raise RuntimeError(f"주문 실패 HTTP {r.status_code}: {err_body}")

        result = r.json()
        warnings = result.get("warnings", [])
        errors = result.get("errors", [])
        if errors:
            log.error("주문 오류: %s", errors)
            raise RuntimeError(f"주문 실패: {errors}")
        if warnings:
            log.warning("주문 경고: %s", warnings)

        log.info("주문 성공: %s", result)
        return result

    def get_orders(self, date: str | None = None) -> list[dict]:
        """당일 주문 목록 조회."""
        d = date or datetime.now().strftime("%Y-%m-%d")
        r = self._session.get(
            f"{BASE_URL}/api/Portfolio/Orders",
            params={"pfId": self._pf_id, "d": d},
            headers=self.headers,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
