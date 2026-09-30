#!/usr/bin/env python3
"""Rank every ETF on InvestEngine by 1-week and 1-month price return.

Steps:
  1. Scrape the InvestEngine ETF list  -> universe.csv
  2. Batch-download ~45 days of daily closes from Yahoo (TICKER.L)
  3. Compute 1W / 1M price returns
  4. Flag data-quality issues in a notes column (never silently drop)
  5. Write results.csv, print top-20 tables and the failure list

Usage:
  python etf_screen.py                      # full run (fetches universe + prices)
  python etf_screen.py --html saved.html    # parse a manually saved copy of the page
  python etf_screen.py --universe universe.csv   # skip scraping, reuse a universe file
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

UNIVERSE_URL = "https://investengine.com/etfs/all/"
EXPECTED_UNIVERSE = 870
MIN_UNIVERSE = 700          # below this, stop and ask before continuing
YAHOO_SUFFIX = ".L"
HISTORY_DAYS = 45
BATCH_SIZE = 100

WEEK_LOOKBACK = 5           # trading days
STALE_TRADING_DAYS = 3
LOW_VOLUME_MEDIAN = 1_000   # shares/day
GAP_MAX_MISSING = 3         # missing sessions in the window before flagging
BIG_WEEK_MOVE = 0.30
UNIT_JUMP_RATIO = 20        # day-over-day close ratio suggesting pence <-> pounds

TICKER_RE = re.compile(r"^[A-Z0-9]{2,6}$")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}

log = logging.getLogger("etf_screen")
HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
# 1. Universe
# --------------------------------------------------------------------------- #
def fetch_universe_html() -> str:
    resp = requests.get(UNIVERSE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def _walk_json(obj: object, out: dict[str, str]) -> None:
    """Collect {ticker: name} from any nested JSON objects that look like funds."""
    if isinstance(obj, dict):
        tick = next((obj[k] for k in ("ticker", "symbol", "code", "tickerSymbol")
                     if isinstance(obj.get(k), str)), None)
        name = next((obj[k] for k in ("name", "title", "fundName", "fullName")
                     if isinstance(obj.get(k), str)), None)
        if tick and name and TICKER_RE.match(tick.strip().upper()):
            out.setdefault(tick.strip().upper(), name.strip())
        for v in obj.values():
            _walk_json(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_json(v, out)


def parse_universe(html: str) -> pd.DataFrame:
    """Extract (ticker, name) pairs. Tries embedded JSON first, then visible text."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, str] = {}

    # a) Embedded JSON (Next.js / Nuxt / JSON-LD / inline state)
    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        text = text.strip()
        if not text:
            continue
        candidates = [text]
        if not text.startswith(("{", "[")):
            candidates = re.findall(r"(\{.*\}|\[.*\])", text, flags=re.S)[:1]
        for c in candidates:
            try:
                _walk_json(json.loads(c), found)
            except (ValueError, RecursionError):
                pass

    # b) Visible text: the ticker is the short uppercase token right after the fund name
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
    text_found: dict[str, str] = {}
    for prev, cur in zip(lines, lines[1:]):
        if (TICKER_RE.match(cur) and not cur.isdigit()
                and len(prev) > 8 and any(c.islower() for c in prev)):
            text_found.setdefault(cur, prev)

    # Prefer whichever method found more
    best = found if len(found) >= len(text_found) else text_found
    df = pd.DataFrame(sorted(best.items()), columns=["ticker", "name"])
    log.info("Parsed %d tickers (json=%d, text=%d)", len(df), len(found), len(text_found))
    return df


# --------------------------------------------------------------------------- #
# 2. Prices
# --------------------------------------------------------------------------- #
def download_prices(tickers: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (close, volume) wide frames indexed by date, columns = IE ticker."""
    start = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()
    closes, vols = [], []
    ysyms = [t + YAHOO_SUFFIX for t in tickers]
    for i in range(0, len(ysyms), BATCH_SIZE):
        batch = ysyms[i:i + BATCH_SIZE]
        log.info("Downloading batch %d-%d of %d", i + 1, i + len(batch), len(ysyms))
        data = yf.download(batch, start=start, interval="1d", auto_adjust=False,
                           group_by="column", threads=True, progress=False)
        if data.empty:
            continue
        c, v = data["Close"], data["Volume"]
        if isinstance(c, pd.Series):  # single-ticker batch
            c, v = c.to_frame(batch[0]), v.to_frame(batch[0])
        closes.append(c)
        vols.append(v)
    if not closes:
        return pd.DataFrame(), pd.DataFrame()
    close = pd.concat(closes, axis=1).sort_index()
    volume = pd.concat(vols, axis=1).sort_index()
    strip = {c: c[: -len(YAHOO_SUFFIX)] for c in close.columns}
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    volume.index = close.index
    return close.rename(columns=strip), volume.rename(columns=strip)


# --------------------------------------------------------------------------- #
# 3 + 4. Returns and quality checks
# --------------------------------------------------------------------------- #
def compute_row(s: pd.Series, v: pd.Series, sessions: pd.DatetimeIndex) -> dict:
    notes: list[str] = []
    s = s.dropna()
    if s.empty:
        return {"last_close_date": None, "ret_1w_pct": np.nan, "ret_1m_pct": np.nan,
                "notes": "not found on Yahoo"}

    last_dt = s.index[-1]
    last = s.iloc[-1]

    # 1W: latest close vs close 5 trading days earlier
    ret_1w = s.iloc[-1] / s.iloc[-1 - WEEK_LOOKBACK] - 1 if len(s) > WEEK_LOOKBACK else np.nan
    if np.isnan(ret_1w):
        notes.append("insufficient history for 1W")

    # 1M: latest close vs last close on/before same date one calendar month ago
    target = last_dt - pd.DateOffset(months=1)
    prior = s.loc[:target]
    ret_1m = last / prior.iloc[-1] - 1 if not prior.empty else np.nan
    if prior.empty:
        notes.append("insufficient history for 1M")

    # Stale price: sessions (seen across universe) after this ticker's last close
    stale = int((sessions > last_dt).sum())
    if stale > STALE_TRADING_DAYS:
        notes.append(f"stale: last price {stale} trading days old")

    # Volume / gaps
    vv = v.reindex(s.index).fillna(0)
    if vv.median() < LOW_VOLUME_MEDIAN:
        notes.append(f"low volume (median {int(vv.median()):,}/day)")
    window = sessions[(sessions >= s.index[0]) & (sessions <= last_dt)]
    missing = len(window.difference(s.index))
    if missing > GAP_MAX_MISSING:
        notes.append(f"data gaps ({missing} missing sessions)")

    # Unit errors / suspicious moves
    ratio = (s / s.shift(1)).dropna()
    if ((ratio > UNIT_JUMP_RATIO) | (ratio < 1 / UNIT_JUMP_RATIO)).any():
        notes.append("possible pence/pound unit error (~100x daily jump)")
    if not np.isnan(ret_1w) and abs(ret_1w) > BIG_WEEK_MOVE:
        notes.append(f"suspicious 1W move {ret_1w:+.0%} - check units")

    return {"last_close_date": last_dt.date(), "ret_1w_pct": round(ret_1w * 100, 2),
            "ret_1m_pct": round(ret_1m * 100, 2), "notes": "; ".join(notes)}


def build_results(universe: pd.DataFrame, close: pd.DataFrame,
                  volume: pd.DataFrame) -> pd.DataFrame:
    sessions = close.dropna(how="all").index
    rows = []
    for t, name in universe[["ticker", "name"]].itertuples(index=False):
        s = close[t] if t in close else pd.Series(dtype=float)
        v = volume[t] if t in volume else pd.Series(dtype=float)
        rows.append({"ticker": t, "name": name, **compute_row(s, v, sessions)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 5. Output
# --------------------------------------------------------------------------- #
def print_top(df: pd.DataFrame, col: str, label: str, n: int = 20) -> None:
    top = df.dropna(subset=[col]).sort_values(col, ascending=False).head(n)
    cols = ["ticker", "name", "last_close_date", "ret_1w_pct", "ret_1m_pct", "notes"]
    out = top[cols].copy()
    out["name"] = out["name"].str.slice(0, 45)
    print(f"\n=== Top {n} by {label} ===")
    print(out.to_string(index=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", help="parse a locally saved copy of the InvestEngine page")
    ap.add_argument("--universe", help="reuse an existing universe.csv (skip scraping)")
    ap.add_argument("--force", action="store_true",
                    help="continue even if far fewer tickers than expected were parsed")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # 1. Universe
    if args.universe:
        universe = pd.read_csv(args.universe)
    else:
        html = Path(args.html).read_text(encoding="utf-8") if args.html else fetch_universe_html()
        universe = parse_universe(html)
        universe.to_csv(HERE / "universe.csv", index=False)
        log.info("Saved universe.csv (%d ETFs)", len(universe))
    if len(universe) < MIN_UNIVERSE and not args.force:
        print(f"\nOnly {len(universe)} tickers parsed (expected ~{EXPECTED_UNIVERSE}). "
              "The page layout may have changed or be JS-rendered. Stopping so you can "
              "check universe.csv. Re-run with --force to continue anyway, or save the "
              "page from your browser and pass --html.")
        return 2

    # 2. Prices
    close, volume = download_prices(universe["ticker"].tolist())
    if close.empty:
        print("Yahoo returned no data at all - check your network connection.")
        return 1

    # 3 + 4
    results = build_results(universe, close, volume)
    results.to_csv(HERE / "results.csv", index=False)

    # 5
    print(f"\nPrices as of {close.dropna(how='all').index[-1].date()} "
          f"({len(results)} ETFs, source: Yahoo Finance {YAHOO_SUFFIX})")
    print_top(results, "ret_1w_pct", "1-week return")
    print_top(results, "ret_1m_pct", "1-month return")

    failed = results[results["last_close_date"].isna()]
    flagged = results[results["notes"].ne("") & results["last_close_date"].notna()]
    ok = len(results) - len(failed)
    print(f"\n=== Coverage: {ok}/{len(results)} found on Yahoo "
          f"({ok / len(results):.0%}); {len(flagged)} found but flagged ===")
    if not failed.empty:
        print("Not found on Yahoo (may use a different symbol there):")
        print("  " + ", ".join(failed["ticker"]))

    print("\nNOTE: These are PRICE returns only. Distributing funds pay out dividends, "
          "so they will look slightly worse here than their total return. Yahoo data "
          "is free but imperfect - verify anything near the top on InvestEngine or "
          "justETF before acting on it.")
    print(f"\nWrote {HERE / 'results.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
