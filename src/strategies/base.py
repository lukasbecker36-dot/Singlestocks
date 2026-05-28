"""Shared helpers and the common contract for strategy modules.

Each strategy is a **pure function** ``run(universe, mode) -> DataFrame`` that takes the
base-universe DataFrame and returns only the rows it matches, with three extra columns:

* ``strategy`` -- the strategy's display name
* ``match``    -- ``"tight"`` or ``"loose"`` (whether the row also clears tight criteria)
* ``signal``   -- a short human-readable, strategy-specific signal string

A row is included when it passes the *active* mode's mask. It is tagged ``"tight"`` when it
also passes the tight mask, otherwise ``"loose"`` -- so a tight-mode run only ever yields
``"tight"`` tags, while a loose-mode run distinguishes the stronger hits.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def between(series: pd.Series, low: float, high: float) -> pd.Series:
    """Inclusive band test. NaN values are excluded (NaN comparisons yield False)."""
    return (series >= low) & (series <= high)


def optional(condition: pd.Series, source: pd.Series) -> pd.Series:
    """An *optional* filter: rows missing the underlying data pass through.

    Used for fields that the spec marks "(optional)" or that data providers may not
    supply. When ``source`` is NaN the row is not excluded by this condition.
    """
    return condition | source.isna()


def finalize(
    universe: pd.DataFrame,
    name: str,
    tight_mask: pd.Series,
    loose_mask: pd.Series,
    signal: pd.Series,
    mode: str,
) -> pd.DataFrame:
    """Select rows for ``mode`` and attach ``strategy`` / ``match`` / ``signal`` columns."""
    mask = tight_mask if mode == "tight" else loose_mask
    out = universe.loc[mask].copy()
    out["strategy"] = name
    out["match"] = np.where(tight_mask.loc[out.index].to_numpy(), "tight", "loose")
    out["signal"] = signal.loc[out.index].to_numpy()
    return out.reset_index(drop=True)
