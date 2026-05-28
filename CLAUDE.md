# CLAUDE.md — NASDAQ Small-Cap Stock Screener

## Project Purpose

Automated daily screener that identifies NASDAQ-listed small-cap stocks matching four investment strategies, then emails a summary of qualifying tickers each morning before market open.

## Architecture

```
src/
  strategies/        # One module per strategy (momentum, earnings, post_earnings_drift, squeeze)
  data/              # Data source adapters (API clients, rate limiting, caching)
  screener.py        # Orchestrator — runs all strategies, deduplicates, ranks
  emailer.py         # Formats results and sends via SMTP/SES
  config.py          # Environment-based config (API keys, email settings, thresholds)
  main.py            # Entry point — called by cron
tests/
  test_strategies.py
  test_screener.py
  fixtures/          # Sample API responses for offline testing
cron/
  screener.crontab   # Cron schedule definition
.env.example         # Template for secrets (never commit .env)
requirements.txt
```

**Language:** Python 3.11+
**Key libraries:** `pandas`, `requests`, `smtplib` / `boto3` (SES), `schedule` (optional alternative to system cron), `python-dotenv`

## Data Source

Use **Financial Modeling Prep (FMP)** API as the primary data source — it provides:

- Stock screener endpoint with most needed filters (exchange, market cap, price, volume, SMA, RSI, beta)
- Earnings calendar endpoint (upcoming and recent report dates)
- Key metrics (debt/equity, revenue growth, EPS growth, analyst consensus)
- Float and short interest data

Fallback/supplement: **Finviz** (scraping or API), **Alpha Vantage**, or **Polygon.io** if FMP lacks a specific field (e.g., short float percentage, gap %).

Store the API key in `.env` — never hardcode. Respect rate limits (cache daily fundamentals; only poll intraday metrics like relative volume fresh).

## Strategy Definitions

All strategies share a **base universe filter**:

- Exchange: NASDAQ only (no OTC/pink sheets)
- Market Cap: < $2B (tight) or < $300M micro-cap (loose)
- Price: > $5 (tight) or > $2 (loose)
- Avg Volume (3-month): > 1M (tight) or > 500K (loose)

### 1. Momentum

**Goal:** Find small-caps in confirmed uptrends with accelerating interest.

|Filter          |Tight               |Loose|
|----------------|--------------------|-----|
|Relative Volume |> 1.5               |> 1.0|
|Price vs SMA200 |Above               |Above|
|Price vs SMA50  |Above               |Above|
|RSI(14)         |50–70               |50–70|
|Performance (1W)|> 0%                |> 0% |
|Performance (1M)|≥ +10%              |≥ +5%|
|52-week high    |Yes (optional tight)|—    |
|Sales Q/Q       |> +10%              |—    |
|Debt/Equity     |< 0.5               |< 1.0|

### 2. Earnings (Pre-Earnings Play)

**Goal:** Stocks with bullish setups reporting earnings within the next 5 trading days.

|Filter          |Tight              |Loose              |
|----------------|-------------------|-------------------|
|Relative Volume |> 1.2              |> 1.0              |
|Price vs SMA50  |Above              |Above              |
|Price vs SMA200 |Above              |Above              |
|RSI(14)         |50–70              |50–70              |
|Performance (1M)|≥ +5%              |> 0%               |
|Earnings Date   |Next 5 trading days|Next 5 trading days|
|EPS Q/Q         |> 0% (optional)    |—                  |
|Sales Q/Q       |> 0% (optional)    |—                  |

### 3. Post-Earnings Drift

**Goal:** Stocks that beat earnings recently and are drifting higher (PEAD effect).

|Filter          |Tight                  |Loose                   |
|----------------|-----------------------|------------------------|
|Relative Volume |> 1.5                  |> 1.5                   |
|Price vs SMA20  |Above                  |Above                   |
|Price vs SMA50  |Above                  |Above                   |
|Price vs SMA200 |Above (optional)       |—                       |
|RSI(14)         |> 50                   |> 50                    |
|Performance (1W)|≥ +5%                  |≥ +5%                   |
|Earnings Date   |Previous 5 trading days|Previous 10 trading days|
|Gap Up          |≥ 5%                   |≥ 5%                    |

### 4. Squeeze (Short Squeeze)

**Goal:** Low-float, heavily shorted stocks showing early signs of a squeeze.

|Filter          |Tight               |Loose        |
|----------------|--------------------|-------------|
|Avg Volume      |> 500K              |> 300K       |
|Relative Volume |> 1.5               |> 1.5        |
|Price vs SMA20  |Above               |Above        |
|Price vs SMA50  |Above (optional)    |—            |
|Performance (1W)|> 0% (tight: > +10%)|> 0%         |
|Float           |< 50M shares        |< 100M shares|
|Short % of Float|> 15%               |> 10%        |
|Week Volatility |5–7%+ (optional)    |—            |

## Cron Schedule

Run daily at **6:00 AM ET** (before pre-market activity picks up). On weekends/holidays, the job should detect a non-trading day and skip gracefully.

```cron
0 6 * * 1-5 cd /path/to/project && python src/main.py >> logs/screener.log 2>&1
```

## Email Output Format

Subject: `📊 NASDAQ Screener — {date} — {N} hits`

Body should contain one section per strategy with a table:

- Ticker | Company | Price | Mkt Cap | Strategy-specific signal (e.g., RSI, short %, gap %)
- Link to chart (e.g., TradingView or Finviz chart URL)
- Loose vs tight tag per match

If zero results for a strategy, say so explicitly rather than omitting the section.

## Coding Conventions

- Each strategy is a function that takes a DataFrame of the base universe and returns filtered results with a `strategy` label column.
- All filter thresholds live in `config.py` as named constants with `_TIGHT` / `_LOOSE` suffixes — never use magic numbers in strategy code.
- Write pure functions where possible; side effects (API calls, email sending) are isolated in `data/` and `emailer.py`.
- Use `logging` module (not print). Log every strategy’s hit count and any API errors.
- Type hints on all public functions.
- Tests use saved fixture data so they run without API keys.

## Environment Variables (.env)

```
FMP_API_KEY=
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASS=
EMAIL_TO=
EMAIL_FROM=
SCAN_MODE=tight          # "tight" or "loose"
LOG_LEVEL=INFO
```

## Important Notes

- **This is not financial advice.** The screener is a research tool. All investment decisions are the user’s responsibility.
- Relative volume and gap % may require intraday data or previous-close comparison — handle this in the data layer, not in strategy logic.
- Short float data is notoriously delayed (FINRA reports biweekly). Document the staleness of any short interest data clearly in the email output.
- Rate-limit API calls and cache aggressively. FMP free tier is ~250 calls/day; batch where possible.
