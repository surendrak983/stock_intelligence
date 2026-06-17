"""
Layer 1 — Media collector
Covers all 6 sources from the "Media" tab:
  1. PTI / Reuters India   → Primary   (RSS)
  2. ET / Mint / BS        → Secondary (RSS)
  3. MoneyControl/CNBCTV18 → Secondary (RSS + scrape)
  4. Bloomberg India       → Secondary (RSS)
  5. Sector trade media    → Signal    (RSS)
  6. Court/litigation      → Primary   (RSS/scrape)

Each article is hashed (url+title) for deduplication before insert.
"""

import hashlib
import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("media_collector")

# ── RSS feed catalogue ──────────────────────────────────────────────────────
FEEDS = [
    # ── PTI / Reuters India  (Primary) ─────────────────────────────────────
    {
        "source_name": "PTI",
        "source_tier": "Primary",
        "url": "https://www.ptinews.com/rss/businessfeed.xml",
        "event_types": ["regulatory", "macro", "earnings"],
    },
    {
        "source_name": "Reuters India",
        "source_tier": "Primary",
        "url": "https://feeds.reuters.com/reuters/INbusinessNews",
        "event_types": ["macro", "regulatory", "earnings"],
    },
    # ── ET / Mint / BS  (Secondary) ─────────────────────────────────────────
    {
        "source_name": "Economic Times",
        "source_tier": "Secondary",
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "event_types": ["earnings", "mgmt", "sector"],
    },
    {
        "source_name": "Mint",
        "source_tier": "Secondary",
        "url": "https://www.livemint.com/rss/markets",
        "event_types": ["macro", "earnings", "sector"],
    },
    {
        "source_name": "Business Standard",
        "source_tier": "Secondary",
        "url": "https://www.business-standard.com/rss/markets-106.rss",
        "event_types": ["macro", "earnings", "regulatory"],
    },
    # ── MoneyControl / CNBCTV18  (Secondary) ────────────────────────────────
    {
        "source_name": "MoneyControl",
        "source_tier": "Secondary",
        "url": "https://www.moneycontrol.com/rss/business.xml",
        "event_types": ["earnings", "mgmt", "macro"],
    },
    {
        "source_name": "CNBCTV18",
        "source_tier": "Secondary",
        "url": "https://www.cnbctv18.com/commonfeeds/v1/eng/rss/market.xml",
        "event_types": ["macro", "earnings", "sector"],
    },
    # ── Bloomberg India  (Secondary) ────────────────────────────────────────
    {
        "source_name": "Bloomberg India",
        "source_tier": "Secondary",
        "url": "https://feeds.bloomberg.com/markets/news.rss",
        "event_types": ["macro", "fpi", "credit"],
    },
    # ── Sector trade media  (Signal) ────────────────────────────────────────
    {
        "source_name": "Auto Dealers / SIAM",
        "source_tier": "Signal",
        "url": "https://www.siamindia.com/rss.aspx",
        "event_types": ["sector"],
    },
    {
        "source_name": "Pharma AIOCD",
        "source_tier": "Signal",
        "url": "https://www.aiocd.net/feed",
        "event_types": ["sector"],
    },
    # ── Court / Litigation  (Primary) ───────────────────────────────────────
    {
        "source_name": "Livelaw",
        "source_tier": "Primary",
        "url": "https://www.livelaw.in/feed",
        "event_types": ["litigation"],
    },
]

# ── Google News RSS for tickers/keywords (supplementary) ───────────────────
GNEWS_QUERIES = [
    "NSE BSE India stocks",
    "SEBI regulatory India",
    "RBI interest rate India",
    "India corporate earnings results",
    "FPI FII India equity",
]

GNEWS_BASE = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

# ── Nifty-50 common tickers (used for entity extraction) ───────────────────
NIFTY50_TICKERS = [
    "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC",
    "SBIN","BHARTIARTL","BAJFINANCE","KOTAKBANK","LT","AXISBANK","ASIANPAINT",
    "MARUTI","HCLTECH","SUNPHARMA","WIPRO","ULTRACEMCO","NESTLEIND",
    "ADANIENT","POWERGRID","NTPC","TITAN","ONGC","TECHM","JSWSTEEL",
    "COALINDIA","BAJAJ-AUTO","GRASIM","CIPLA","DRREDDY","HINDALCO","EICHERMOT",
    "DIVISLAB","BPCL","BRITANNIA","SBILIFE","UPL","HEROMOTOCO",
    "TATACONSUM","APOLLOHOSP","TATAPOWER","TATACOMM","TATAMOTORS",
    "ADANIPORTS","BAJAJFINSV","M&M","INDUSINDBK","HDFCLIFE",
]

# company-name → ticker map (partial)
NAME_TO_TICKER = {
    "reliance": "RELIANCE", "tcs": "TCS", "tata consultancy": "TCS",
    "hdfc bank": "HDFCBANK", "infosys": "INFY", "icici bank": "ICICIBANK",
    "hindustan unilever": "HINDUNILVR", "itc": "ITC", "state bank": "SBIN",
    "bharti airtel": "BHARTIARTL", "bajaj finance": "BAJFINANCE",
    "kotak mahindra": "KOTAKBANK", "larsen": "LT", "axis bank": "AXISBANK",
    "asian paints": "ASIANPAINT", "maruti": "MARUTI", "hcl tech": "HCLTECH",
    "sun pharma": "SUNPHARMA", "wipro": "WIPRO", "ultratech": "ULTRACEMCO",
}


def _make_hash(url: str, title: str) -> str:
    return hashlib.sha256(f"{url}|{title}".encode()).hexdigest()


def _extract_tickers(text: str) -> list[str]:
    """Simple regex + name lookup to pull ticker symbols from article text."""
    found = set()
    upper = text.upper()
    for t in NIFTY50_TICKERS:
        if re.search(rf"\b{t}\b", upper):
            found.add(t)
    lower = text.lower()
    for name, ticker in NAME_TO_TICKER.items():
        if name in lower:
            found.add(ticker)
    return sorted(found)


def _infer_event_type(text: str, defaults: list[str]) -> str:
    t = text.lower()
    if any(w in t for w in ["sebi", "rbi", "regulatory", "circular", "notification"]):
        return "regulatory"
    if any(w in t for w in ["earnings", "results", "profit", "revenue", "q1", "q2", "q3", "q4"]):
        return "earnings"
    if any(w in t for w in ["ceo", "md", "management", "appoint", "resign", "board"]):
        return "mgmt"
    if any(w in t for w in ["court", "litigation", "supreme court", "dispute", "penalty"]):
        return "litigation"
    if any(w in t for w in ["fpi", "fii", "foreign investor", "credit spread", "global"]):
        return "macro"
    return defaults[0] if defaults else "general"


def _parse_published(entry) -> str:
    """Return ISO-8601 string regardless of feed format."""
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
    except Exception:
        pass
    return datetime.now(timezone.utc).isoformat()


def fetch_feed(feed_cfg: dict, timeout: int = 10) -> list[dict]:
    """Parse a single RSS feed and return list of normalised article dicts."""
    articles = []
    try:
        fp = feedparser.parse(feed_cfg["url"])
        for entry in fp.entries:
            title   = entry.get("title", "").strip()
            url     = entry.get("link", "").strip()
            summary = BeautifulSoup(
                entry.get("summary", entry.get("description", "")), "html.parser"
            ).get_text(" ", strip=True)[:1000]

            if not title:
                continue

            tickers    = _extract_tickers(f"{title} {summary}")
            event_type = _infer_event_type(
                f"{title} {summary}", feed_cfg.get("event_types", ["general"])
            )

            articles.append(
                {
                    "hash":         _make_hash(url, title),
                    "source_name":  feed_cfg["source_name"],
                    "source_tier":  feed_cfg["source_tier"],
                    "url":          url,
                    "title":        title,
                    "summary":      summary,
                    "tickers":      json.dumps(tickers),
                    "event_type":   event_type,
                    "published_at": _parse_published(entry),
                }
            )
    except Exception as exc:
        logger.warning("Feed %s failed: %s", feed_cfg["source_name"], exc)
    return articles


def fetch_gnews(query: str) -> list[dict]:
    """Fetch Google News RSS for a search query."""
    url = GNEWS_BASE.format(query=requests.utils.quote(query))
    cfg = {
        "source_name": f"GoogleNews:{query[:30]}",
        "source_tier": "Secondary",
        "url": url,
        "event_types": ["macro"],
    }
    return fetch_feed(cfg)


def collect_all(conn: sqlite3.Connection) -> int:
    """Run all collectors, dedup, and store in DB. Returns new article count."""
    all_articles: list[dict] = []

    for cfg in FEEDS:
        arts = fetch_feed(cfg)
        logger.info("  %-25s → %d articles", cfg["source_name"], len(arts))
        all_articles.extend(arts)

    for q in GNEWS_QUERIES:
        arts = fetch_gnews(q)
        logger.info("  GNews %-35s → %d articles", q[:35], len(arts))
        all_articles.extend(arts)

    inserted = 0
    for art in all_articles:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO events
                   (hash, source_name, source_tier, url, title, summary,
                    tickers, event_type, published_at)
                   VALUES (:hash,:source_name,:source_tier,:url,:title,:summary,
                           :tickers,:event_type,:published_at)""",
                art,
            )
            if conn.execute(
                "SELECT changes()"
            ).fetchone()[0]:
                inserted += 1
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    logger.info("[collect_all] inserted %d new events (total attempted: %d)", inserted, len(all_articles))
    return inserted


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from db.schema import init_db
    conn = init_db()
    collect_all(conn)
    conn.close()
