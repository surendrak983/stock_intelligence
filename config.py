"""
config.py — Centralised configuration for the Stock Intelligence System
All credentials and tunable settings live here.
Set environment variables or edit defaults below.
"""

import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent
DB_DIR      = BASE_DIR / "db"
OUTPUT_DIR  = BASE_DIR / "outputs"
LOG_DIR     = BASE_DIR / "logs"

for d in [DB_DIR, OUTPUT_DIR, LOG_DIR]:
    d.mkdir(exist_ok=True)

MEDIA_DB_PATH      = str(DB_DIR / "media_intel.db")
REGULATORY_DB_PATH = str(DB_DIR / "regulatory_intel.db")
RESEARCH_DB_PATH   = str(DB_DIR / "equity_research.db")

# ── Delivery — Telegram ───────────────────────────────────────────────────────
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID   = os.getenv("TG_CHAT_ID", "")

# ── Delivery — Email (SMTP) ───────────────────────────────────────────────────
SMTP_HOST    = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT    = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER    = os.getenv("SMTP_USER", "")
SMTP_PASS    = os.getenv("SMTP_PASS", "")
ALERT_EMAIL  = os.getenv("ALERT_EMAIL", "")

# ── Delivery — WhatsApp (Twilio) ──────────────────────────────────────────────
TWILIO_SID     = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_WA = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
ALERT_WHATSAPP = os.getenv("ALERT_WHATSAPP_TO", "")

# ── Anthropic (optional AI enrichment) ───────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── Market hours (IST) ───────────────────────────────────────────────────────
MARKET_OPEN  = (9, 15)
MARKET_CLOSE = (15, 30)

# ── Scheduler intervals ───────────────────────────────────────────────────────
INTRADAY_INTERVAL_MIN  = 15
OVERNIGHT_INTERVAL_MIN = 60
DIGEST_TIME_IST        = (7, 50)

# ── Default watchlist ─────────────────────────────────────────────────────────
DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BHARTIARTL", "BAJFINANCE", "KOTAKBANK", "LT",
    "AXISBANK", "HINDUNILVR", "ITC", "WIPRO", "HCLTECH",
    "SUNPHARMA", "MARUTI", "TATAMOTORS", "ADANIENT", "ZOMATO",
]

# ── Alert thresholds ──────────────────────────────────────────────────────────
WHATSAPP_MIN_SEVERITY = "CRITICAL"
TELEGRAM_MIN_SEVERITY = "HIGH"
EMAIL_MIN_SEVERITY    = "MEDIUM"

# ── Web dashboard ─────────────────────────────────────────────────────────────
DASHBOARD_HOST  = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT  = int(os.getenv("DASHBOARD_PORT", "5000"))
DASHBOARD_DEBUG = os.getenv("DASHBOARD_DEBUG", "false").lower() == "true"
