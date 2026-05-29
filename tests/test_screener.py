"""Orchestrator, emailer, and calendar tests (offline)."""
from __future__ import annotations

import math
from datetime import date

import numpy as np

import emailer
import screener
from data.universe import compute_short_metrics
from market_calendar import is_trading_day, trading_days_offset


def test_run_screener_partitions_by_strategy(universe):
    results = screener.run_screener(universe, "tight")
    assert set(results) == {"Momentum", "Earnings", "Post-Earnings Drift", "Squeeze"}
    assert set(results["Momentum"]["symbol"]) == {"MOMO"}
    assert set(results["Earnings"]["symbol"]) == {"EARN"}
    assert set(results["Post-Earnings Drift"]["symbol"]) == {"PEAD"}
    assert set(results["Squeeze"]["symbol"]) == {"SQZ"}


def test_signals_tolerate_nan_on_non_matching_rows(universe):
    # Regression: signals must be built only for matched rows. Previously a NaN
    # earnings_trading_days on a non-matching row crashed int() in the Earnings signal.
    u = universe.copy()
    u.loc[u["symbol"] != "EARN", "earnings_trading_days"] = np.nan
    results = screener.run_screener(u, "tight")  # must not raise
    assert set(results["Earnings"]["symbol"]) == {"EARN"}


def test_unique_hits_counts_distinct_tickers(universe):
    results = screener.run_screener(universe, "tight")
    assert screener.unique_hits(results) == 4


def test_results_ranked_by_relative_volume(universe):
    # Loose squeeze yields two rows; both have rel_volume 2.0 so ordering is stable,
    # but the column must be present and sorted descending.
    hits = screener.run_screener(universe, "loose")["Squeeze"]
    rel = hits["rel_volume"].tolist()
    assert rel == sorted(rel, reverse=True)


def test_format_email_includes_both_modes(universe):
    results_by_mode = {
        "tight": screener.run_screener(universe, "tight"),
        "loose": screener.run_screener(universe, "loose"),
    }
    subject, html = emailer.format_email(results_by_mode, date(2026, 5, 28))
    # Unique tickers across both modes: MOMO, MOLO, EARN, PEAD, SQZ, SQLO.
    assert "6 hits" in subject
    assert "2026-05-28" in subject
    assert "TIGHT scan" in html and "LOOSE scan" in html
    # Tight block appears before loose block.
    assert html.index("TIGHT scan") < html.index("LOOSE scan")
    assert "Momentum" in html and "Squeeze" in html
    assert "not financial advice" in html


def test_format_email_reports_empty_sections(universe):
    only_dud = universe[universe["symbol"] == "DUD"]
    results_by_mode = {"tight": screener.run_screener(only_dud, "tight")}
    subject, html = emailer.format_email(results_by_mode, date(2026, 5, 28))
    assert "0 hits" in subject
    assert "No matches today." in html


def test_calendar_weekend_and_holiday():
    assert not is_trading_day(date(2026, 5, 30))  # Saturday
    assert not is_trading_day(date(2025, 12, 25))  # Christmas
    assert not is_trading_day(date(2025, 7, 4))    # Independence Day
    assert is_trading_day(date(2026, 5, 28))       # ordinary Thursday


def test_short_metrics_prefers_float():
    pct, dtc = compute_short_metrics(
        short_shares=10_000_000, float_shares=50_000_000, avg_volume=2_000_000,
        short_pct_outstanding=0.05, short_ratio=2.0,
    )
    assert pct == 20.0          # 10M / 50M = 20% of float (not the 5% of outstanding)
    assert dtc == 2.0           # provider-supplied short ratio preferred


def test_short_metrics_falls_back_to_outstanding_and_computed_ratio():
    pct, dtc = compute_short_metrics(
        short_shares=10_000_000, float_shares=np.nan, avg_volume=2_000_000,
        short_pct_outstanding=0.05, short_ratio=np.nan,
    )
    assert pct == 5.0           # falls back to % of shares outstanding
    assert dtc == 5.0           # 10M / 2M avg volume


def test_short_metrics_all_missing_is_nan():
    pct, dtc = compute_short_metrics(np.nan, np.nan, np.nan)
    assert math.isnan(pct) and math.isnan(dtc)


def test_trading_days_offset_signs():
    # Thu 2026-05-28 -> next trading day Fri 2026-05-29 is +1
    assert trading_days_offset(date(2026, 5, 29), date(2026, 5, 28)) == 1
    # previous trading day Wed 2026-05-27 is -1
    assert trading_days_offset(date(2026, 5, 27), date(2026, 5, 28)) == -1
    assert trading_days_offset(date(2026, 5, 28), date(2026, 5, 28)) == 0
