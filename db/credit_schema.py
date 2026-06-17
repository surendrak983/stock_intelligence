"""
DB schema — Credit & Debt Markets (Phase 3)
5 source tables + credit_alerts.
"""
import sqlite3, os, sys

CREDIT_DDL = """
CREATE TABLE IF NOT EXISTS credit_ratings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,
    ticker          TEXT,
    company_name    TEXT    NOT NULL,
    rating_agency   TEXT    NOT NULL,
    instrument      TEXT,
    old_rating      TEXT,
    new_rating      TEXT    NOT NULL,
    rating_action   TEXT    NOT NULL,
    outlook         TEXT,
    amount_cr       REAL,
    action_date     TEXT,
    source_url      TEXT,
    collected_at    TEXT DEFAULT (datetime('now')),
    severity_score  REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS cp_issuances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,
    ticker          TEXT,
    issuer_name     TEXT    NOT NULL,
    issuer_type     TEXT,
    cp_type         TEXT,
    face_value_cr   REAL,
    issuance_rate   REAL,
    peer_spread_bps REAL,
    tenor_days      INTEGER,
    issuance_date   TEXT,
    maturity_date   TEXT,
    source_url      TEXT,
    collected_at    TEXT DEFAULT (datetime('now')),
    severity_score  REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS cersai_charges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,
    ticker          TEXT,
    company_name    TEXT,
    secured_creditor TEXT,
    charge_type     TEXT,
    asset_type      TEXT,
    charge_amount_cr REAL,
    charge_date     TEXT,
    satisfaction_date TEXT,
    charge_id       TEXT,
    source_url      TEXT,
    collected_at    TEXT DEFAULT (datetime('now')),
    severity_score  REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS ccil_derivatives (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,
    ticker          TEXT,
    entity_name     TEXT,
    instrument_type TEXT,
    notional_cr     REAL,
    hedge_direction TEXT,
    hedge_type      TEXT,
    trade_date      TEXT,
    maturity_date   TEXT,
    pattern_flag    TEXT,
    source_url      TEXT,
    collected_at    TEXT DEFAULT (datetime('now')),
    severity_score  REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS rbi_credit_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    UNIQUE NOT NULL,
    sector          TEXT    NOT NULL,
    sub_sector      TEXT,
    credit_growth_pct  REAL,
    npa_ratio_pct      REAL,
    slippage_ratio_pct REAL,
    stressed_assets_pct REAL,
    period          TEXT,
    source_url      TEXT,
    collected_at    TEXT DEFAULT (datetime('now')),
    severity_score  REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS credit_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_type     TEXT NOT NULL,
    source_table    TEXT NOT NULL,
    source_id       INTEGER NOT NULL,
    ticker          TEXT,
    company_name    TEXT,
    severity        TEXT NOT NULL CHECK(severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    reason          TEXT,
    delivered_tg    INTEGER DEFAULT 0,
    delivered_email INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cr_ticker   ON credit_ratings(ticker);
CREATE INDEX IF NOT EXISTS idx_cr_action   ON credit_ratings(rating_action);
CREATE INDEX IF NOT EXISTS idx_cp_ticker   ON cp_issuances(ticker);
CREATE INDEX IF NOT EXISTS idx_ces_ticker  ON cersai_charges(ticker);
CREATE INDEX IF NOT EXISTS idx_ccil_ticker ON ccil_derivatives(ticker);
CREATE INDEX IF NOT EXISTS idx_rbi_sector  ON rbi_credit_data(sector);
CREATE INDEX IF NOT EXISTS idx_ca_ticker   ON credit_alerts(ticker);
CREATE INDEX IF NOT EXISTS idx_ca_severity ON credit_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_ca_type     ON credit_alerts(signal_type);
"""

def extend_db_credit(conn):
    conn.executescript(CREDIT_DDL)
    conn.commit()

if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from db.schema import init_db
    conn = init_db()
    extend_db_credit(conn)
    print("[CreditDB] Schema extended.")
    for tbl in ["credit_ratings","cp_issuances","cersai_charges","ccil_derivatives","rbi_credit_data","credit_alerts"]:
        print(f"  {tbl}: {conn.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]} rows")
    conn.close()
