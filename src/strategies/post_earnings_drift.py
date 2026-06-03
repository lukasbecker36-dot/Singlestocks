"""Post-earnings drift: stocks that recently reported and are drifting higher (PEAD)."""
from __future__ import annotations

import pandas as pd

import config
from strategies.base import Condition, between, combine, finalize, funnel_log, optional

NAME = "Post-Earnings Drift"


def _conditions(df: pd.DataFrame, mode: str) -> list[Condition]:
    tight = mode == "tight"
    days = config.PEAD_DAYS_TIGHT if tight else config.PEAD_DAYS_LOOSE

    conds: list[Condition] = [
        (f"rel_vol>{config.PEAD_REL_VOL}", df["rel_volume"] > config.PEAD_REL_VOL),
        ("price>sma20", df["price"] > df["sma20"]),
        ("price>sma50", df["price"] > df["sma50"]),
    ]
    if tight:
        conds.append(("price>sma200(opt)", optional(df["price"] > df["sma200"], df["sma200"])))
    conds.extend(
        [
            (f"rsi>{config.PEAD_RSI_MIN}", df["rsi"] > config.PEAD_RSI_MIN),
            (f"perf_1w>={config.PEAD_PERF_1W}", df["perf_1w"] >= config.PEAD_PERF_1W),
            (f"earnings_in_-{days}..-1td", between(df["earnings_trading_days"], -days, -1)),
            (f"gap>={config.PEAD_GAP}", df["gap_pct"] >= config.PEAD_GAP),
        ]
    )
    return conds


def run(universe: pd.DataFrame, mode: str = "tight") -> pd.DataFrame:
    df = universe
    tight_mask = combine(_conditions(df, "tight"))
    loose_mask = combine(_conditions(df, "loose"))
    funnel_log(NAME, mode, df, _conditions(df, mode))
    return finalize(df, NAME, tight_mask, loose_mask, _signal, mode)


def _signal(r: pd.Series) -> str:
    return (
        f"Gap {r['gap_pct']:+.1f}%, 1W {r['perf_1w']:+.1f}%, "
        f"{abs(int(r['earnings_trading_days']))} td post-ER"
    )
