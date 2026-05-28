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

Each strategy runs in **tight** or **loose** mode (`SCAN_MODE`). Every hit is tagged
`tight`/`loose` so loose-mode runs still highlight the stronger setups.

## Project layout

```
src/
  config.py           # all thresholds as *_TIGHT / *_LOOSE constants (no magic numbers)
  data/
    fmp_client.py     # FMP REST client: rate limiting + daily on-disk cache
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
cp .env.example .env      # then fill in FMP_API_KEY, SMTP_*, EMAIL_*
```

Get a free [Financial Modeling Prep](https://financialmodelingprep.com/) API key. The free
tier allows ~250 calls/day; the client caches daily fundamentals/technicals under
`cache/<date>/` and only fetches quotes fresh, so keep `SCREEN_LIMIT` modest.

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

Tests use saved fixture data (`tests/fixtures/universe.json`) and run fully offline — no API
key required.

## Deployment

**GitHub Actions (recommended).** [`.github/workflows/screener.yml`](.github/workflows/screener.yml)
runs on a weekday cron. Add `FMP_API_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASS`, `EMAIL_TO`, `EMAIL_FROM` as **repository secrets**, and optionally `SCAN_MODE` /
`LOG_LEVEL` as **repository variables**. Trigger manually via *Run workflow* to test.

> GitHub cron is UTC; the workflow uses two schedules to approximate 06:00 ET across DST.

**Self-hosted cron.** Alternatively use [`cron/screener.crontab`](cron/screener.crontab) on an
always-on server set to `America/New_York`.

## Notes

- **Short interest is delayed.** FINRA publishes biweekly, so Squeeze signals may rest on
  stale short-float data — the email says so explicitly.
- Relative volume and gap % are derived in the data layer (`universe.py`), never in strategy
  code.
- Fields a given FMP plan does not expose (e.g. float/short interest on the free tier) come
  back as `NaN`; optional filters treat `NaN` as a pass, required filters exclude it.
