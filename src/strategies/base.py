"""Shared helpers and the common contract for strategy modules.

Each strategy is a **pure function** ``run(universe, mode) -> DataFrame`` that takes the
base-universe DataFrame and returns only the rows it matches, with three extra columns:

* ``strategy`` -- the strategy's display name
* ``match``    -- ``"tight"`` or ``"loose"`` (whether the row also clears tight criteria)
* ``signal``   -- a short human-readable, strategy-specific signal string

A row is included when it passes the *active* mode's mask. It is tagged ``"tight"`` when it
also passes the tight mask, otherwise ``"loose"`` -- so a tight-mode run only ever yields
``"tight"`` tags, while a loose-mode run distinguishes the stronger hits.

The ``signal`` text is built only for the rows that matched (via a per-row function), so a
strategy never has to format fields that are NaN on non-matching rows.
"""
from __future__ import annotations

import logging
from typing import Callable

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# A named filter condition: (human label, boolean mask aligned to the universe).
Condition = tuple[str, pd.Series]


def between(series: pd.Series, low: float, high: float) -> pd.Series:
    """Inclusive band test. NaN values are excluded (NaN comparisons yield False)."""
    return (series >= low) & (series <= high)


def optional(condition: pd.Series, source: pd.Series) -> pd.Series:
    """An *optional* filter: rows missing the underlying data pass through.

    Used for fields that the spec marks "(optional)" or that data providers may not
    supply. When ``source`` is NaN the row is not excluded by this condition.
    """
    return condition | source.isna()


def combine(conditions: list[Condition]) -> pd.Series:
    """AND a list of named conditions into a single mask."""
    mask: pd.Series | None = None
    for _, m in conditions:
        mask = m if mask is None else (mask & m)
    return mask


def funnel_log(name: str, mode: str, universe: pd.DataFrame, conditions: list[Condition]) -> None:
    """Log how many rows pass each filter standalone and cumulatively (a drop funnel).

    Diagnostic only — does not affect screening. Reveals which filter is the bottleneck.
    """
    if not log.isEnabledFor(logging.INFO):
        return
    cum = pd.Series(True, index=universe.index)
    parts = []
    for label, m in conditions:
        cum = cum & m
        parts.append(f"{label}: {int(m.sum())} (cum {int(cum.sum())})")
    log.info("Funnel %s[%s] n=%d → %s", name, mode, len(universe), " | ".join(parts))


def finalize(
    universe: pd.DataFrame,
    name: str,
    tight_mask: pd.Series,
    loose_mask: pd.Series,
    signal_fn: Callable[[pd.Series], str],
    mode: str,
) -> pd.DataFrame:
    """Select rows for ``mode`` and attach ``strategy`` / ``match`` / ``signal`` columns.

    ``signal_fn`` is applied only to the selected rows, so it can safely assume the
    filters' guarantees (e.g. a non-NaN earnings date for an earnings hit).
    """
    mask = tight_mask if mode == "tight" else loose_mask
    out = universe.loc[mask].copy()
    out["strategy"] = name
    out["match"] = np.where(tight_mask.loc[out.index].to_numpy(), "tight", "loose")
    out["signal"] = [signal_fn(row) for _, row in out.iterrows()]
    return out.reset_index(drop=True)
