"""Financial Modeling Prep REST client with rate limiting and daily on-disk caching.

Network and provider concerns live here so that strategy code stays pure. Endpoints
that change at most once per day (fundamentals, technicals, calendars) are cached under
``CACHE_DIR/<today>/``; intraday-sensitive calls (quotes) are always fetched fresh.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

import config

log = logging.getLogger(__name__)


class RateLimiter:
    """Spaces out calls and enforces a hard daily budget (FMP free tier ~250/day)."""

    def __init__(self, min_interval: float, max_calls: int) -> None:
        self.min_interval = min_interval
        self.max_calls = max_calls
        self._last = 0.0
        self._count = 0

    def acquire(self) -> None:
        if self._count >= self.max_calls:
            raise RuntimeError(f"FMP daily call budget ({self.max_calls}) exhausted")
        delta = time.monotonic() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()
        self._count += 1


class FMPClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_dir: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else config.FMP_API_KEY
        if not self.api_key:
            raise ValueError("FMP_API_KEY is not set")
        self.base_url = (base_url or config.FMP_BASE_URL).rstrip("/")
        self.cache_dir = Path(cache_dir or config.CACHE_DIR) / date.today().isoformat()
        self.limiter = RateLimiter(
            config.FMP_MIN_INTERVAL_SECONDS, config.FMP_MAX_CALLS_PER_DAY
        )

    # ------------------------------------------------------------------ #
    # transport
    # ------------------------------------------------------------------ #
    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _get(
        self, path: str, params: dict[str, Any] | None = None, cache_key: str | None = None
    ) -> Any:
        if cache_key:
            cached = self._cache_path(cache_key)
            if cached.exists():
                log.debug("cache hit: %s", cache_key)
                return json.loads(cached.read_text())

        params = dict(params or {})
        params["apikey"] = self.api_key
        url = f"{self.base_url}/{path.lstrip('/')}"

        data: Any = None
        for attempt in range(3):
            try:
                self.limiter.acquire()
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.RequestException as exc:
                log.warning("FMP %s failed (attempt %d/3): %s", path, attempt + 1, exc)
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)

        if cache_key:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(cache_key).write_text(json.dumps(data))
        return data

    # ------------------------------------------------------------------ #
    # endpoints
    # ------------------------------------------------------------------ #
    def screen(self, mode: str) -> list[dict[str, Any]]:
        """Stock screener constrained to the NASDAQ small-cap base universe."""
        if mode == "tight":
            cap, price, vol = (
                config.BASE_MARKET_CAP_MAX_TIGHT,
                config.BASE_PRICE_MIN_TIGHT,
                config.SQUEEZE_AVG_VOL_TIGHT,  # lowest base floor that keeps squeeze names
            )
        else:
            cap, price, vol = (
                config.BASE_MARKET_CAP_MAX_LOOSE,
                config.BASE_PRICE_MIN_LOOSE,
                config.SQUEEZE_AVG_VOL_LOOSE,
            )
        params = {
            "exchange": config.EXCHANGE,
            "marketCapLowerThan": cap,
            "priceMoreThan": price,
            "volumeMoreThan": vol,
            "isActivelyTrading": "true",
            "limit": config.SCREEN_LIMIT,
        }
        return self._get("stock-screener", params, cache_key=f"screen_{mode}") or []

    def quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Batched real-time quotes (price, volumes, SMA50/200, 52w high). Not cached."""
        out: list[dict[str, Any]] = []
        for i in range(0, len(symbols), 50):
            batch = ",".join(symbols[i : i + 50])
            out.extend(self._get(f"quote/{batch}") or [])
        return out

    def technical(self, symbol: str, indicator: str, period: int) -> dict[str, Any]:
        """Latest daily technical-indicator point (e.g. rsi/sma)."""
        data = self._get(
            f"technical_indicator/daily/{symbol}",
            {"type": indicator, "period": period},
            cache_key=f"{indicator}{period}_{symbol}",
        )
        return data[0] if data else {}

    def price_change(self, symbol: str) -> dict[str, Any]:
        data = self._get(f"stock-price-change/{symbol}", cache_key=f"pricechange_{symbol}")
        return data[0] if data else {}

    def ratios_ttm(self, symbol: str) -> dict[str, Any]:
        data = self._get(f"ratios-ttm/{symbol}", cache_key=f"ratios_{symbol}")
        return data[0] if data else {}

    def income_growth(self, symbol: str) -> dict[str, Any]:
        data = self._get(
            f"income-statement-growth/{symbol}",
            {"period": "quarter", "limit": 1},
            cache_key=f"incomegrowth_{symbol}",
        )
        return data[0] if data else {}

    def earnings_calendar(self, start: date, end: date) -> list[dict[str, Any]]:
        return (
            self._get(
                "earning_calendar",
                {"from": start.isoformat(), "to": end.isoformat()},
                cache_key=f"earncal_{start.isoformat()}_{end.isoformat()}",
            )
            or []
        )

    def shares_float(self, symbol: str) -> dict[str, Any]:
        """Float / short interest (v4 endpoint). May require a paid plan."""
        v4 = self.base_url.replace("/v3", "/v4")
        url = f"{v4}/shares_float"
        try:
            self.limiter.acquire()
            resp = requests.get(
                url, params={"symbol": symbol, "apikey": self.api_key}, timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            return data[0] if data else {}
        except (requests.RequestException, IndexError, KeyError) as exc:
            log.warning("shares_float unavailable for %s: %s", symbol, exc)
            return {}
