"""
Layer 3 — Output: Intraday Alerts
Polls for undelivered CRITICAL/HIGH alerts during market hours (9:15–15:30 IST)
and fires them via Telegram and/or email (configurable).
"""

import json
import logging
import smtplib
import sqlite3
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from typing import Optional

import requests

logger = logging.getLogger("intraday_alert")

# ── Config (fill from env or config file) ──────────────────────────────────
import os

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")          # set in environment
TG_CHAT_ID   = os.getenv("TG_CHAT_ID", "")
SMTP_HOST    = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT    = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER    = os.getenv("SMTP_USER", "")
SMTP_PASS    = os.getenv("SMTP_PASS", "")
ALERT_EMAIL  = os.getenv("ALERT_EMAIL", "")            # recipient

MARKET_OPEN  = (9, 15)   # HH, MM  IST
MARKET_CLOSE = (15, 30)

SEVERITY_EMOJI = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "📌", "LOW": "ℹ️"}


def _ist_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


def _in_market_hours() -> bool:
    now = _ist_now()
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t <= MARKET_CLOSE


def _format_telegram(event: dict, alert: dict) -> str:
    emoji = SEVERITY_EMOJI.get(alert["severity"], "📰")
    tickers = json.loads(event["tickers"] or "[]")
    ticker_str = " ".join(f"#{t}" for t in tickers) if tickers else ""
    return (
        f"{emoji} *{alert['severity']}* — {event['source_name']}\n"
        f"*{event['title'][:200]}*\n\n"
        f"{(event['summary'] or '')[:300]}\n\n"
        f"Type: `{event['event_type']}` | Tier: {event['source_tier']}\n"
        f"{ticker_str}\n"
        f"[Read more]({event['url'] or 'https://example.com'})"
    )


def _send_telegram(text: str) -> bool:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        logger.info("[TG] not configured — skipping Telegram send")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning("[TG] send failed: %s", e)
        return False


def _send_email(subject: str, body: str) -> bool:
    if not SMTP_USER or not ALERT_EMAIL:
        logger.info("[EMAIL] not configured — skipping email send")
        return False
    try:
        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = ALERT_EMAIL
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        logger.warning("[EMAIL] send failed: %s", e)
        return False


def _html_alert(event: dict, alert: dict) -> str:
    from processors.morning_digest import SEVERITY_COLOR
    color = SEVERITY_COLOR.get(alert["severity"], "#333")
    tickers = json.loads(event["tickers"] or "[]")
    chips = "".join(
        f'<span style="background:#e8eaf6;color:#283593;padding:1px 6px;'
        f'border-radius:3px;font-size:12px;margin:2px">{t}</span>'
        for t in tickers
    )
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;
                border-left:5px solid {color};padding:12px;background:#fff">
      <h3 style="color:{color};margin:0">{SEVERITY_EMOJI.get(alert['severity'],'')} {alert['severity']} ALERT</h3>
      <p style="font-weight:700">{event['title']}</p>
      <p style="color:#555;font-size:13px">{event['summary'] or ''}</p>
      <p>{chips}</p>
      <a href="{event['url'] or '#'}">Read full article →</a>
    </div>"""


def fire_pending_alerts(conn: sqlite3.Connection, force: bool = False) -> int:
    """
    Check for undelivered CRITICAL/HIGH alerts and dispatch them.
    During market hours only (unless force=True).
    Returns count of alerts dispatched.
    """
    if not force and not _in_market_hours():
        logger.info("[intraday] outside market hours — skipping")
        return 0

    rows = conn.execute(
        """
        SELECT a.id AS alert_id, a.severity, a.ticker, a.reason,
               e.title, e.summary, e.url, e.source_name, e.source_tier,
               e.tickers, e.event_type
        FROM alerts a
        JOIN events e ON a.event_id = e.id
        WHERE a.severity IN ('CRITICAL','HIGH')
          AND a.delivered_tg = 0
          AND a.delivered_email = 0
        ORDER BY a.created_at DESC
        LIMIT 20
        """
    ).fetchall()

    dispatched = 0
    for row in rows:
        event = dict(row)
        alert = {"severity": row["severity"], "reason": row["reason"]}

        tg_text   = _format_telegram(event, alert)
        html_body = _html_alert(event, alert)
        subject   = f"[{row['severity']}] {row['title'][:80]}"

        tg_ok    = _send_telegram(tg_text)
        email_ok = _send_email(subject, html_body)

        conn.execute(
            """UPDATE alerts SET delivered_tg=?, delivered_email=?
               WHERE id=?""",
            (int(tg_ok), int(email_ok), row["alert_id"]),
        )
        dispatched += 1
        logger.info(
            "[intraday] dispatched alert_id=%d  sev=%s  tg=%s  email=%s",
            row["alert_id"], row["severity"], tg_ok, email_ok,
        )

    conn.commit()
    return dispatched


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from db.schema import init_db
    conn = init_db()
    n = fire_pending_alerts(conn, force=True)
    print(f"Alerts dispatched: {n}")
    conn.close()
