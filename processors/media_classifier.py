"""
Layer 2 — Processing engine
  • Event parser   : severity scoring, entity extraction
  • Alert classifier: CRITICAL / HIGH / MEDIUM / LOW
    Uses keyword rules + price-impact heuristics as shown in architecture diagram.
"""

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("alert_classifier")

# ── Keyword rule tables ─────────────────────────────────────────────────────

CRITICAL_KEYWORDS = [
    # Regulatory / systemic
    "sebi ban", "trading halt", "suspension", "default", "insolvency",
    "bankruptcy", "fraud", "scam", "cbi raid", "ed raid", "promoter arrested",
    "nclt", "nclt order", "liquidation", "rbi penalty", "licence cancelled",
    "merger blocked", "acquisition blocked", "force majeure",
    # Market-moving macro
    "rate hike", "rate cut", "emergency", "circuit breaker", "market crash",
    "financial crisis", "sovereign downgrade", "currency crisis",
    # Corporate events
    "ceo resigned", "md resigned", "chairman resigned", "auditor resigned",
    "accounting fraud", "restatement", "going concern",
]

HIGH_KEYWORDS = [
    "profit warning", "earnings miss", "revenue miss", "guidance cut",
    "downgrade", "rating cut", "credit watch", "negative outlook",
    "rights issue", "qip", "block deal", "bulk deal", "fpo",
    "mgmt change", "ceo appointed", "board meeting", "dividend",
    "buyback", "open offer", "delisting", "regulatory notice",
    "show cause", "adjudication", "insider trading", "pledge",
    "fpi selling", "fpi outflow", "macro headwind",
    "court order", "supreme court", "penalty",
]

MEDIUM_KEYWORDS = [
    "quarterly results", "q1 results", "q2 results", "q3 results", "q4 results",
    "annual results", "earnings", "revenue growth", "margin improvement",
    "order win", "contract", "partnership", "joint venture", "capex",
    "expansion", "plant shutdown", "strike", "labour unrest",
    "price hike", "price cut", "market share", "analyst meet",
    "credit upgrade", "rating upgrade", "positive outlook",
    "fpi buying", "fpi inflow",
]

LOW_KEYWORDS = [
    "product launch", "event", "conference", "agm", "egm",
    "compliance", "press release", "management interview",
    "sector report", "analyst note", "target price",
]

# Source-tier weight multipliers
TIER_WEIGHT = {"Primary": 1.3, "Secondary": 1.0, "Signal": 0.8}

# Event-type base scores
EVENT_BASE_SCORE = {
    "regulatory": 7.0,
    "litigation": 6.5,
    "macro": 5.5,
    "earnings": 5.0,
    "mgmt": 6.0,
    "sector": 4.0,
    "fpi": 5.0,
    "credit": 5.5,
    "general": 3.0,
}


def _keyword_score(text: str) -> tuple[float, str, str]:
    """
    Returns (score 0-10, severity label, matched reason).
    Checks keyword lists in order: CRITICAL → HIGH → MEDIUM → LOW.
    """
    tl = text.lower()

    for kw in CRITICAL_KEYWORDS:
        if kw in tl:
            return 9.0, "CRITICAL", f"keyword: '{kw}'"

    for kw in HIGH_KEYWORDS:
        if kw in tl:
            return 7.0, "HIGH", f"keyword: '{kw}'"

    for kw in MEDIUM_KEYWORDS:
        if kw in tl:
            return 5.0, "MEDIUM", f"keyword: '{kw}'"

    for kw in LOW_KEYWORDS:
        if kw in tl:
            return 3.0, "LOW", f"keyword: '{kw}'"

    return 2.0, "LOW", "no matching keyword"


def _watchlist_boost(
    tickers: list[str], keywords_in_text: str, watchlist: list[dict]
) -> float:
    """Add +1.5 to score if the article matches a watched ticker or keyword."""
    boost = 0.0
    tl = keywords_in_text.lower()
    for w in watchlist:
        if w["ticker"] and w["ticker"] in tickers:
            boost = max(boost, 1.5)
        if w["keyword"] and w["keyword"].lower() in tl:
            boost = max(boost, 1.0)
    return boost


def compute_severity(
    title: str,
    summary: str,
    event_type: str,
    source_tier: str,
    tickers: list[str],
    watchlist: list[dict],
) -> tuple[float, str, str]:
    """
    Full severity pipeline:
      base (event_type) + keyword_score + tier_weight + watchlist_boost → final score
    Returns (severity_score, severity_label, reason).
    """
    text = f"{title} {summary}"

    kw_score, severity, reason = _keyword_score(text)
    base    = EVENT_BASE_SCORE.get(event_type, 3.0)
    tier_w  = TIER_WEIGHT.get(source_tier, 1.0)
    wb      = _watchlist_boost(tickers, text, watchlist)

    raw_score = ((kw_score * 0.6) + (base * 0.3)) * tier_w + wb
    score = min(round(raw_score, 2), 10.0)

    # Re-map label based on final numeric score
    if score >= 8.5:
        label = "CRITICAL"
    elif score >= 6.5:
        label = "HIGH"
    elif score >= 4.5:
        label = "MEDIUM"
    else:
        label = "LOW"

    return score, label, reason


def _simple_sentiment(text: str) -> float:
    """
    Naïve rule-based sentiment without external model dependencies.
    Returns -1.0 (very negative) … +1.0 (very positive).
    """
    positive = [
        "profit", "growth", "beat", "upgrade", "surge", "rally",
        "outperform", "positive", "buyback", "dividend", "win",
        "record", "expansion", "recovery", "inflow",
    ]
    negative = [
        "loss", "miss", "downgrade", "fall", "crash", "fraud",
        "penalty", "default", "cut", "decline", "warning",
        "outflow", "liquidation", "ban", "suspended", "arrested",
    ]
    tl = text.lower()
    pos = sum(1 for w in positive if w in tl)
    neg = sum(1 for w in negative if w in tl)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 3)


def classify_unprocessed(conn: sqlite3.Connection) -> int:
    """
    Pull events without a severity_score, score them, and write alerts.
    Returns count of new alerts created.
    """
    watchlist = [
        dict(r)
        for r in conn.execute(
            "SELECT ticker, keyword, threshold FROM watchlist_config WHERE active=1"
        ).fetchall()
    ]

    rows = conn.execute(
        """SELECT id, title, summary, event_type, source_tier, tickers
           FROM events
           WHERE severity_score = 0
           ORDER BY collected_at DESC
           LIMIT 500"""
    ).fetchall()

    new_alerts = 0
    for row in rows:
        tickers = json.loads(row["tickers"] or "[]")
        text    = f"{row['title']} {row['summary'] or ''}"
        sentiment = _simple_sentiment(text)

        score, label, reason = compute_severity(
            title      = row["title"],
            summary    = row["summary"] or "",
            event_type = row["event_type"] or "general",
            source_tier= row["source_tier"],
            tickers    = tickers,
            watchlist  = watchlist,
        )

        conn.execute(
            "UPDATE events SET severity_score=?, raw_sentiment=? WHERE id=?",
            (score, sentiment, row["id"]),
        )

        # Only create an alert for MEDIUM and above
        if label in ("CRITICAL", "HIGH", "MEDIUM"):
            for ticker in (tickers or [None]):
                conn.execute(
                    """INSERT INTO alerts(event_id, severity, ticker, reason)
                       VALUES (?,?,?,?)""",
                    (row["id"], label, ticker, reason),
                )
                new_alerts += 1

    conn.commit()
    logger.info("[classifier] scored %d events → %d new alerts", len(rows), new_alerts)
    return new_alerts


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from db.schema import init_db
    conn = init_db()
    n = classify_unprocessed(conn)
    print(f"Classified: {n} new alerts")
    conn.close()
