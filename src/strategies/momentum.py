"""Momentum: small-caps in confirmed uptrends with accelerating interest."""
from __future__ import annotations

import pandas as pd

import config
from strategies.base import Condition, between, combine, finalize, funnel_log, optional

NAME = "Momentum"


def _conditions(df: pd.DataFrame, mode: str) -> list[Condition]:
    tight = mode == "tight"
    rel = config.MOMENTUM_REL_VOL_TIGHT if tight else config.MOMENTUM_REL_VOL_LOOSE
    perf1m = config.MOMENTUM_PERF_1M_TIGHT if tight else config.MOMENTUM_PERF_1M_LOOSE
    de = config.MOMENTUM_DEBT_EQUITY_TIGHT if tight else config.MOMENTUM_DEBT_EQUITY_LOOSE

    conds: list[Condition] = [
        (f"rel_vol>{rel}", df["rel_volume"] > rel),
        ("price>sma50", df["price"] > df["sma50"]),
        ("price>sma200", df["price"] > df["sma200"]),
        ("rsi50-70", between(df["rsi"], config.MOMENTUM_RSI_MIN, config.MOMENTUM_RSI_MAX)),
        ("perf_1w>0", df["perf_1w"] > 0),
        (f"perf_1m>={perf1m}", df["perf_1m"] >= perf1m),
        (f"debt/eq<{de}", df["debt_equity"] < de),
    ]
    if tight:
        conds.append(("52w_high(opt)", optional(df["week_52_high"] == True, df["week_52_high"])))  # noqa: E712
        conds.append(
            ("salesQoQ(opt)", optional(df["sales_qoq"] > config.MOMENTUM_SALES_QOQ_TIGHT, df["sales_qoq"]))
        )
    return conds


def run(universe: pd.DataFrame, mode: str = "tight") -> pd.DataFrame:
    df = universe
    tight_mask = combine(_conditions(df, "tight"))
    loose_mask = combine(_conditions(df, "loose"))
    funnel_log(NAME, mode, df, _conditions(df, mode))
    return finalize(df, NAME, tight_mask, loose_mask, _signal, mode)


def _signal(r: pd.Series) -> str:
    return f"1M {r['perf_1m']:+.1f}%, RSI {r['rsi']:.0f}, RVol {r['rel_volume']:.1f}"
