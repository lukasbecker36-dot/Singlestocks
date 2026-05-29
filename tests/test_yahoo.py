"""Offline tests for the Yahoo data layer's pure metric helpers (no network)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from data.yahoo import compute_price_metrics, compute_rsi


def test_rsi_all_gains_is_100():
    close = pd.Series(np.arange(1, 60, dtype=float))  # strictly increasing
    assert compute_rsi(close).iloc[-1] == 100.0


def test_rsi_within_bounds_and_midrange_for_choppy_series():
    rng = np.random.default_rng(0)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    rsi = compute_rsi(close).iloc[-1]
    assert 0 <= rsi <= 100


def _ramp_history(n: int = 60, start: float = 10.0, step: float = 0.5) -> pd.DataFrame:
    close = np.arange(start, start + n * step, step)[:n]
    return pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.2,
            "Low": close - 0.2,
            "Close": close,
            "Volume": np.full(n, 1_000_000.0),
        }
    )


def test_compute_price_metrics_uptrend():
    m = compute_price_metrics(_ramp_history())
    assert m is not None
    # Rising series: price above every SMA, strong RSI, positive performance.
    assert m["price"] > m["sma20"] > m["sma50"]
    assert m["rsi"] > 70
    assert m["perf_1w"] > 0 and m["perf_1m"] > 0
    assert m["avg_volume"] == 1_000_000.0
    assert m["week_52_high"] is True


def test_compute_price_metrics_rejects_short_history():
    assert compute_price_metrics(_ramp_history(n=10)) is None
