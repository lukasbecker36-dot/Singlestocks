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
        self,
        path: str,
        params: dict[str, Any] | None = None,
        cache_key: str | None = None,
        optional: bool = False,
    ) -> Any:
        """GET an endpoint. ``optional`` calls return ``None`` instead of raising on failure,
        so a missing/plan-restricted enrichment endpoint degrades to NaN rather than
        aborting the whole run."""
        if cache_key:
            cached = self._cache_path(cache_key)
            if cached.exists():
                log.debug("cache hit: %s", cache_key)
                return json.loads(cached.read_text())

        params = dict(params or {})
        params["apikey"] = self.api_key
        url = f"{self.base_url}/{path.lstrip('/')}"

        # Count one logical call against the daily budget; retries don't re-charge it.
        self.limiter.acquire()
        data: Any = None
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.RequestException as exc:
                log.warning("FMP %s failed (attempt %d/3): %s", path, attempt + 1, exc)
                if attempt == 2:
                    if optional:
                        return None
                    raise
                time.sleep(2 ** attempt)

        if cache_key:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(cache_key).write_text(json.dumps(data))
        return data

    # ------------------------------------------------------------------ #
    # endpoints (FMP "stable" API; symbol is a query param, not a path segment)
    # ------------------------------------------------------------------ #
    def screen(self, mode: str) -> list[dict[str, Any]]:
        """Company screener constrained to the NASDAQ small-cap base universe."""
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
        # Essential: if the screener fails there is no universe, so let it raise.
        return self._get("company-screener", params, cache_key=f"screen_{mode}") or []

    def quote(self, symbol: str) -> dict[str, Any]:
        """Real-time quote (price, volumes, SMA50/200, 52w high, open/prev close). Fresh."""
        data = self._get("quote", {"symbol": symbol}, optional=True)
        return data[0] if data else {}

    def technical(self, symbol: str, indicator: str, period: int) -> dict[str, Any]:
        """Latest daily technical-indicator point (e.g. rsi/sma)."""
        data = self._get(
            f"technical-indicators/{indicator}",
            {"symbol": symbol, "periodLength": period, "timeframe": "1day"},
            cache_key=f"{indicator}{period}_{symbol}",
            optional=True,
        )
        return data[0] if data else {}

    def price_change(self, symbol: str) -> dict[str, Any]:
        data = self._get(
            "stock-price-change", {"symbol": symbol},
            cache_key=f"pricechange_{symbol}", optional=True,
        )
        return data[0] if data else {}

    def ratios_ttm(self, symbol: str) -> dict[str, Any]:
        data = self._get(
            "ratios-ttm", {"symbol": symbol}, cache_key=f"ratios_{symbol}", optional=True
        )
        return data[0] if data else {}

    def income_growth(self, symbol: str) -> dict[str, Any]:
        data = self._get(
            "income-statement-growth",
            {"symbol": symbol, "period": "quarter", "limit": 1},
            cache_key=f"incomegrowth_{symbol}",
            optional=True,
        )
        return data[0] if data else {}

    def earnings_calendar(self, start: date, end: date) -> list[dict[str, Any]]:
        return (
            self._get(
                "earnings-calendar",
                {"from": start.isoformat(), "to": end.isoformat()},
                cache_key=f"earncal_{start.isoformat()}_{end.isoformat()}",
                optional=True,
            )
            or []
        )

    def shares_float(self, symbol: str) -> dict[str, Any]:
        """Float data. May require a paid plan; degrades to empty if unavailable."""
        data = self._get(
            "shares-float", {"symbol": symbol}, cache_key=f"float_{symbol}", optional=True
        )
        return data[0] if data else {}
