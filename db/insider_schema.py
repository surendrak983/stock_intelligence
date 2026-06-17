"""
DB schema extension — Insider & Ownership Signals (Phase 2)

New tables alongside existing Phase 1 tables:
  1. insider_trades        — SEBI UPSI / SAST / bulk-deal disclosures
  2. pledge_tracker        — NSDL/CDSL promoter pledge data
  3. qib_allotments        — QIP / anchor allotment filings
  4. related_party_txns    — RPT disclosures from annual reports / filings
  5. director_checks       — MCA DIN records, disqualifications
  6. agm_egm_outcomes      — AGM/EGM voting results
  7. insider_alerts        — classified CRITICAL/HIGH/MEDIUM/LOW
"""

import sqlite3, os

INSIDER_DDL = """
CREATE TABLE IF NOT EXISTS insider_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,
    ticker          TEXT    NOT NULL,
    company_name    TEXT,
    trader_name     TEXT,
    trader_category TEXT,
    trade_type      TEXT,
    quantity        INTEGER,
    trade_value_cr  REAL,
    trade_date      TEXT,
    disclosure_date TEXT,
    window_type     TEXT,
    source_url      TEXT,
    collected_at    TEXT DEFAULT (datetime('now')),
    severity_score  REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS pledge_tracker (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,
    ticker          TEXT    NOT NULL,
    company_name    TEXT,
    promoter_name   TEXT,
    pledge_pct      REAL,
    pledged_shares  INTEGER,
    pledge_date     TEXT,
    change_pct      REAL,
    change_type     TEXT,
    source_url      TEXT,
    collected_at    TEXT DEFAULT (datetime('now')),
    severity_score  REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS qib_allotments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,
    ticker          TEXT    NOT NULL,
    company_name    TEXT,
    allotment_type  TEXT,
    anchor_name     TEXT,
    allotment_size_cr REAL,
    price           REAL,
    allotment_date  TEXT,
    discount_pct    REAL,
    source_url      TEXT,
    collected_at    TEXT DEFAULT (datetime('now')),
    severity_score  REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS related_party_txns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,
    ticker          TEXT    NOT NULL,
    company_name    TEXT,
    related_party   TEXT,
    txn_type        TEXT,
    txn_value_cr    REAL,
    txn_pct_revenue REAL,
    financial_year  TEXT,
    red_flags       TEXT,
    source_url      TEXT,
    collected_at    TEXT DEFAULT (datetime('now')),
    severity_score  REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS director_checks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,
    ticker          TEXT    NOT NULL,
    din             TEXT,
    director_name   TEXT,
    designation     TEXT,
    past_directorships TEXT,
    disqualified    INTEGER DEFAULT 0,
    disq_reason     TEXT,
    defaulting_companies TEXT,
    check_date      TEXT,
    source_url      TEXT,
    collected_at    TEXT DEFAULT (datetime('now')),
    severity_score  REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS agm_egm_outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,
    ticker          TEXT    NOT NULL,
    company_name    TEXT,
    meeting_type    TEXT,
    meeting_date    TEXT,
    resolution_title TEXT,
    votes_for_pct   REAL,
    votes_against_pct REAL,
    minority_dissent_pct REAL,
    resolution_passed INTEGER,
    dissent_flag    INTEGER DEFAULT 0,
    source_url      TEXT,
    collected_at    TEXT DEFAULT (datetime('now')),
    severity_score  REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS insider_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_type     TEXT NOT NULL,
    source_table    TEXT NOT NULL,
    source_id       INTEGER NOT NULL,
    ticker          TEXT,
    severity        TEXT NOT NULL CHECK(severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    reason          TEXT,
    delivered_tg    INTEGER DEFAULT 0,
    delivered_email INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_it_ticker   ON insider_trades(ticker);
CREATE INDEX IF NOT EXISTS idx_pt_ticker   ON pledge_tracker(ticker);
CREATE INDEX IF NOT EXISTS idx_qa_ticker   ON qib_allotments(ticker);
CREATE INDEX IF NOT EXISTS idx_rpt_ticker  ON related_party_txns(ticker);
CREATE INDEX IF NOT EXISTS idx_dc_ticker   ON director_checks(ticker);
CREATE INDEX IF NOT EXISTS idx_agm_ticker  ON agm_egm_outcomes(ticker);
CREATE INDEX IF NOT EXISTS idx_ia_ticker   ON insider_alerts(ticker);
CREATE INDEX IF NOT EXISTS idx_ia_severity ON insider_alerts(severity);
"""

def extend_db(conn: sqlite3.Connection) -> None:
    conn.executescript(INSIDER_DDL)
    conn.commit()

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from db.schema import init_db
    conn = init_db()
    extend_db(conn)
    print("[InsiderDB] Schema extended.")
    for tbl in ["insider_trades","pledge_tracker","qib_allotments",
                "related_party_txns","director_checks","agm_egm_outcomes","insider_alerts"]:
        n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {n} rows")
    conn.close()
