"""Orchestrator: run every strategy over the base universe, rank, and report."""
from __future__ import annotations

import logging

import pandas as pd

import config
from strategies import earnings, momentum, post_earnings_drift, squeeze

log = logging.getLogger(__name__)

# Order here is the order strategies appear in the email.
STRATEGIES = [momentum, earnings, post_earnings_drift, squeeze]


def _rank(df: pd.DataFrame) -> pd.DataFrame:
    """Rank hits within a strategy by conviction (relative volume, descending)."""
    if df.empty:
        return df
    return df.sort_values("rel_volume", ascending=False).reset_index(drop=True)


def run_screener(universe: pd.DataFrame, mode: str | None = None) -> dict[str, pd.DataFrame]:
    """Run all strategies and return ``{strategy_name: ranked_hits_df}``.

    A ticker may legitimately appear under more than one strategy; results are kept
    per-strategy (not collapsed) so each section of the email is self-contained.
    """
    mode = config.validate_mode(mode or config.SCAN_MODE)
    results: dict[str, pd.DataFrame] = {}
    for strat in STRATEGIES:
        hits = _rank(strat.run(universe, mode))
        log.info("%s: %d hit(s) [mode=%s]", strat.NAME, len(hits), mode)
        results[strat.NAME] = hits
    return results


def unique_hits(results: dict[str, pd.DataFrame]) -> int:
    """Count of distinct tickers across all strategies."""
    symbols: set[str] = set()
    for df in results.values():
        if not df.empty:
            symbols.update(df["symbol"].tolist())
    return len(symbols)
