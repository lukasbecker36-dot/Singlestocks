"""Post-earnings drift: stocks that recently reported and are drifting higher (PEAD)."""
from __future__ import annotations

import pandas as pd

import config
from strategies.base import between, finalize, optional

NAME = "Post-Earnings Drift"


def run(universe: pd.DataFrame, mode: str = "tight") -> pd.DataFrame:
    df = universe
    above_short = (df["price"] > df["sma20"]) & (df["price"] > df["sma50"])
    rel_vol = df["rel_volume"] > config.PEAD_REL_VOL
    rsi_ok = df["rsi"] > config.PEAD_RSI_MIN
    drift = df["perf_1w"] >= config.PEAD_PERF_1W
    gap = df["gap_pct"] >= config.PEAD_GAP

    # earnings within the previous N trading days -> negative offset
    recent_tight = between(df["earnings_trading_days"], -config.PEAD_DAYS_TIGHT, -1)
    recent_loose = between(df["earnings_trading_days"], -config.PEAD_DAYS_LOOSE, -1)

    tight = (
        rel_vol
        & above_short
        & optional(df["price"] > df["sma200"], df["sma200"])
        & rsi_ok
        & drift
        & recent_tight
        & gap
    )
    loose = rel_vol & above_short & rsi_ok & drift & recent_loose & gap

    return finalize(df, NAME, tight, loose, _signal, mode)


def _signal(r: pd.Series) -> str:
    return (
        f"Gap {r['gap_pct']:+.1f}%, 1W {r['perf_1w']:+.1f}%, "
        f"{abs(int(r['earnings_trading_days']))} td post-ER"
    )
