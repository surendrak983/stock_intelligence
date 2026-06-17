"""
delivery/telegram_bot.py
Telegram delivery: instant push alerts + /watchlist /digest /status bot commands.
Set TG_BOT_TOKEN and TG_CHAT_ID in environment or config.py.
"""
import json, logging, requests
from config import TG_BOT_TOKEN, TG_CHAT_ID, TELEGRAM_MIN_SEVERITY

logger = logging.getLogger("telegram_bot")
SEVERITY_EMOJI = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "📌", "LOW": "ℹ️"}
SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

def _post(payload: dict) -> bool:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        logger.info("[TG] Not configured — skipping.")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json=payload, timeout=8,
        )
        return r.status_code == 200
    except Exception as e:
        logger.warning("[TG] send failed: %s", e)
        return False


def send_alert(title: str, summary: str, severity: str,
               ticker: str = "", source: str = "", url: str = "") -> bool:
    """Send a single alert message."""
    if SEV_RANK.get(severity, 0) < SEV_RANK.get(TELEGRAM_MIN_SEVERITY, 3):
        return False
    emoji = SEVERITY_EMOJI.get(severity, "📰")
    tag   = f" #{ticker}" if ticker else ""
    text  = (
        f"{emoji} *{severity}*{tag} — {source}\n"
        f"*{title[:200]}*\n\n"
        f"{summary[:350]}\n"
        + (f"\n[Read →]({url})" if url else "")
    )
    return _post({"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "Markdown",
                  "disable_web_page_preview": True})


def send_digest_summary(date_str: str, counts: dict) -> bool:
    """Send morning digest summary card."""
    lines = [f"📰 *Morning Digest — {date_str}*\n"]
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        n = counts.get(sev, 0)
        if n:
            lines.append(f"{SEVERITY_EMOJI[sev]} {sev}: {n}")
    lines.append("\n_Full digest sent to email._")
    return _post({"chat_id": TG_CHAT_ID, "text": "\n".join(lines), "parse_mode": "Markdown"})


def send_text(text: str) -> bool:
    return _post({"chat_id": TG_CHAT_ID, "text": text})


def fire_pending_tg_alerts(conn) -> int:
    """Dispatch all undelivered HIGH/CRITICAL media alerts via Telegram."""
    rows = conn.execute("""
        SELECT a.id, a.severity, a.ticker, a.reason,
               e.title, e.summary, e.url, e.source_name, e.tickers
        FROM alerts a
        JOIN events e ON a.event_id = e.id
        WHERE a.severity IN ('CRITICAL','HIGH') AND a.delivered_tg = 0
        ORDER BY a.created_at DESC LIMIT 20
    """).fetchall()
    sent = 0
    for r in rows:
        tickers = json.loads(r["tickers"] or "[]")
        ok = send_alert(
            title    = r["title"],
            summary  = r["summary"] or "",
            severity = r["severity"],
            ticker   = r["ticker"] or (tickers[0] if tickers else ""),
            source   = r["source_name"],
            url      = r["url"] or "",
        )
        if ok:
            conn.execute("UPDATE alerts SET delivered_tg=1 WHERE id=?", (r["id"],))
            sent += 1
    conn.commit()
    return sent


def fire_pending_insider_tg(conn) -> int:
    """Dispatch undelivered insider alerts via Telegram."""
    rows = conn.execute("""
        SELECT id, severity, ticker, signal_type, reason
        FROM insider_alerts
        WHERE severity IN ('CRITICAL','HIGH') AND delivered_tg = 0
        ORDER BY created_at DESC LIMIT 10
    """).fetchall()
    sent = 0
    for r in rows:
        ok = send_alert(
            title    = f"{r['signal_type']} signal",
            summary  = r["reason"] or "",
            severity = r["severity"],
            ticker   = r["ticker"] or "",
            source   = "Insider Signals",
        )
        if ok:
            conn.execute("UPDATE insider_alerts SET delivered_tg=1 WHERE id=?", (r["id"],))
            sent += 1
    conn.commit()
    return sent


def fire_pending_credit_tg(conn) -> int:
    """Dispatch undelivered credit alerts via Telegram."""
    rows = conn.execute("""
        SELECT id, severity, ticker, company_name, signal_type, reason
        FROM credit_alerts
        WHERE severity IN ('CRITICAL','HIGH') AND delivered_tg = 0
        ORDER BY created_at DESC LIMIT 10
    """).fetchall()
    sent = 0
    for r in rows:
        ok = send_alert(
            title    = f"Credit: {r['signal_type']} — {r['company_name']}",
            summary  = r["reason"] or "",
            severity = r["severity"],
            ticker   = r["ticker"] or "",
            source   = "Credit Markets",
        )
        if ok:
            conn.execute("UPDATE credit_alerts SET delivered_tg=1 WHERE id=?", (r["id"],))
            sent += 1
    conn.commit()
    return sent
