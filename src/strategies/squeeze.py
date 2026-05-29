"""Squeeze: low-float, heavily shorted stocks showing early signs of a short squeeze."""
from __future__ import annotations

import pandas as pd

import config
from strategies.base import finalize, optional

NAME = "Squeeze"


def run(universe: pd.DataFrame, mode: str = "tight") -> pd.DataFrame:
    df = universe
    rel_vol = df["rel_volume"] > config.SQUEEZE_REL_VOL
    above_20 = df["price"] > df["sma20"]

    tight = (
        (df["avg_volume"] > config.SQUEEZE_AVG_VOL_TIGHT)
        & rel_vol
        & above_20
        & optional(df["price"] > df["sma50"], df["sma50"])
        & (df["perf_1w"] > config.SQUEEZE_PERF_1W_TIGHT)
        & (df["float_shares"] < config.SQUEEZE_FLOAT_TIGHT)
        & (df["short_pct_float"] > config.SQUEEZE_SHORT_TIGHT)
        & optional(
            df["week_volatility"] >= config.SQUEEZE_VOLATILITY_TIGHT, df["week_volatility"]
        )
    )
    loose = (
        (df["avg_volume"] > config.SQUEEZE_AVG_VOL_LOOSE)
        & rel_vol
        & above_20
        & (df["perf_1w"] > config.SQUEEZE_PERF_1W_LOOSE)
        & (df["float_shares"] < config.SQUEEZE_FLOAT_LOOSE)
        & (df["short_pct_float"] > config.SQUEEZE_SHORT_LOOSE)
    )

    signal = df.apply(_signal, axis=1)
    return finalize(df, NAME, tight, loose, signal, mode)


def _signal(row: pd.Series) -> str:
    text = (
        f"Short {row['short_pct_float']:.0f}% of float, "
        f"{row['float_shares'] / 1e6:.0f}M float, 1W {row['perf_1w']:+.1f}%"
    )
    dtc = row.get("days_to_cover")
    if dtc is not None and pd.notna(dtc):
        text += f", {dtc:.1f}d to cover"
    return text
