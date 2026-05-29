"""Assemble the normalised base-universe DataFrame from Yahoo Finance.

The output frame has one row per ticker and exactly the columns every strategy expects.
Fields the data source does not expose are left as ``NaN`` (optional filters treat NaN as
"pass"; required filters naturally exclude NaN rows). All derived metrics that depend on
prior-close data (relative volume, gap %) are computed in the data layer -- never in
strategy code.

Because there is no server-side screener on the free tier, the universe is built
client-side: scan all NASDAQ symbols' price history, gate cheaply on price/volume, then on
market cap, then enrich the survivors with fundamentals + short interest. Two configurable
caps (``MAX_PREFILTER``, ``MAX_ENRICH``) bound the number of per-ticker lookups so a daily
run stays within a sane runtime.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

import config
from data import yahoo
from market_calendar import trading_days_offset

log = logging.getLogger(__name__)

# Columns guaranteed to exist on the universe frame.
COLUMNS = [
    "symbol", "company", "price", "market_cap", "avg_volume", "rel_volume",
    "sma20", "sma50", "sma200", "rsi", "perf_1w", "perf_1m", "week_52_high",
    "sales_qoq", "eps_qoq", "debt_equity", "earnings_trading_days", "gap_pct",
    "float_shares", "short_pct_float", "days_to_cover", "week_volatility",
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


def _coalesce(*values: float) -> float:
    """First non-NaN value, else NaN."""
    for value in values:
        v = _num(value)
        if not np.isnan(v):
            return v
    return np.nan


def compute_short_metrics(
    short_shares: float,
    float_shares: float,
    avg_volume: float,
    short_pct_outstanding: float = np.nan,
    short_ratio: float = np.nan,
) -> tuple[float, float]:
    """Derive (short % of float, days to cover) from whatever inputs are available.

    Prefers short-of-float (short shares / float); falls back to a provider's
    percent-of-outstanding figure when float is unknown. Days to cover prefers a provider's
    ratio, else short shares / avg volume.
    """
    short_pct = _safe_div(short_shares, float_shares) * 100
    if np.isnan(short_pct):
        pct_out = _num(short_pct_outstanding)
        if not np.isnan(pct_out):
            short_pct = pct_out * 100
    days = _coalesce(short_ratio, _safe_div(short_shares, avg_volume))
    return short_pct, days


def _base_thresholds(mode: str) -> tuple[float, float, float]:
    """Return (market_cap_max, price_min, avg_volume_min) for ``mode``.

    The volume floor is dropped to the Squeeze floor so squeeze candidates survive the
    shared gate; each strategy still applies its own volume threshold on top.
    """
    if mode == "tight":
        cap, price_min, vol_min = (
            config.BASE_MARKET_CAP_MAX_TIGHT,
            config.BASE_PRICE_MIN_TIGHT,
            config.BASE_AVG_VOLUME_MIN_TIGHT,
        )
        vol_min = min(vol_min, config.SQUEEZE_AVG_VOL_TIGHT)
    else:
        cap, price_min, vol_min = (
            config.BASE_MARKET_CAP_MAX_LOOSE,
            config.BASE_PRICE_MIN_LOOSE,
            config.BASE_AVG_VOLUME_MIN_LOOSE,
        )
        vol_min = min(vol_min, config.SQUEEZE_AVG_VOL_LOOSE)
    return cap, price_min, vol_min


def build_universe(mode: str) -> pd.DataFrame:
    """Build and base-filter the universe for ``mode`` using Yahoo Finance."""
    mode = config.validate_mode(mode)
    cap, price_min, vol_min = _base_thresholds(mode)

    symbols = yahoo.fetch_nasdaq_symbols()
    metrics = yahoo.scan_price_metrics(symbols, config.HISTORY_PERIOD, config.YF_BATCH_SIZE)
    if metrics.empty:
        log.warning("No price history returned from Yahoo")
        return pd.DataFrame(columns=COLUMNS)

    # Cheap gate: price + average volume (computed entirely from history).
    metrics = metrics[(metrics["price"] > price_min) & (metrics["avg_volume"] > vol_min)]
    metrics = metrics.sort_values("avg_dollar_volume", ascending=False).head(config.MAX_PREFILTER)
    log.info("Passed price/volume gate: %d", len(metrics))

    # Market-cap gate (cheap fast_info lookup).
    caps = yahoo.fetch_market_caps(metrics["symbol"].tolist())
    metrics["market_cap"] = metrics["symbol"].map(caps)
    metrics = metrics[metrics["market_cap"] < cap]
    metrics = metrics.sort_values("rel_volume", ascending=False).head(config.MAX_ENRICH)
    log.info("Passed market-cap gate (small-caps): %d", len(metrics))

    # Enrich survivors with fundamentals + short interest.
    today = date.today()
    rows: list[dict[str, Any]] = []
    for _, m in metrics.iterrows():
        sym = m["symbol"]
        f = yahoo.fetch_fundamentals(sym)

        short_pct_float, days_to_cover = compute_short_metrics(
            short_shares=f.get("shares_short", np.nan),
            float_shares=f.get("float_shares", np.nan),
            avg_volume=m["avg_volume"],
            short_pct_outstanding=np.nan,
            short_ratio=f.get("short_ratio", np.nan),
        )
        short_pct_float = _coalesce(short_pct_float, f.get("short_pct_float"))

        earn = f.get("earnings_date")
        etd = trading_days_offset(earn, today) if isinstance(earn, date) else np.nan

        rows.append(
            {
                "symbol": sym,
                "company": f.get("company", sym),
                "price": m["price"],
                "market_cap": _coalesce(f.get("market_cap"), m["market_cap"]),
                "avg_volume": m["avg_volume"],
                "rel_volume": m["rel_volume"],
                "sma20": m["sma20"],
                "sma50": m["sma50"],
                "sma200": m["sma200"],
                "rsi": m["rsi"],
                "perf_1w": m["perf_1w"],
                "perf_1m": m["perf_1m"],
                "week_52_high": m["week_52_high"],
                "sales_qoq": f.get("sales_qoq", np.nan),
                "eps_qoq": f.get("eps_qoq", np.nan),
                "debt_equity": f.get("debt_equity", np.nan),
                "earnings_trading_days": etd,
                "gap_pct": m["gap_pct"],
                "float_shares": f.get("float_shares", np.nan),
                "short_pct_float": short_pct_float,
                "days_to_cover": days_to_cover,
                "week_volatility": m["week_volatility"],
            }
        )

    df = pd.DataFrame(rows, columns=COLUMNS)
    return apply_base_filter(df, mode)


def apply_base_filter(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Apply the shared base-universe gate (market cap / price / avg volume)."""
    if df.empty:
        return df
    cap, price_min, vol_min = _base_thresholds(mode)
    mask = (
        (df["market_cap"] < cap)
        & (df["price"] > price_min)
        & (df["avg_volume"] > vol_min)
    )
    return df[mask].reset_index(drop=True)
