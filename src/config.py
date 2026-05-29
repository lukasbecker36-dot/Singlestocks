"""Central configuration.

All values come from the environment (loaded from a local ``.env`` when present).
Every strategy threshold lives here as a named constant with a ``_TIGHT`` / ``_LOOSE``
suffix so that strategy code never contains magic numbers.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


# --------------------------------------------------------------------------- #
# Runtime
# --------------------------------------------------------------------------- #
SCAN_MODE: str = os.getenv("SCAN_MODE", "tight").lower()
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

# --------------------------------------------------------------------------- #
# Data source (Yahoo Finance via yfinance — free, no API key)
# --------------------------------------------------------------------------- #
NASDAQ_LIST_URL: str = os.getenv(
    "NASDAQ_LIST_URL", "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
)
HISTORY_PERIOD: str = os.getenv("HISTORY_PERIOD", "1y")  # enough for SMA200 / 52-week high
YF_BATCH_SIZE: int = _int("YF_BATCH_SIZE", 200)  # symbols per bulk history download
# Caps that bound per-ticker network lookups so a daily run stays fast/reliable:
MAX_PREFILTER: int = _int("MAX_PREFILTER", 800)  # symbols kept before market-cap lookup
MAX_ENRICH: int = _int("MAX_ENRICH", 250)  # small-caps kept for fundamentals enrichment

# --------------------------------------------------------------------------- #
# Email (SMTP)
# --------------------------------------------------------------------------- #
SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = _int("SMTP_PORT", 587)
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASS: str = os.getenv("SMTP_PASS", "")
EMAIL_TO: str = os.getenv("EMAIL_TO", "")
EMAIL_FROM: str = os.getenv("EMAIL_FROM", "")

# --------------------------------------------------------------------------- #
# Base universe filter  (shared by every strategy)
# --------------------------------------------------------------------------- #
EXCHANGE: str = "NASDAQ"
BASE_MARKET_CAP_MAX_TIGHT: int = 2_000_000_000
BASE_MARKET_CAP_MAX_LOOSE: int = 300_000_000  # micro-cap
BASE_PRICE_MIN_TIGHT: float = 5.0
BASE_PRICE_MIN_LOOSE: float = 2.0
BASE_AVG_VOLUME_MIN_TIGHT: int = 1_000_000
BASE_AVG_VOLUME_MIN_LOOSE: int = 500_000

# --------------------------------------------------------------------------- #
# 1. Momentum
# --------------------------------------------------------------------------- #
MOMENTUM_REL_VOL_TIGHT: float = 1.5
MOMENTUM_REL_VOL_LOOSE: float = 1.0
MOMENTUM_RSI_MIN: float = 50.0
MOMENTUM_RSI_MAX: float = 70.0
MOMENTUM_PERF_1M_TIGHT: float = 10.0
MOMENTUM_PERF_1M_LOOSE: float = 5.0
MOMENTUM_SALES_QOQ_TIGHT: float = 10.0  # optional, tight only
MOMENTUM_DEBT_EQUITY_TIGHT: float = 0.5
MOMENTUM_DEBT_EQUITY_LOOSE: float = 1.0

# --------------------------------------------------------------------------- #
# 2. Earnings (pre-earnings play)
# --------------------------------------------------------------------------- #
EARNINGS_REL_VOL_TIGHT: float = 1.2
EARNINGS_REL_VOL_LOOSE: float = 1.0
EARNINGS_RSI_MIN: float = 50.0
EARNINGS_RSI_MAX: float = 70.0
EARNINGS_PERF_1M_TIGHT: float = 5.0
EARNINGS_PERF_1M_LOOSE: float = 0.0
EARNINGS_DAYS_MIN: int = 0  # trading days until earnings
EARNINGS_DAYS_MAX: int = 5
EARNINGS_EPS_QOQ_TIGHT: float = 0.0  # optional
EARNINGS_SALES_QOQ_TIGHT: float = 0.0  # optional

# --------------------------------------------------------------------------- #
# 3. Post-earnings drift
# --------------------------------------------------------------------------- #
PEAD_REL_VOL: float = 1.5
PEAD_RSI_MIN: float = 50.0
PEAD_PERF_1W: float = 5.0
PEAD_GAP: float = 5.0
PEAD_DAYS_TIGHT: int = 5  # earnings within previous N trading days
PEAD_DAYS_LOOSE: int = 10

# --------------------------------------------------------------------------- #
# 4. Squeeze (short squeeze)
# --------------------------------------------------------------------------- #
SQUEEZE_AVG_VOL_TIGHT: int = 500_000
SQUEEZE_AVG_VOL_LOOSE: int = 300_000
SQUEEZE_REL_VOL: float = 1.5
SQUEEZE_PERF_1W_TIGHT: float = 10.0
SQUEEZE_PERF_1W_LOOSE: float = 0.0
SQUEEZE_FLOAT_TIGHT: int = 50_000_000
SQUEEZE_FLOAT_LOOSE: int = 100_000_000
SQUEEZE_SHORT_TIGHT: float = 15.0
SQUEEZE_SHORT_LOOSE: float = 10.0
SQUEEZE_VOLATILITY_TIGHT: float = 5.0  # optional


def validate_mode(mode: str) -> str:
    """Return a normalised, validated scan mode."""
    mode = (mode or "tight").lower()
    if mode not in ("tight", "loose"):
        raise ValueError(f"SCAN_MODE must be 'tight' or 'loose', got {mode!r}")
    return mode
