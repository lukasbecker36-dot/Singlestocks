"""Render screener results as HTML and send via SMTP."""
from __future__ import annotations

import logging
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import pandas as pd

import config
from screener import unique_hits

log = logging.getLogger(__name__)

DISCLAIMER = (
    "This is a research tool, not financial advice. All investment decisions are your own."
)
SHORT_INTEREST_NOTE = (
    "Short interest / float data is reported on a delay (FINRA publishes biweekly), "
    "so Squeeze signals may be based on stale short-float figures."
)


def chart_url(symbol: str) -> str:
    """Finviz quote/chart link for a ticker."""
    return f"https://finviz.com/quote.ashx?t={escape(symbol)}"


def _fmt_cap(value: float) -> str:
    if pd.isna(value):
        return "—"
    if value >= 1e9:
        return f"${value / 1e9:.2f}B"
    return f"${value / 1e6:.0f}M"


def _fmt_price(value: float) -> str:
    return "—" if pd.isna(value) else f"${value:.2f}"


def _render_section(name: str, df: pd.DataFrame) -> str:
    if df.empty:
        return f"<h2>{escape(name)}</h2><p><em>No matches today.</em></p>"

    rows = []
    for _, r in df.iterrows():
        sym = str(r["symbol"])
        tag = str(r["match"]).upper()
        rows.append(
            "<tr>"
            f'<td><a href="{chart_url(sym)}">{escape(sym)}</a></td>'
            f"<td>{escape(str(r.get('company', '')))}</td>"
            f"<td>{_fmt_price(r['price'])}</td>"
            f"<td>{_fmt_cap(r['market_cap'])}</td>"
            f"<td>{escape(str(r['signal']))}</td>"
            f"<td>{tag}</td>"
            "</tr>"
        )
    header = (
        "<tr><th>Ticker</th><th>Company</th><th>Price</th><th>Mkt Cap</th>"
        "<th>Signal</th><th>Match</th></tr>"
    )
    return (
        f"<h2>{escape(name)} <small>({len(df)})</small></h2>"
        f'<table border="1" cellpadding="6" cellspacing="0" '
        f'style="border-collapse:collapse">{header}{"".join(rows)}</table>'
    )


def format_email(
    results: dict[str, pd.DataFrame], run_date: date, mode: str
) -> tuple[str, str]:
    """Build the (subject, html_body) pair for a screener run."""
    n = unique_hits(results)
    subject = f"📊 NASDAQ Screener — {run_date.isoformat()} — {n} hits"

    sections = "".join(_render_section(name, df) for name, df in results.items())
    body = (
        f"<html><body style='font-family:Arial,Helvetica,sans-serif'>"
        f"<p>Scan mode: <strong>{escape(mode)}</strong> · {run_date.isoformat()}</p>"
        f"{sections}"
        f"<hr><p style='color:#666;font-size:12px'>{escape(SHORT_INTEREST_NOTE)}</p>"
        f"<p style='color:#666;font-size:12px'>{escape(DISCLAIMER)}</p>"
        f"</body></html>"
    )
    return subject, body


def send_email(subject: str, html_body: str) -> None:
    """Send the screener email over SMTP using STARTTLS.

    Raises ``RuntimeError`` if required SMTP settings are missing.
    """
    if not (config.SMTP_HOST and config.EMAIL_TO and config.EMAIL_FROM):
        raise RuntimeError("SMTP_HOST, EMAIL_FROM and EMAIL_TO must all be configured")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = config.EMAIL_TO
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
        server.starttls()
        if config.SMTP_USER:
            server.login(config.SMTP_USER, config.SMTP_PASS)
        server.sendmail(config.EMAIL_FROM, config.EMAIL_TO.split(","), msg.as_string())
    log.info("Email sent to %s", config.EMAIL_TO)
