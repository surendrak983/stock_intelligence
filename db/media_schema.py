"""
SQLite schema for Media Intelligence Layer
Mirrors the Layer 2 structure from the architecture diagram:
  - events table  (raw collected items)
  - alerts table  (classified CRITICAL/HIGH/MEDIUM/LOW)
  - digest_history (morning digest log)
  - watchlist_config (tickers / keywords to track)
"""

import sqlite3
import os

import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.dirname(__file__))); DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "media_intel.db")


DDL = """
-- ── raw collected media items ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,          -- dedup key (sha256 of url+title)
    source_name     TEXT    NOT NULL,                 -- PTI, ET/Mint, MoneyControl, Bloomberg, etc.
    source_tier     TEXT    NOT NULL,                 -- Primary | Secondary | Signal
    url             TEXT,
    title           TEXT    NOT NULL,
    summary         TEXT,
    full_text       TEXT,
    tickers         TEXT,                             -- JSON list  e.g. ["RELIANCE","TCS"]
    event_type      TEXT,                             -- earnings | regulatory | mgmt | macro | litigation | sector
    published_at    TEXT,                             -- ISO-8601
    collected_at    TEXT    DEFAULT (datetime('now')),
    raw_sentiment   REAL,                             -- -1.0 … +1.0
    severity_score  REAL    DEFAULT 0.0               -- 0-10 computed score
);

-- ── classified alerts ready for delivery ───────────────────────────────────
CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER REFERENCES events(id),
    severity        TEXT    NOT NULL CHECK(severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    ticker          TEXT,
    reason          TEXT,                             -- human-readable classification reason
    delivered_tg    INTEGER DEFAULT 0,                -- 1 = sent via Telegram
    delivered_email INTEGER DEFAULT 0,
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ── morning digest history ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS digest_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_date TEXT    NOT NULL,
    html_report TEXT,
    sent_at     TEXT    DEFAULT (datetime('now')),
    item_count  INTEGER DEFAULT 0
);

-- ── per-ticker / keyword watchlist ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS watchlist_config (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT,
    keyword     TEXT,
    threshold   TEXT    DEFAULT 'HIGH',               -- minimum severity to alert on
    active      INTEGER DEFAULT 1
);

-- ── useful indices ──────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_events_hash        ON events(hash);
CREATE INDEX IF NOT EXISTS idx_events_ticker      ON events(tickers);
CREATE INDEX IF NOT EXISTS idx_events_collected   ON events(collected_at);
CREATE INDEX IF NOT EXISTS idx_alerts_severity    ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker      ON alerts(ticker);
"""


def init_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.commit()

    # seed a default watchlist if empty
    cur = conn.execute("SELECT COUNT(*) FROM watchlist_config")
    if cur.fetchone()[0] == 0:
        seeds = [
            ("RELIANCE", None, "HIGH"),
            ("TCS", None, "HIGH"),
            ("HDFCBANK", None, "HIGH"),
            ("INFY", None, "HIGH"),
            ("NIFTY50", None, "CRITICAL"),
            (None, "RBI", "HIGH"),
            (None, "SEBI", "CRITICAL"),
            (None, "FPI", "HIGH"),
            (None, "interest rate", "HIGH"),
            (None, "earnings", "MEDIUM"),
        ]
        conn.executemany(
            "INSERT INTO watchlist_config(ticker, keyword, threshold) VALUES(?,?,?)",
            seeds,
        )
        conn.commit()

    return conn


if __name__ == "__main__":
    conn = init_db()
    print(f"[DB] Initialised at {DB_PATH}")
    for tbl in ["events", "alerts", "digest_history", "watchlist_config"]:
        n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {n} rows")
    conn.close()
