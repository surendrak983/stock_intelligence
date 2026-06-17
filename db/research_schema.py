"""
Database schema for Indian Equity Research Platform
Covers: Screener.in, Trendlyne, Tickertape, Broker Research, CMIE, Dion Global, Concall data
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'equity_research.db')

SCHEMA_SQL = """
-- ─────────────────────────────────────────────
-- MASTER TABLES
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS watchlist (
    ticker          TEXT PRIMARY KEY,
    company_name    TEXT NOT NULL,
    sector          TEXT,
    industry        TEXT,
    market_cap_cr   REAL,
    added_on        TEXT DEFAULT (datetime('now')),
    is_active       INTEGER DEFAULT 1,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS data_pull_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    ticker          TEXT,
    pulled_at       TEXT DEFAULT (datetime('now')),
    status          TEXT,       -- success / error / partial
    records_fetched INTEGER DEFAULT 0,
    error_msg       TEXT
);

-- ─────────────────────────────────────────────
-- SOURCE 1: SCREENER.IN  (Secondary)
-- 10-yr financials, concall transcripts, shareholding, peer comparison
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS screener_financials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    fiscal_year     INTEGER,
    period_type     TEXT,       -- annual / quarterly
    period_end      TEXT,       -- YYYY-MM-DD
    revenue_cr      REAL,
    ebitda_cr       REAL,
    pat_cr          REAL,       -- Profit After Tax
    eps             REAL,
    roce_pct        REAL,
    roe_pct         REAL,
    debt_to_equity  REAL,
    current_ratio   REAL,
    ocf_cr          REAL,       -- Operating Cash Flow
    capex_cr        REAL,
    free_cashflow_cr REAL,
    gross_margin_pct REAL,
    net_margin_pct  REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, period_end, period_type)
);

CREATE TABLE IF NOT EXISTS screener_shareholding (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    period_end      TEXT,
    promoter_pct    REAL,
    promoter_pledge_pct REAL,
    dii_pct         REAL,
    fii_pct         REAL,
    public_pct      REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, period_end)
);

CREATE TABLE IF NOT EXISTS screener_peer_comparison (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    peer_ticker     TEXT NOT NULL,
    metric          TEXT,       -- PE, PB, EV_EBITDA, etc.
    ticker_value    REAL,
    peer_value      REAL,
    sector_median   REAL,
    as_of_date      TEXT,
    fetched_at      TEXT DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────
-- SOURCE 2: TRENDLYNE  (Secondary)
-- Earnings estimate revisions, promoter pledging alerts, analyst target tracker
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS trendlyne_estimate_revisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    analyst_house   TEXT,
    revision_date   TEXT,
    estimate_type   TEXT,       -- EPS / Revenue / EBITDA
    period          TEXT,       -- FY26E / FY27E
    old_estimate    REAL,
    new_estimate    REAL,
    pct_change      REAL,
    direction       TEXT,       -- upgrade / downgrade / maintained
    fetched_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trendlyne_promoter_pledging (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    event_date      TEXT,
    event_type      TEXT,       -- pledge_created / pledge_released / pledge_invoked
    shares_pledged  INTEGER,
    pct_of_total    REAL,
    cumulative_pledge_pct REAL,
    fetched_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trendlyne_analyst_targets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    analyst_house   TEXT,
    report_date     TEXT,
    recommendation  TEXT,       -- BUY / SELL / HOLD / NEUTRAL
    target_price    REAL,
    current_price_at_report REAL,
    upside_pct      REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, analyst_house, report_date)
);

-- ─────────────────────────────────────────────
-- SOURCE 3: TICKERTAPE / TIJORI  (Secondary)
-- Segment revenue, subsidiary financials, capex tracking
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tickertape_segments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    fiscal_year     INTEGER,
    period_end      TEXT,
    segment_name    TEXT,
    revenue_cr      REAL,
    revenue_pct     REAL,
    ebit_cr         REAL,
    ebit_margin_pct REAL,
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, period_end, segment_name)
);

CREATE TABLE IF NOT EXISTS tickertape_subsidiaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    subsidiary_name TEXT,
    stake_pct       REAL,
    fiscal_year     INTEGER,
    revenue_cr      REAL,
    pat_cr          REAL,
    net_worth_cr    REAL,
    fetched_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tickertape_capex (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    fiscal_year     INTEGER,
    period_end      TEXT,
    announced_capex_cr REAL,
    spent_ytd_cr    REAL,
    completion_pct  REAL,
    project_desc    TEXT,
    fetched_at      TEXT DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────
-- SOURCE 4: BROKER RESEARCH PORTALS  (Secondary)
-- Kotak, Motilal, IIFL, Nuvama — initiation reports, rating changes
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS broker_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    broker          TEXT,       -- Kotak / Motilal / IIFL / Nuvama / etc.
    report_date     TEXT,
    report_type     TEXT,       -- initiation / rating_change / quarterly_update / sector_note
    recommendation  TEXT,
    target_price    REAL,
    prev_recommendation TEXT,
    prev_target     REAL,
    key_thesis      TEXT,       -- brief summary
    report_url      TEXT,
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, broker, report_date, report_type)
);

-- ─────────────────────────────────────────────
-- SOURCE 5: CMIE PROWESS  (Primary)
-- Historical financials, industry benchmarking, capex going back 30 years
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cmie_historical_financials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    fiscal_year     INTEGER,
    revenue_cr      REAL,
    ebitda_cr       REAL,
    pat_cr          REAL,
    total_assets_cr REAL,
    debt_cr         REAL,
    capex_cr        REAL,
    employees       INTEGER,
    data_source     TEXT DEFAULT 'CMIE',
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, fiscal_year)
);

CREATE TABLE IF NOT EXISTS cmie_industry_benchmarks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    industry        TEXT NOT NULL,
    fiscal_year     INTEGER,
    metric          TEXT,       -- ROCE / Debt-Equity / Asset-Turnover / etc.
    industry_median REAL,
    industry_mean   REAL,
    top_quartile    REAL,
    bottom_quartile REAL,
    sample_size     INTEGER,
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(industry, fiscal_year, metric)
);

-- ─────────────────────────────────────────────
-- SOURCE 6: DION GLOBAL / ACEEQUITY  (Secondary)
-- Corporate actions, rights/bonus/split history, AGM outcomes
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS corporate_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    action_type     TEXT,       -- dividend / bonus / split / rights / buyback / agm
    ex_date         TEXT,
    record_date     TEXT,
    announcement_date TEXT,
    details         TEXT,       -- JSON blob for type-specific fields
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, action_type, ex_date)
);

CREATE TABLE IF NOT EXISTS agm_outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    agm_date        TEXT,
    resolution_type TEXT,       -- dividend / director_appointment / auditor / capex_approval
    resolution_desc TEXT,
    result          TEXT,       -- passed / rejected / withdrawn
    votes_for_pct   REAL,
    votes_against_pct REAL,
    fetched_at      TEXT DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────
-- SOURCE 7: CONCALL TRANSCRIPTS  (Signal)
-- Management tone analysis — NLP-driven sentiment shift vs prior quarter
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS concall_transcripts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    call_date       TEXT,
    fiscal_period   TEXT,       -- Q1FY26 etc.
    transcript_text TEXT,
    transcript_url  TEXT,
    word_count      INTEGER,
    fetched_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, call_date)
);

CREATE TABLE IF NOT EXISTS concall_nlp_analysis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    transcript_id   INTEGER REFERENCES concall_transcripts(id),
    ticker          TEXT NOT NULL,
    fiscal_period   TEXT,
    sentiment_score REAL,       -- -1.0 to +1.0
    sentiment_label TEXT,       -- positive / neutral / negative
    prev_period_score REAL,
    score_delta     REAL,
    key_topics      TEXT,       -- JSON list
    mgmt_confidence_score REAL,
    guidance_tone   TEXT,       -- bullish / cautious / neutral
    red_flags       TEXT,       -- JSON list of flagged phrases
    positive_signals TEXT,      -- JSON list
    analysed_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, fiscal_period)
);

-- ─────────────────────────────────────────────
-- AGGREGATED RESEARCH OUTPUT (feeds into decision model)
-- ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS research_summary (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    generated_at    TEXT DEFAULT (datetime('now')),
    -- Valuation signals
    pe_ratio        REAL,
    pb_ratio        REAL,
    ev_ebitda       REAL,
    sector_pe       REAL,
    pe_discount_pct REAL,       -- vs sector median
    -- Quality signals
    roce_5yr_avg    REAL,
    roe_5yr_avg     REAL,
    debt_equity     REAL,
    ocf_pat_ratio   REAL,       -- OCF / PAT — earnings quality
    -- Growth signals
    revenue_cagr_3y REAL,
    pat_cagr_3y     REAL,
    eps_revision_6m TEXT,       -- upgrade / downgrade / stable
    -- Ownership signals
    promoter_pledge_pct REAL,
    fii_change_qoq  REAL,
    -- Sentiment signals
    consensus_recommendation TEXT,
    analyst_count   INTEGER,
    concall_sentiment TEXT,
    sentiment_shift TEXT,       -- improved / deteriorated / stable
    -- Composite score (0-100)
    research_score  REAL,
    score_components TEXT       -- JSON breakdown
);

-- Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_screener_fin_ticker ON screener_financials(ticker, period_end);
CREATE INDEX IF NOT EXISTS idx_broker_ticker ON broker_reports(ticker, report_date);
CREATE INDEX IF NOT EXISTS idx_concall_ticker ON concall_transcripts(ticker, call_date);
CREATE INDEX IF NOT EXISTS idx_watchlist_active ON watchlist(is_active);
CREATE INDEX IF NOT EXISTS idx_corp_actions_ticker ON corporate_actions(ticker, ex_date);
"""

def init_db(db_path=None):
    """Initialize the database with all tables."""
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    print(f"✅ Database initialized at: {path}")
    return path

if __name__ == '__main__':
    init_db()
