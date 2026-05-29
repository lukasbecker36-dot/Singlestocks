"""Yahoo Finance data adapter (via ``yfinance``) — the free, key-less data source.

Because there is no server-side screener, we build the universe client-side:

1. Pull the full NASDAQ-listed symbol directory (a free public file).
2. Bulk-download daily price history in batches and compute every technical metric
   ourselves (SMA / RSI / performance / relative volume / gap / 52-week high).
3. Look up market cap cheaply (``fast_info``) to gate to small-caps.
4. Enrich the survivors with fundamentals + short interest (``Ticker.info``).

The pure metric helpers (``compute_rsi``, ``compute_price_metrics``) are import-safe and
unit-tested offline; ``yfinance`` is imported lazily only inside the network functions.

Note on timing: this runs pre-market, so the latest available daily bar is the *prior*
session. Relative volume and gap % are therefore measured on the prior session's close —
a documented limitation of using free end-of-day data rather than live pre-market feeds.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests

import config

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Universe directory
# --------------------------------------------------------------------------- #
def fetch_nasdaq_symbols() -> list[str]:
    """Return NASDAQ-listed common-stock tickers (excludes ETFs, test issues, warrants)."""
    resp = requests.get(config.NASDAQ_LIST_URL, timeout=30)
    resp.raise_for_status()
    symbols: list[str] = []
    for line in resp.text.splitlines()[1:]:  # skip header row
        if line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        symbol, _name, _cat, test_issue, _fin, _lot, etf, _next = parts[:8]
        symbol = symbol.strip()
        if test_issue == "Y" or etf == "Y" or not symbol:
            continue
        if any(c in symbol for c in (".", "$", "+")):  # warrants / units / preferred
            continue
        symbols.append(symbol)
    log.info("NASDAQ directory: %d common-stock symbols", len(symbols))
    return symbols


# --------------------------------------------------------------------------- #
# Pure technical-metric helpers (no network — unit tested)
# --------------------------------------------------------------------------- #
def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    return rsi.where(avg_loss != 0, 100.0)


def compute_price_metrics(hist: pd.DataFrame) -> dict[str, Any] | None:
    """Derive all price-based metrics from a daily OHLCV history (ascending dates).

    Returns ``None`` when there is too little history to be meaningful.
    """
    hist = hist.dropna(subset=["Close"])
    if len(hist) < 50:
        return None

    close = hist["Close"].astype(float)
    high = hist["High"].astype(float)
    low = hist["Low"].astype(float)
    vol = hist["Volume"].astype(float)
    open_ = hist["Open"].astype(float)

    price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    day_open = float(open_.iloc[-1])
    avg_volume = float(vol.tail(63).mean())  # ~3 trading months
    last_vol = float(vol.iloc[-1])

    def sma(n: int) -> float:
        return float(close.tail(n).mean()) if len(close) >= n else np.nan

    def perf(n: int) -> float:
        return (price / float(close.iloc[-(n + 1)]) - 1) * 100 if len(close) > n else np.nan

    year_high = float(close.tail(252).max())
    week_range = ((high.tail(5) - low.tail(5)) / close.tail(5)).mean() * 100

    return {
        "price": price,
        "avg_volume": avg_volume,
        "rel_volume": last_vol / avg_volume if avg_volume else np.nan,
        "sma20": sma(20),
        "sma50": sma(50),
        "sma200": sma(200),
        "rsi": float(compute_rsi(close).iloc[-1]),
        "perf_1w": perf(5),
        "perf_1m": perf(21),
        "week_52_high": bool(price >= 0.97 * year_high) if year_high else np.nan,
        "gap_pct": (day_open / prev_close - 1) * 100 if prev_close else np.nan,
        "week_volatility": float(week_range),
        "avg_dollar_volume": avg_volume * price,
    }


# --------------------------------------------------------------------------- #
# Network: history, market cap, fundamentals
# --------------------------------------------------------------------------- #
def scan_price_metrics(
    symbols: list[str], period: str, batch_size: int
) -> pd.DataFrame:
    """Bulk-download history in batches and return one metrics row per usable symbol."""
    import yfinance as yf

    rows: list[dict[str, Any]] = []
    for start in range(0, len(symbols), batch_size):
        batch = symbols[start : start + batch_size]
        try:
            data = yf.download(
                batch, period=period, interval="1d", group_by="ticker",
                auto_adjust=False, threads=True, progress=False,
            )
        except Exception as exc:  # noqa: BLE001 - yfinance raises a variety of errors
            log.warning("yfinance batch %d-%d failed: %s", start, start + len(batch), exc)
            continue

        for sym in batch:
            try:
                df = data[sym] if len(batch) > 1 else data
            except KeyError:
                continue
            if df is None or df.empty:
                continue
            metrics = compute_price_metrics(df)
            if metrics:
                rows.append({"symbol": sym, **metrics})
        log.info("scanned %d/%d symbols", min(start + batch_size, len(symbols)), len(symbols))

    return pd.DataFrame(rows)


def fetch_market_caps(symbols: list[str]) -> dict[str, float]:
    """Cheap market-cap lookup via ``fast_info`` (falls back to shares x price)."""
    import yfinance as yf

    caps: dict[str, float] = {}
    for sym in symbols:
        try:
            fi = yf.Ticker(sym).fast_info
            cap = getattr(fi, "market_cap", None)
            if not cap:  # derive from shares x last price when not provided directly
                shares = getattr(fi, "shares", None) or 0
                last = getattr(fi, "last_price", None) or 0
                cap = shares * last
            caps[sym] = float(cap) if cap else np.nan
        except Exception as exc:  # noqa: BLE001
            log.debug("market cap unavailable for %s: %s", sym, exc)
            caps[sym] = np.nan
    return caps


def fetch_fundamentals(symbol: str) -> dict[str, Any]:
    """Fundamentals + short interest for one symbol via ``Ticker.info`` (best effort)."""
    import yfinance as yf

    try:
        info = yf.Ticker(symbol).info or {}
    except Exception as exc:  # noqa: BLE001
        log.debug("info unavailable for %s: %s", symbol, exc)
        return {}

    def num(key: str) -> float:
        val = info.get(key)
        try:
            return float(val) if val is not None else np.nan
        except (TypeError, ValueError):
            return np.nan

    earnings_ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
    earnings_date: date | None = None
    if earnings_ts:
        try:
            earnings_date = datetime.fromtimestamp(earnings_ts, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            earnings_date = None

    debt_equity = num("debtToEquity")
    if not np.isnan(debt_equity):
        debt_equity /= 100.0  # yfinance reports e.g. 150.0 meaning 1.5x

    return {
        "company": info.get("longName") or info.get("shortName") or symbol,
        "market_cap": num("marketCap"),
        "float_shares": num("floatShares"),
        "short_pct_float": num("shortPercentOfFloat") * 100,
        "short_ratio": num("shortRatio"),
        "shares_short": num("sharesShort"),
        "debt_equity": debt_equity,
        "sales_qoq": num("revenueGrowth") * 100,
        "eps_qoq": num("earningsQuarterlyGrowth") * 100,
        "earnings_date": earnings_date,
    }
