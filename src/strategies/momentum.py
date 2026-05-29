"""Momentum: small-caps in confirmed uptrends with accelerating interest."""
from __future__ import annotations

import pandas as pd

import config
from strategies.base import between, finalize, optional

NAME = "Momentum"


def run(universe: pd.DataFrame, mode: str = "tight") -> pd.DataFrame:
    df = universe
    above_trend = (df["price"] > df["sma50"]) & (df["price"] > df["sma200"])
    rsi_band = between(df["rsi"], config.MOMENTUM_RSI_MIN, config.MOMENTUM_RSI_MAX)
    positive_week = df["perf_1w"] > 0

    tight = (
        (df["rel_volume"] > config.MOMENTUM_REL_VOL_TIGHT)
        & above_trend
        & rsi_band
        & positive_week
        & (df["perf_1m"] >= config.MOMENTUM_PERF_1M_TIGHT)
        & (df["debt_equity"] < config.MOMENTUM_DEBT_EQUITY_TIGHT)
        & optional(df["week_52_high"] == True, df["week_52_high"])  # noqa: E712
        & optional(df["sales_qoq"] > config.MOMENTUM_SALES_QOQ_TIGHT, df["sales_qoq"])
    )
    loose = (
        (df["rel_volume"] > config.MOMENTUM_REL_VOL_LOOSE)
        & above_trend
        & rsi_band
        & positive_week
        & (df["perf_1m"] >= config.MOMENTUM_PERF_1M_LOOSE)
        & (df["debt_equity"] < config.MOMENTUM_DEBT_EQUITY_LOOSE)
    )

    return finalize(df, NAME, tight, loose, _signal, mode)


def _signal(r: pd.Series) -> str:
    return f"1M {r['perf_1m']:+.1f}%, RSI {r['rsi']:.0f}, RVol {r['rel_volume']:.1f}"
