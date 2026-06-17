"""
delivery/whatsapp.py — CRITICAL-only WhatsApp alerts via Twilio API.
Requires: pip install twilio
Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, ALERT_WHATSAPP_TO.
"""
import logging
from config import TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM_WA, ALERT_WHATSAPP

logger = logging.getLogger("whatsapp")


def send_whatsapp(message: str) -> bool:
    if not all([TWILIO_SID, TWILIO_TOKEN, ALERT_WHATSAPP]):
        logger.info("[WA] Twilio not configured — skipping.")
        return False
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(
            body=message,
            from_=TWILIO_FROM_WA,
            to=ALERT_WHATSAPP,
        )
        return True
    except Exception as e:
        logger.warning("[WA] send failed: %s", e)
        return False


def fire_critical_whatsapp(conn) -> int:
    """Send CRITICAL-only alerts via WhatsApp (all three alert tables)."""
    sent = 0

    # Media alerts
    rows = conn.execute("""
        SELECT a.id, a.severity, a.ticker, a.reason,
               e.title, e.source_name
        FROM alerts a JOIN events e ON a.event_id = e.id
        WHERE a.severity='CRITICAL' AND a.delivered_tg=0
        ORDER BY a.created_at DESC LIMIT 5
    """).fetchall()
    for r in rows:
        msg = f"🚨 CRITICAL — {r['source_name']}\n{r['title'][:200]}\nTicker: {r['ticker'] or 'N/A'}"
        if send_whatsapp(msg):
            sent += 1

    # Insider alerts
    rows = conn.execute("""
        SELECT id, ticker, signal_type, reason
        FROM insider_alerts WHERE severity='CRITICAL' AND delivered_tg=0
        LIMIT 5
    """).fetchall()
    for r in rows:
        msg = f"🚨 CRITICAL INSIDER — {r['signal_type']}\nTicker: {r['ticker']}\n{r['reason'][:200]}"
        if send_whatsapp(msg):
            sent += 1

    # Credit alerts
    rows = conn.execute("""
        SELECT id, ticker, company_name, signal_type, reason
        FROM credit_alerts WHERE severity='CRITICAL' AND delivered_tg=0
        LIMIT 5
    """).fetchall()
    for r in rows:
        msg = f"🚨 CRITICAL CREDIT — {r['signal_type']}\n{r['company_name']} ({r['ticker'] or 'N/A'})\n{r['reason'][:200]}"
        if send_whatsapp(msg):
            sent += 1

    return sent
