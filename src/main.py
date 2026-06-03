"""Entry point. Invoked daily by the scheduler (GitHub Actions / cron)."""
from __future__ import annotations

import logging
import sys
from datetime import date

import config
from data.universe import apply_base_filter, scan_and_enrich
from emailer import format_email, send_email
from market_calendar import is_trading_day
from screener import run_screener, unique_hits

log = logging.getLogger("screener")

# The email always reports both modes: tight first, loose below.
MODES = ("tight", "loose")

# Fields that are often missing from the free data source; if a strategy hard-requires one
# and it is absent, the row is silently excluded. Logging coverage helps diagnose empties.
_COVERAGE_COLS = (
    "debt_equity", "earnings_trading_days", "short_pct_float", "float_shares",
    "sales_qoq", "eps_qoq",
)


def _coverage(universe) -> dict[str, str]:
    return {c: f"{int(universe[c].notna().sum())}/{len(universe)}" for c in _COVERAGE_COLS}


def _configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def run(today: date | None = None) -> int:
    """Run the screener for ``today`` (defaults to the current date)."""
    today = today or date.today()

    if not is_trading_day(today):
        log.info("%s is not a trading day — skipping.", today.isoformat())
        return 0

    log.info("Running NASDAQ screener for %s [modes=%s]", today.isoformat(), ", ".join(MODES))
    frame = scan_and_enrich()  # expensive Yahoo scan happens once
    log.info("Enriched universe: %d ticker(s)", len(frame))

    results_by_mode: dict[str, dict] = {}
    for mode in MODES:
        universe = apply_base_filter(frame, mode)
        log.info("Base universe [%s]: %d ticker(s) | data coverage: %s",
                 mode, len(universe), _coverage(universe))
        results = run_screener(universe, mode)
        results_by_mode[mode] = results
        log.info("Base universe [%s]: %d hit(s)", mode, unique_hits(results))

    subject, html = format_email(results_by_mode, today)
    log.info("%s", subject)

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
