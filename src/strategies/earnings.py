"""Earnings (pre-earnings play): bullish setups reporting within the next 5 trading days."""
from __future__ import annotations

import pandas as pd

import config
from strategies.base import Condition, between, combine, finalize, funnel_log, optional

NAME = "Earnings"


def _conditions(df: pd.DataFrame, mode: str) -> list[Condition]:
    tight = mode == "tight"
    rel = config.EARNINGS_REL_VOL_TIGHT if tight else config.EARNINGS_REL_VOL_LOOSE
    upcoming = between(
        df["earnings_trading_days"], config.EARNINGS_DAYS_MIN, config.EARNINGS_DAYS_MAX
    )

    conds: list[Condition] = [
        (f"rel_vol>{rel}", df["rel_volume"] > rel),
        ("price>sma50", df["price"] > df["sma50"]),
        ("price>sma200", df["price"] > df["sma200"]),
        ("rsi50-70", between(df["rsi"], config.EARNINGS_RSI_MIN, config.EARNINGS_RSI_MAX)),
    ]
    if tight:
        conds.append((f"perf_1m>={config.EARNINGS_PERF_1M_TIGHT}", df["perf_1m"] >= config.EARNINGS_PERF_1M_TIGHT))
    else:
        conds.append((f"perf_1m>{config.EARNINGS_PERF_1M_LOOSE}", df["perf_1m"] > config.EARNINGS_PERF_1M_LOOSE))
    conds.append(("earnings_in_0-5td", upcoming))
    if tight:
        conds.append(("epsQoQ(opt)", optional(df["eps_qoq"] > config.EARNINGS_EPS_QOQ_TIGHT, df["eps_qoq"])))
        conds.append(("salesQoQ(opt)", optional(df["sales_qoq"] > config.EARNINGS_SALES_QOQ_TIGHT, df["sales_qoq"])))
    return conds


def run(universe: pd.DataFrame, mode: str = "tight") -> pd.DataFrame:
    df = universe
    tight_mask = combine(_conditions(df, "tight"))
    loose_mask = combine(_conditions(df, "loose"))
    funnel_log(NAME, mode, df, _conditions(df, mode))
    return finalize(df, NAME, tight_mask, loose_mask, _signal, mode)


def _signal(r: pd.Series) -> str:
    return f"Reports in {int(r['earnings_trading_days'])} td, RSI {r['rsi']:.0f}"
