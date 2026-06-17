"""
delivery/channels.py — Unified delivery: Telegram, WhatsApp (Twilio), Email
Called by both intraday_alert and morning_digest pipelines.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from config import (
    TG_BOT_TOKEN, TG_CHAT_ID,
    TWILIO_SID, TWILIO_TOKEN, TWILIO_WA_FROM, TWILIO_WA_TO,
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_EMAIL,
    DELIVERY_RULES,
)

logger = logging.getLogger("delivery")

SEVERITY_EMOJI = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "📌", "LOW": "ℹ️"}


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Telegram
# ─────────────────────────────────────────────────────────────────────────────

def send_telegram(text: str, parse_mode: str = "Markdown") -> bool:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        logger.debug("[TG] Not configured — skipping")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text[:4096], "parse_mode": parse_mode},
            timeout=8,
        )
        ok = resp.status_code == 200
        if not ok:
            logger.warning("[TG] Failed: %s", resp.text[:200])
        return ok
    except Exception as e:
        logger.warning("[TG] Exception: %s", e)
        return False


def format_alert_telegram(severity: str, ticker: str, title: str,
                           summary: str, source: str, url: str = "") -> str:
    emoji = SEVERITY_EMOJI.get(severity, "📰")
    tag   = f"#{ticker}" if ticker and ticker != "MARKET" else ""
    return (
        f"{emoji} *{severity}* — {source}\n"
        f"*{title[:180]}*\n\n"
        f"{(summary or '')[:280]}\n\n"
        f"{tag}\n"
        f"{('[Read →](' + url + ')') if url else ''}"
    ).strip()


# ─────────────────────────────────────────────────────────────────────────────
# 2.  WhatsApp via Twilio (CRITICAL only)
# ─────────────────────────────────────────────────────────────────────────────

def send_whatsapp(text: str) -> bool:
    if not TWILIO_SID or not TWILIO_TOKEN:
        logger.debug("[WA] Not configured — skipping")
        return False
    try:
        from twilio.rest import Client  # optional dep
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        msg = client.messages.create(
            body=text[:1600],
            from_=TWILIO_WA_FROM,
            to=TWILIO_WA_TO,
        )
        return msg.sid is not None
    except ImportError:
        logger.warning("[WA] twilio package not installed (pip install twilio)")
        return False
    except Exception as e:
        logger.warning("[WA] Failed: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Email (SMTP)
# ─────────────────────────────────────────────────────────────────────────────

def send_email(subject: str, html_body: str, to: str = "") -> bool:
    recipient = to or ALERT_EMAIL
    if not SMTP_USER or not recipient:
        logger.debug("[EMAIL] Not configured — skipping")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = recipient
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        logger.warning("[EMAIL] Failed: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Unified dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def dispatch_alert(severity: str, ticker: str, title: str,
                   summary: str, source: str, url: str = "",
                   html_body: str = "") -> dict:
    """
    Dispatch an alert to all channels appropriate for its severity.
    Returns dict of {channel: bool} delivery results.
    """
    channels = DELIVERY_RULES.get(severity, [])
    results = {}

    tg_text = format_alert_telegram(severity, ticker, title, summary, source, url)

    if "telegram" in channels:
        results["telegram"] = send_telegram(tg_text)

    if "whatsapp" in channels:
        wa_text = f"🚨 {severity} — {ticker}\n{title[:200]}\n{source}"
        results["whatsapp"] = send_whatsapp(wa_text)

    if "email" in channels:
        body = html_body or f"<h2>{severity}</h2><p>{title}</p><p>{summary}</p>"
        subj = f"[{severity}] {ticker}: {title[:80]}"
        results["email"] = send_email(subj, body)

    if results:
        logger.info("[Dispatch] %s %s → %s", severity, ticker, results)
    return results
