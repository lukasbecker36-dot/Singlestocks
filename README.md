# NASDAQ Small-Cap Stock Screener

Automated daily screener that scans NASDAQ-listed small-cap stocks against four
investment strategies and emails a summary of qualifying tickers each morning before
market open.

> **This is a research tool, not financial advice.** All investment decisions are your own.

See [`CLAUDE.md`](CLAUDE.md) for the full specification (strategy tables, thresholds,
conventions).

## Strategies

| Strategy | Idea |
|----------|------|
| **Momentum** | Small-caps in confirmed uptrends with accelerating volume |
| **Earnings** | Bullish setups reporting within the next 5 trading days |
| **Post-Earnings Drift** | Recent earnings + gap-up drifting higher (PEAD) |
| **Squeeze** | Low-float, heavily shorted names showing early squeeze signs |

Every run reports **both** a **tight** and a **loose** scan in the same email (tight first,
loose below), so you see the strict setups and the wider net side by side.

## Project layout

```
src/
  config.py           # all thresholds as *_TIGHT / *_LOOSE constants (no magic numbers)
  data/
    yahoo.py          # Yahoo Finance adapter: NASDAQ list, history, indicators, fundamentals
    universe.py       # builds the normalised base-universe DataFrame
  strategies/         # one pure function per strategy: run(universe, mode) -> DataFrame
  market_calendar.py  # NYSE trading-day / holiday helpers
  screener.py         # orchestrator: run all strategies, rank, count
  emailer.py          # render HTML + send via SMTP
  main.py             # entry point (scheduler calls this)
tests/                # offline tests against tests/fixtures/
.github/workflows/    # scheduled GitHub Actions run (primary scheduler)
cron/                 # crontab for self-hosting
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in SMTP_*, EMAIL_*  (no data-source key needed)
```

Market data comes from **Yahoo Finance** via [`yfinance`](https://github.com/ranaroussi/yfinance)
— no API key. The screener builds the universe client-side: it pulls the public NASDAQ symbol
directory, bulk-downloads daily history (computing SMA/RSI/performance/relative volume/gap/
52-week high itself), then gates on price → volume → market cap and enriches the survivors
with fundamentals + short interest. The `MAX_PREFILTER` / `MAX_ENRICH` caps bound how many
per-ticker lookups happen, keeping a daily run fast and within Yahoo's tolerance.

## Run

```bash
python src/main.py
```

`main.py` skips weekends and U.S. market holidays automatically. If SMTP is unconfigured it
logs the subject line instead of sending — handy for a dry run. Point `SMTP_*` at a test
inbox (e.g. [Mailtrap](https://mailtrap.io/)) to preview the email safely.

## Tests

```bash
pytest
```

Tests use saved fixture data (`tests/fixtures/universe.json`) plus synthetic price series
and run fully offline — no network or API key required.

## Deployment

**GitHub Actions (recommended).** [`.github/workflows/screener.yml`](.github/workflows/screener.yml)
runs on a weekday cron. Add only the email settings as **repository secrets**: `SMTP_HOST`,
`SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_TO`, `EMAIL_FROM` (and optionally `LOG_LEVEL`
as a **repository variable**). No data-source key is needed. Trigger manually via
*Run workflow* to test.

> GitHub cron is UTC; the workflow uses two schedules to approximate 06:00 ET across DST.

**Self-hosted cron.** Alternatively use [`cron/screener.crontab`](cron/screener.crontab) on an
always-on server set to `America/New_York`.

## Notes

- **Short interest is delayed.** Short-float figures (FINRA, biweekly) reach Yahoo with a lag,
  so Squeeze signals may rest on stale data — the email says so explicitly.
- **Pre-market timing.** The run happens before the open, so the latest daily bar is the
  *prior* session; relative volume and gap % are measured on that session's close, not live
  pre-market activity.
- **Yahoo is an unofficial source.** `yfinance` can be rate-limited or occasionally return
  gaps, especially from cloud IPs. Missing fields degrade to `NaN` (optional filters pass,
  required filters exclude) rather than failing the run.
- Relative volume and gap % are derived in the data layer, never in strategy code.
- Fields a given FMP plan does not expose (e.g. float/short interest on the free tier) come
  back as `NaN`; optional filters treat `NaN` as a pass, required filters exclude it.
