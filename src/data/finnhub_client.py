"""Finnhub adapter — free supplementary source for short interest.

FMP gates float / short-float behind a paid plan, so we source short interest from
Finnhub's free ``/stock/short-interest`` endpoint instead. The endpoint returns biweekly
records (FINRA settlement cadence):

    {"data": [{"settlementDate": "...", "shortInterest": <shares>,
               "shortPercentOutstanding": <fraction>, "shortRatio": <days to cover>}, ...],
     "symbol": "AAPL"}

The client self-disables when ``FINNHUB_API_KEY`` is unset, returning empty results so the
universe builder simply falls back to FMP / NaN.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

import requests

import config

log = logging.getLogger(__name__)


class FinnhubClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else config.FINNHUB_API_KEY
        self.base_url = (base_url or config.FINNHUB_BASE_URL).rstrip("/")
        self.enabled = bool(self.api_key)
        if not self.enabled:
            log.info("FINNHUB_API_KEY not set — short interest falls back to FMP/NaN")

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        params = dict(params)
        params["token"] = self.api_key
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                log.warning("Finnhub %s failed (attempt %d/3): %s", path, attempt + 1, exc)
                if attempt == 2:
                    return None
                time.sleep(2 ** attempt)
        return None

    def short_interest(self, symbol: str, lookback_days: int = 90) -> dict[str, Any]:
        """Latest short-interest record for ``symbol`` (empty dict if unavailable).

        Returns keys: ``short_shares``, ``short_pct_outstanding`` (fraction),
        ``short_ratio`` (days to cover), ``settlement_date``.
        """
        if not self.enabled:
            return {}
        today = date.today()
        payload = self._get(
            "stock/short-interest",
            {
                "symbol": symbol,
                "from": (today - timedelta(days=lookback_days)).isoformat(),
                "to": today.isoformat(),
            },
        )
        records = (payload or {}).get("data") or []
        if not records:
            return {}
        latest = max(records, key=lambda r: r.get("settlementDate", ""))
        return {
            "short_shares": latest.get("shortInterest"),
            "short_pct_outstanding": latest.get("shortPercentOutstanding"),
            "short_ratio": latest.get("shortRatio"),
            "settlement_date": latest.get("settlementDate"),
        }
