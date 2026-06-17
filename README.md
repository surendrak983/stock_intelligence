# 🇮🇳 Stock Intelligence System

Fully integrated 3-layer Indian equity intelligence platform.

## Architecture

```
Layer 1 — Data Collectors (5 min during market hours, hourly after)
  ├── media_collector.py       PTI, Reuters, ET, Mint, BS, MoneyControl, CNBCTV18, Bloomberg
  ├── insider_collector.py     SEBI SAST, NSE/BSE pledge, QIB, RPT, Director checks, AGM/EGM
  ├── credit_collector.py      CRISIL/ICRA/CARE ratings, CP issuances, CERSAI, CCIL, RBI credit
  └── regulatory_collector.py  NSE/BSE corp announcements, RBI RSS, MCA stubs

Layer 2 — Processing Engine (SQLite + scoring + deduplication)
  ├── media_classifier.py      CRITICAL/HIGH/MEDIUM/LOW scoring for news events
  ├── insider_classifier.py    Insider trade, pledge, QIB, RPT, Director, AGM classifiers
  ├── credit_classifier.py     Rating action, CP spread, CERSAI, CCIL, RBI NPA classifiers
  ├── regulatory_classifier.py Regulatory event classification → signals
  └── decision_model.py        Aggregate signals → BUY/SELL/HOLD/AVOID equity decisions

Layer 3 — Delivery
  ├── telegram_bot.py          Instant push alerts (HIGH + CRITICAL)
  ├── whatsapp.py              CRITICAL-only via Twilio
  ├── email_digest.py          HTML report at 07:50 IST daily
  └── web_dashboard.py         Live feed at localhost:5000
```

## Quick Start

```bash
# 1. Install dependencies
pip install feedparser requests beautifulsoup4 flask

# 2. Configure credentials (optional — system works without them)
cp .env.example .env
# edit .env with your Telegram token, email, etc.

# 3. Demo run (no credentials needed)
python main.py demo

# 4. View live dashboard
python main.py dashboard   # open http://localhost:5000

# 5. Start live scheduler
python main.py schedule
```

## Commands

| Command | Description |
|---|---|
| `python main.py demo` | Inject demo data and run full pipeline |
| `python main.py collect` | Run live collectors once |
| `python main.py classify` | Classify all unprocessed events |
| `python main.py alerts` | Print all CRITICAL/HIGH alerts |
| `python main.py decisions` | Run decision model |
| `python main.py digest` | Generate today's HTML digest |
| `python main.py status` | Database statistics |
| `python main.py watchlist` | Show watchlist |
| `python main.py add TICKER` | Add ticker to watchlist |
| `python main.py dashboard` | Start web dashboard |
| `python main.py research` | Run equity research scoring |
| `python main.py schedule` | Start continuous scheduler |

## Databases

| DB | Purpose |
|---|---|
| `db/media_intel.db` | Media events, insider signals, credit signals, alerts, digest history |
| `db/regulatory_intel.db` | Raw regulatory events, classified events, signals, watchlist |
| `db/equity_research.db` | Screener financials, Trendlyne estimates, concall NLP, broker reports |

## Alert Severity Levels

| Level | Trigger examples |
|---|---|
| 🚨 CRITICAL | UPSI-window insider sell, pledge >50%, rating DEFAULT, SEBI ban |
| ⚠️ HIGH | Promoter pledge new creation, rating downgrade, director resignation |
| 📌 MEDIUM | QIB allotment, pledge release, concall guidance change |
| ℹ️ LOW | News mentions, routine filings |
