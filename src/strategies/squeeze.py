"""Squeeze: low-float, heavily shorted stocks showing early signs of a short squeeze."""
from __future__ import annotations

import pandas as pd

import config
from strategies.base import Condition, combine, finalize, funnel_log, optional

NAME = "Squeeze"


def _conditions(df: pd.DataFrame, mode: str) -> list[Condition]:
    tight = mode == "tight"
    avg_vol = config.SQUEEZE_AVG_VOL_TIGHT if tight else config.SQUEEZE_AVG_VOL_LOOSE
    perf1w = config.SQUEEZE_PERF_1W_TIGHT if tight else config.SQUEEZE_PERF_1W_LOOSE
    flt = config.SQUEEZE_FLOAT_TIGHT if tight else config.SQUEEZE_FLOAT_LOOSE
    short = config.SQUEEZE_SHORT_TIGHT if tight else config.SQUEEZE_SHORT_LOOSE

    conds: list[Condition] = [
        (f"avg_vol>{avg_vol:.0f}", df["avg_volume"] > avg_vol),
        (f"rel_vol>{config.SQUEEZE_REL_VOL}", df["rel_volume"] > config.SQUEEZE_REL_VOL),
        ("price>sma20", df["price"] > df["sma20"]),
    ]
    if tight:
        conds.append(("price>sma50(opt)", optional(df["price"] > df["sma50"], df["sma50"])))
    conds.extend(
        [
            (f"perf_1w>{perf1w}", df["perf_1w"] > perf1w),
            (f"float<{flt / 1e6:.0f}M", df["float_shares"] < flt),
            (f"short%>{short}", df["short_pct_float"] > short),
        ]
    )
    if tight:
        conds.append(
            ("weekVol>=5(opt)", optional(df["week_volatility"] >= config.SQUEEZE_VOLATILITY_TIGHT, df["week_volatility"]))
        )
    return conds


def run(universe: pd.DataFrame, mode: str = "tight") -> pd.DataFrame:
    df = universe
    tight_mask = combine(_conditions(df, "tight"))
    loose_mask = combine(_conditions(df, "loose"))
    funnel_log(NAME, mode, df, _conditions(df, mode))
    return finalize(df, NAME, tight_mask, loose_mask, _signal, mode)


def _signal(row: pd.Series) -> str:
    text = (
        f"Short {row['short_pct_float']:.0f}% of float, "
        f"{row['float_shares'] / 1e6:.0f}M float, 1W {row['perf_1w']:+.1f}%"
    )
    dtc = row.get("days_to_cover")
    if dtc is not None and pd.notna(dtc):
        text += f", {dtc:.1f}d to cover"
    return text
