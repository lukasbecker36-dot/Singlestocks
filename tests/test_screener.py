"""Orchestrator, emailer, and calendar tests (offline)."""
from __future__ import annotations

from datetime import date

import emailer
import screener
from market_calendar import is_trading_day, trading_days_offset


def test_run_screener_partitions_by_strategy(universe):
    results = screener.run_screener(universe, "tight")
    assert set(results) == {"Momentum", "Earnings", "Post-Earnings Drift", "Squeeze"}
    assert set(results["Momentum"]["symbol"]) == {"MOMO"}
    assert set(results["Earnings"]["symbol"]) == {"EARN"}
    assert set(results["Post-Earnings Drift"]["symbol"]) == {"PEAD"}
    assert set(results["Squeeze"]["symbol"]) == {"SQZ"}


def test_unique_hits_counts_distinct_tickers(universe):
    results = screener.run_screener(universe, "tight")
    assert screener.unique_hits(results) == 4


def test_results_ranked_by_relative_volume(universe):
    # Loose squeeze yields two rows; both have rel_volume 2.0 so ordering is stable,
    # but the column must be present and sorted descending.
    hits = screener.run_screener(universe, "loose")["Squeeze"]
    rel = hits["rel_volume"].tolist()
    assert rel == sorted(rel, reverse=True)


def test_format_email_subject_and_sections(universe):
    results = screener.run_screener(universe, "tight")
    subject, html = emailer.format_email(results, date(2026, 5, 28), "tight")
    assert "4 hits" in subject
    assert "2026-05-28" in subject
    assert "Momentum" in html and "Squeeze" in html
    assert "not financial advice" in html


def test_format_email_reports_empty_sections(universe):
    only_dud = universe[universe["symbol"] == "DUD"]
    results = screener.run_screener(only_dud, "tight")
    subject, html = emailer.format_email(results, date(2026, 5, 28), "tight")
    assert "0 hits" in subject
    assert "No matches today." in html


def test_calendar_weekend_and_holiday():
    assert not is_trading_day(date(2026, 5, 30))  # Saturday
    assert not is_trading_day(date(2025, 12, 25))  # Christmas
    assert not is_trading_day(date(2025, 7, 4))    # Independence Day
    assert is_trading_day(date(2026, 5, 28))       # ordinary Thursday


def test_trading_days_offset_signs():
    # Thu 2026-05-28 -> next trading day Fri 2026-05-29 is +1
    assert trading_days_offset(date(2026, 5, 29), date(2026, 5, 28)) == 1
    # previous trading day Wed 2026-05-27 is -1
    assert trading_days_offset(date(2026, 5, 27), date(2026, 5, 28)) == -1
    assert trading_days_offset(date(2026, 5, 28), date(2026, 5, 28)) == 0
