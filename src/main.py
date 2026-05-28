"""Entry point. Invoked daily by the scheduler (GitHub Actions / cron)."""
from __future__ import annotations

import logging
import sys
from datetime import date

import config
from data.universe import build_universe
from emailer import format_email, send_email
from market_calendar import is_trading_day
from screener import run_screener, unique_hits

log = logging.getLogger("screener")


def _configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def run(today: date | None = None) -> int:
    """Run the screener for ``today`` (defaults to the current date)."""
    today = today or date.today()
    mode = config.validate_mode(config.SCAN_MODE)

    if not is_trading_day(today):
        log.info("%s is not a trading day — skipping.", today.isoformat())
        return 0

    log.info("Running NASDAQ screener for %s [mode=%s]", today.isoformat(), mode)
    universe = build_universe(mode)
    log.info("Base universe: %d ticker(s)", len(universe))

    results = run_screener(universe, mode)
    subject, html = format_email(results, today, mode)
    log.info("%s (%d unique tickers)", subject, unique_hits(results))

    if config.EMAIL_TO and config.SMTP_HOST:
        send_email(subject, html)
    else:
        log.warning("Email not configured (SMTP_HOST/EMAIL_TO); skipping send.")

    return 0


def main() -> int:
    _configure_logging()
    try:
        return run()
    except Exception:  # noqa: BLE001 - top-level guard so cron logs the traceback
        log.exception("Screener run failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
