"""
query_api.py — Structured query interface for the decision-making model
Returns clean dicts / DataFrames that the downstream equity decision model can consume.

Key outputs per the architecture's Layer 3 → decision pipeline:
  • get_alerts_summary()        — CRITICAL/HIGH alert counts by ticker
  • get_ticker_signals(ticker)  — all media signals for a specific stock
  • get_macro_signals()         — market-wide macro / regulatory signals
  • get_sector_signals()        — sector-level signals (from Signal-tier sources)
  • get_sentiment_by_ticker()   — aggregated sentiment scores per ticker
  • get_recent_events()         — latest N events for a quick scan
"""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from db.schema import init_db


# ─── helpers ────────────────────────────────────────────────────────────────

def _conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    return init_db(db_path) if db_path else init_db()


def _since(hours: int = 24) -> str:
    """ISO-8601 timestamp `hours` ago (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ─── public API ─────────────────────────────────────────────────────────────

def get_alerts_summary(hours: int = 24, conn=None) -> list[dict]:
    """
    Returns per-ticker alert counts for the last `hours`.
    Shape: [{ticker, CRITICAL, HIGH, MEDIUM, LOW, total}, …]
    Sorted by CRITICAL desc, then HIGH desc.
    """
    c = conn or _conn()
    rows = c.execute(
        """
        SELECT a.ticker,
               SUM(CASE WHEN a.severity='CRITICAL' THEN 1 ELSE 0 END) AS CRITICAL,
               SUM(CASE WHEN a.severity='HIGH'     THEN 1 ELSE 0 END) AS HIGH,
               SUM(CASE WHEN a.severity='MEDIUM'   THEN 1 ELSE 0 END) AS MEDIUM,
               SUM(CASE WHEN a.severity='LOW'      THEN 1 ELSE 0 END) AS LOW,
               COUNT(*) AS total
        FROM alerts a
        JOIN events e ON a.event_id = e.id
        WHERE e.collected_at >= ?
        GROUP BY a.ticker
        ORDER BY CRITICAL DESC, HIGH DESC
        """,
        (_since(hours),),
    ).fetchall()
    return [dict(r) for r in rows]


def get_ticker_signals(ticker: str, hours: int = 48, conn=None) -> list[dict]:
    """
    All media signals (title, severity, sentiment, source, event_type)
    for a given NSE ticker in the last `hours`.
    """
    c = conn or _conn()
    rows = c.execute(
        """
        SELECT e.title, e.summary, e.url, e.source_name, e.source_tier,
               e.event_type, e.published_at, e.raw_sentiment,
               a.severity, a.reason
        FROM alerts a
        JOIN events e ON a.event_id = e.id
        WHERE (a.ticker = ?
               OR e.tickers LIKE ?)
          AND e.collected_at >= ?
        ORDER BY
            CASE a.severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
                            WHEN 'MEDIUM' THEN 3 ELSE 4 END,
            e.published_at DESC
        """,
        (ticker, f"%{ticker}%", _since(hours)),
    ).fetchall()
    return [dict(r) for r in rows]


def get_macro_signals(hours: int = 24, conn=None) -> list[dict]:
    """
    Macro / regulatory / FPI events not tied to a specific ticker.
    These map to Bloomberg India + PTI/Reuters in the Media tab.
    """
    c = conn or _conn()
    rows = c.execute(
        """
        SELECT e.title, e.summary, e.url, e.source_name, e.source_tier,
               e.event_type, e.published_at, e.raw_sentiment,
               a.severity
        FROM alerts a
        JOIN events e ON a.event_id = e.id
        WHERE e.event_type IN ('macro', 'regulatory', 'fpi', 'credit')
          AND e.collected_at >= ?
        ORDER BY a.severity, e.published_at DESC
        LIMIT 50
        """,
        (_since(hours),),
    ).fetchall()
    return [dict(r) for r in rows]


def get_sector_signals(hours: int = 24, conn=None) -> list[dict]:
    """
    Sector-level signals from Signal-tier sources (auto, pharma, cement …).
    """
    c = conn or _conn()
    rows = c.execute(
        """
        SELECT e.title, e.summary, e.url, e.source_name,
               e.event_type, e.published_at, e.raw_sentiment,
               a.severity
        FROM alerts a
        JOIN events e ON a.event_id = e.id
        WHERE e.source_tier = 'Signal'
          AND e.collected_at >= ?
        ORDER BY e.published_at DESC
        LIMIT 30
        """,
        (_since(hours),),
    ).fetchall()
    return [dict(r) for r in rows]


def get_sentiment_by_ticker(hours: int = 24, conn=None) -> list[dict]:
    """
    Aggregated sentiment per ticker — useful as a feature vector
    for the downstream decision model.
    Shape: [{ticker, avg_sentiment, article_count, max_severity, score_sum}, …]
    """
    c = conn or _conn()
    rows = c.execute(
        """
        SELECT a.ticker,
               AVG(e.raw_sentiment)   AS avg_sentiment,
               COUNT(*)               AS article_count,
               MAX(CASE a.severity WHEN 'CRITICAL' THEN 4 WHEN 'HIGH' THEN 3
                                   WHEN 'MEDIUM' THEN 2 ELSE 1 END) AS severity_level,
               SUM(e.severity_score)  AS score_sum
        FROM alerts a
        JOIN events e ON a.event_id = e.id
        WHERE e.collected_at >= ?
          AND a.ticker IS NOT NULL
        GROUP BY a.ticker
        ORDER BY score_sum DESC
        """,
        (_since(hours),),
    ).fetchall()

    # map numeric severity_level back to label
    sev_map = {4: "CRITICAL", 3: "HIGH", 2: "MEDIUM", 1: "LOW"}
    result = []
    for r in rows:
        d = dict(r)
        d["max_severity"] = sev_map.get(d.pop("severity_level"), "LOW")
        d["avg_sentiment"] = round(d["avg_sentiment"] or 0.0, 4)
        d["score_sum"]     = round(d["score_sum"] or 0.0, 2)
        result.append(d)
    return result


def get_recent_events(n: int = 20, severity: Optional[str] = None, conn=None) -> list[dict]:
    """
    Quick scan of the latest `n` events, optionally filtered by severity.
    """
    c = conn or _conn()
    if severity:
        rows = c.execute(
            """
            SELECT e.title, e.source_name, e.source_tier, e.event_type,
                   e.published_at, e.raw_sentiment, a.severity, a.ticker,
                   e.url, e.tickers
            FROM alerts a JOIN events e ON a.event_id = e.id
            WHERE a.severity = ?
            ORDER BY e.collected_at DESC LIMIT ?
            """,
            (severity.upper(), n),
        ).fetchall()
    else:
        rows = c.execute(
            """
            SELECT e.title, e.source_name, e.source_tier, e.event_type,
                   e.published_at, e.raw_sentiment, a.severity, a.ticker,
                   e.url, e.tickers
            FROM alerts a JOIN events e ON a.event_id = e.id
            ORDER BY e.collected_at DESC LIMIT ?
            """,
            (n,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_decision_payload(ticker: str, hours: int = 24, conn=None) -> dict:
    """
    One-stop function: returns everything the decision model needs
    for a specific ticker in a single structured dict.
    """
    c = conn or _conn()
    ticker_sigs = get_ticker_signals(ticker, hours, c)
    sent_rows   = get_sentiment_by_ticker(hours, c)
    sent_row    = next((r for r in sent_rows if r["ticker"] == ticker), {})
    macro       = get_macro_signals(hours, c)

    return {
        "ticker":           ticker,
        "as_of":            datetime.now(timezone.utc).isoformat(),
        "hours_window":     hours,
        # Direct signals
        "ticker_alerts":    ticker_sigs,
        "alert_count":      len(ticker_sigs),
        "max_severity":     ticker_sigs[0]["severity"] if ticker_sigs else "NONE",
        # Aggregated sentiment
        "avg_sentiment":    sent_row.get("avg_sentiment", 0.0),
        "score_sum":        sent_row.get("score_sum", 0.0),
        # Macro context
        "macro_critical":   sum(1 for m in macro if m["severity"] == "CRITICAL"),
        "macro_high":       sum(1 for m in macro if m["severity"] == "HIGH"),
        "macro_signals":    macro[:5],   # top-5
    }


# ─── CLI quick-test ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import pprint, sys
    conn = _conn()

    print("\n── Alert summary (last 24 h) ──")
    pprint.pprint(get_alerts_summary(24, conn)[:5])

    print("\n── Sentiment by ticker ──")
    pprint.pprint(get_sentiment_by_ticker(24, conn)[:5])

    print("\n── Macro signals ──")
    pprint.pprint(get_macro_signals(24, conn)[:3])

    ticker = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    print(f"\n── Decision payload for {ticker} ──")
    pprint.pprint(get_decision_payload(ticker, 24, conn))

    conn.close()
