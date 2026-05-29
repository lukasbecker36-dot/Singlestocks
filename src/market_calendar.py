"""Lightweight NYSE/NASDAQ trading-calendar helpers (no external dependency).

Covers weekends plus the standard U.S. equity-market holidays, including the
observed-day shift (Saturday -> preceding Friday, Sunday -> following Monday) and
Good Friday. Half-days (e.g. day after Thanksgiving) are treated as trading days.
This is sufficient for a "should we run today?" guard; it is not a minute-accurate
session calendar.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(d: date) -> date:
    if d.weekday() == 5:  # Saturday -> Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday -> Monday
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``-th ``weekday`` (Mon=0) of ``month`` (1-indexed n)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last = nxt - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


@lru_cache(maxsize=None)
def market_holidays(year: int) -> frozenset[date]:
    """Observed U.S. equity-market holidays for ``year``."""
    holidays = {
        _observed(date(year, 1, 1)),          # New Year's Day
        _nth_weekday(year, 1, 0, 3),          # MLK Jr. Day (3rd Mon Jan)
        _nth_weekday(year, 2, 0, 3),          # Washington's Birthday (3rd Mon Feb)
        _easter(year) - timedelta(days=2),    # Good Friday
        _last_weekday(year, 5, 0),            # Memorial Day (last Mon May)
        _observed(date(year, 7, 4)),          # Independence Day
        _nth_weekday(year, 9, 0, 1),          # Labor Day (1st Mon Sep)
        _nth_weekday(year, 11, 3, 4),         # Thanksgiving (4th Thu Nov)
        _observed(date(year, 12, 25)),        # Christmas
    }
    if year >= 2022:
        holidays.add(_observed(date(year, 6, 19)))  # Juneteenth
    return frozenset(holidays)


def is_trading_day(d: date) -> bool:
    """True when ``d`` is a weekday and not an observed market holiday."""
    if d.weekday() >= 5:
        return False
    return d not in market_holidays(d.year)


def trading_days_offset(target: date, ref: date | None = None) -> int:
    """Signed count of trading days from ``ref`` (default today) to ``target``.

    Positive when ``target`` is in the future, negative when in the past, 0 when equal.
    Only trading days are counted.
    """
    ref = ref or date.today()
    if target == ref:
        return 0
    step = 1 if target > ref else -1
    count = 0
    cursor = ref
    while cursor != target:
        cursor += timedelta(days=step)
        if is_trading_day(cursor):
            count += 1
    return count * step
