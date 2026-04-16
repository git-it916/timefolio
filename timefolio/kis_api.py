"""
KIS (Korea Investment & Securities) API - 경량 래퍼.

타임폴리오 차익거래 봇에서 실시간 시세 조회 전용.
원본: strategy_ensemble/src/execution/kis_api.py
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import requests

log = logging.getLogger(__name__)

KIS_BASE_URL_REAL = "https://openapi.koreainvestment.com:9443"
KIS_BASE_URL_PAPER = "https://openapivts.koreainvestment.com:29443"


@dataclass(frozen=True)
class KISAuth:
    """KIS API 인증 정보."""
    app_key: str
    app_secret: str
    account_number: str
    is_paper: bool = True

    @property
    def base_url(self) -> str:
        return KIS_BASE_URL_PAPER if self.is_paper else KIS_BASE_URL_REAL


class KISApi:
    """KIS Open API 시세 조회 전용 래퍼."""

    def __init__(self, auth: KISAuth):
        self.auth = auth
        self._access_token: str | None = None
        self._token_expires: datetime | None = None

    def _is_token_expired(self) -> bool:
        if self._token_expires is None:
            return True
        return datetime.now() >= self._token_expires - timedelta(minutes=5)

    def _refresh_token(self) -> None:
        url = f"{self.auth.base_url}/oauth2/tokenP"
        data = {
            "grant_type": "client_credentials",
            "appkey": self.auth.app_key,
            "appsecret": self.auth.app_secret,
        }
        response = requests.post(url, json=data, timeout=10)
        response.raise_for_status()
        result = response.json()
        self._access_token = result["access_token"]

        expires_at = result.get("access_token_token_expired")
        if expires_at:
            try:
                self._token_expires = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                self._token_expires = datetime.now() + timedelta(hours=23)
        else:
            self._token_expires = datetime.now() + timedelta(hours=23)
        log.info("KIS access token refreshed")

    def _get_headers(self, tr_id: str) -> dict[str, str]:
        if self._access_token is None or self._is_token_expired():
            self._refresh_token()

        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._access_token}",
            "appkey": self.auth.app_key,
            "appsecret": self.auth.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def get_price(self, stock_code: str) -> dict[str, Any]:
        """현재가 조회.

        Args:
            stock_code: 6자리 종목코드 (예: "005930")

        Returns:
            {"stock_code", "name", "price", "change", "change_rate",
             "volume", "high", "low", "open"}
        """
        url = f"{self.auth.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self._get_headers("FHKST01010100")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
        }

        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("rt_cd") != "0":
            raise RuntimeError(f"KIS API error: {data.get('msg1')}")

        output = data.get("output", {})
        return {
            "stock_code": stock_code,
            "name": output.get("hts_kor_isnm", ""),
            "price": int(output.get("stck_prpr", 0)),
            "change": int(output.get("prdy_vrss", 0)),
            "change_rate": float(output.get("prdy_ctrt", 0)),
            "volume": int(output.get("acml_vol", 0)),
            "high": int(output.get("stck_hgpr", 0)),
            "low": int(output.get("stck_lwpr", 0)),
            "open": int(output.get("stck_oprc", 0)),
        }

    def get_prices(
        self, stock_codes: list[str], delay: float = 0.05,
    ) -> dict[str, dict[str, Any]]:
        """여러 종목 현재가 일괄 조회 (순차).

        Args:
            stock_codes: 종목코드 리스트
            delay: 호출 간 대기(초). KIS 속도 제한 준수.

        Returns:
            {stock_code: price_info, ...}
        """
        results: dict[str, dict[str, Any]] = {}
        for code in stock_codes:
            try:
                results[code] = self.get_price(code)
            except Exception as e:
                log.warning("KIS get_price failed for %s: %s", code, e)
                results[code] = {"stock_code": code, "price": 0, "error": str(e)}
            time.sleep(delay)
        return results

    def get_prices_concurrent(
        self, stock_codes: list[str], max_workers: int = 10,
    ) -> dict[str, dict[str, Any]]:
        """여러 종목 현재가 병렬 조회.

        ThreadPoolExecutor로 동시에 최대 max_workers개 요청.
        KIS API 초당 20건 제한 → max_workers=10이 안전.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # 토큰 미리 확보
        if self._access_token is None or self._is_token_expired():
            self._refresh_token()

        results: dict[str, dict[str, Any]] = {}

        def _fetch(code: str) -> tuple[str, dict[str, Any]]:
            try:
                return code, self.get_price(code)
            except Exception as e:
                log.warning("KIS get_price failed for %s: %s", code, e)
                return code, {"stock_code": code, "price": 0, "error": str(e)}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch, code): code for code in stock_codes}
            for future in as_completed(futures):
                code, data = future.result()
                results[code] = data

        return results
