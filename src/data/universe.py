"""Assemble the normalised base-universe DataFrame from FMP.

The output frame has one row per ticker and exactly the columns every strategy expects.
Fields a given FMP plan does not expose are left as ``NaN`` (optional filters treat NaN as
"pass"; required filters naturally exclude NaN rows). All derived metrics that depend on
intraday or previous-close data (relative volume, gap %) are computed here -- never in
strategy code.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

import config
from data.fmp_client import FMPClient
from market_calendar import trading_days_offset

log = logging.getLogger(__name__)

# Columns guaranteed to exist on the universe frame.
COLUMNS = [
    "symbol", "company", "price", "market_cap", "avg_volume", "rel_volume",
    "sma20", "sma50", "sma200", "rsi", "perf_1w", "perf_1m", "week_52_high",
    "sales_qoq", "eps_qoq", "debt_equity", "earnings_trading_days", "gap_pct",
    "float_shares", "short_pct_float", "week_volatility",
]


def _num(value: Any) -> float:
    try:
        if value is None:
            return np.nan
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _safe_div(a: float, b: float) -> float:
    a, b = _num(a), _num(b)
    if np.isnan(a) or np.isnan(b) or b == 0:
        return np.nan
    return a / b


def build_universe(mode: str, client: FMPClient | None = None) -> pd.DataFrame:
    """Build and base-filter the universe for ``mode``."""
    mode = config.validate_mode(mode)
    client = client or FMPClient()

    screened = client.screen(mode)
    symbols = [r["symbol"] for r in screened][: config.SCREEN_LIMIT]
    if not symbols:
        log.warning("Screener returned no symbols")
        return pd.DataFrame(columns=COLUMNS)

    quotes = {q["symbol"]: q for q in client.quotes(symbols)}

    today = date.today()
    cal = client.earnings_calendar(today - timedelta(days=20), today + timedelta(days=15))
    earnings_dates: dict[str, str] = {}
    for entry in cal:
        sym = entry.get("symbol")
        when = entry.get("date")
        if sym and when and sym not in earnings_dates:
            earnings_dates[sym] = when

    rows: list[dict[str, Any]] = []
    for sym in symbols:
        q = quotes.get(sym, {})
        price = _num(q.get("price"))
        prev_close = _num(q.get("previousClose"))
        day_open = _num(q.get("open"))
        avg_volume = _num(q.get("avgVolume"))
        volume = _num(q.get("volume"))
        year_high = _num(q.get("yearHigh"))

        rsi = _num(client.technical(sym, "rsi", 14).get("rsi"))
        sma20 = _num(client.technical(sym, "sma", 20).get("sma"))
        change = client.price_change(sym)
        ratios = client.ratios_ttm(sym)
        growth = client.income_growth(sym)
        flt = client.shares_float(sym)

        earn = earnings_dates.get(sym)
        if earn:
            try:
                etd: float = trading_days_offset(date.fromisoformat(earn[:10]), today)
            except ValueError:
                etd = np.nan
        else:
            etd = np.nan

        rows.append(
            {
                "symbol": sym,
                "company": q.get("name", ""),
                "price": price,
                "market_cap": _num(q.get("marketCap")),
                "avg_volume": avg_volume,
                "rel_volume": _safe_div(volume, avg_volume),
                "sma20": sma20,
                "sma50": _num(q.get("priceAvg50")),
                "sma200": _num(q.get("priceAvg200")),
                "rsi": rsi,
                "perf_1w": _num(change.get("5D")),
                "perf_1m": _num(change.get("1M")),
                "week_52_high": (
                    bool(price >= 0.97 * year_high)
                    if not np.isnan(price) and not np.isnan(year_high)
                    else np.nan
                ),
                "sales_qoq": _num(growth.get("growthRevenue")) * 100,
                "eps_qoq": _num(growth.get("growthEPS")) * 100,
                "debt_equity": _num(ratios.get("debtEquityRatioTTM")),
                "earnings_trading_days": etd,
                "gap_pct": _safe_div(day_open - prev_close, prev_close) * 100,
                "float_shares": _num(flt.get("floatShares")),
                "short_pct_float": _num(flt.get("shortPercentFloat") or flt.get("shortFloat")),
                "week_volatility": np.nan,  # not provided by FMP base plan
            }
        )

    df = pd.DataFrame(rows, columns=COLUMNS)
    return apply_base_filter(df, mode)


def apply_base_filter(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Apply the shared base-universe gate (market cap / price / avg volume)."""
    if df.empty:
        return df
    if mode == "tight":
        cap, price_min, vol_min = (
            config.BASE_MARKET_CAP_MAX_TIGHT,
            config.BASE_PRICE_MIN_TIGHT,
            config.BASE_AVG_VOLUME_MIN_TIGHT,
        )
        squeeze_floor = config.SQUEEZE_AVG_VOL_TIGHT
    else:
        cap, price_min, vol_min = (
            config.BASE_MARKET_CAP_MAX_LOOSE,
            config.BASE_PRICE_MIN_LOOSE,
            config.BASE_AVG_VOLUME_MIN_LOOSE,
        )
        squeeze_floor = config.SQUEEZE_AVG_VOL_LOOSE

    # Keep the volume floor low enough that Squeeze candidates are not pre-excluded;
    # each strategy still applies its own volume threshold on top.
    vol_min = min(vol_min, squeeze_floor)

    mask = (
        (df["market_cap"] < cap)
        & (df["price"] > price_min)
        & (df["avg_volume"] > vol_min)
    )
    return df[mask].reset_index(drop=True)
