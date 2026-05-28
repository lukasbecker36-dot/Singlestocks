"""Earnings (pre-earnings play): bullish setups reporting within the next 5 trading days."""
from __future__ import annotations

import pandas as pd

import config
from strategies.base import between, finalize, optional

NAME = "Earnings"


def run(universe: pd.DataFrame, mode: str = "tight") -> pd.DataFrame:
    df = universe
    above_trend = (df["price"] > df["sma50"]) & (df["price"] > df["sma200"])
    rsi_band = between(df["rsi"], config.EARNINGS_RSI_MIN, config.EARNINGS_RSI_MAX)
    upcoming = between(
        df["earnings_trading_days"], config.EARNINGS_DAYS_MIN, config.EARNINGS_DAYS_MAX
    )

    tight = (
        (df["rel_volume"] > config.EARNINGS_REL_VOL_TIGHT)
        & above_trend
        & rsi_band
        & (df["perf_1m"] >= config.EARNINGS_PERF_1M_TIGHT)
        & upcoming
        & optional(df["eps_qoq"] > config.EARNINGS_EPS_QOQ_TIGHT, df["eps_qoq"])
        & optional(df["sales_qoq"] > config.EARNINGS_SALES_QOQ_TIGHT, df["sales_qoq"])
    )
    loose = (
        (df["rel_volume"] > config.EARNINGS_REL_VOL_LOOSE)
        & above_trend
        & rsi_band
        & (df["perf_1m"] > config.EARNINGS_PERF_1M_LOOSE)
        & upcoming
    )

    signal = df.apply(
        lambda r: f"Reports in {int(r['earnings_trading_days'])} td, RSI {r['rsi']:.0f}",
        axis=1,
    )
    return finalize(df, NAME, tight, loose, signal, mode)
