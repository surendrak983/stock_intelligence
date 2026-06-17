"""
db.py — SQLite schema v2  (Regulatory tab — complete)
New tables vs v1:
  + promoter_pledges      dedicated pledge tracking
  + shareholding_patterns SHP quarterly snapshots
  + bulk_block_deals      bulk/block deal registry
  + credit_ratings        full rating history per issuer
  + insolvency_tracker    NCLT/NCLAT case lifecycle
  + regulatory_orders     SEBI/CCI/IRDAI penalty orders
"""

import sqlite3, os
import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.dirname(__file__))); DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "regulatory_intel.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
    -- ── core tables (unchanged from v1) ─────────────────────────────────────
    CREATE TABLE IF NOT EXISTS raw_events (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        source       TEXT NOT NULL,
        source_type  TEXT NOT NULL,
        category     TEXT NOT NULL,
        sub_category TEXT,
        ticker       TEXT,
        company      TEXT,
        title        TEXT NOT NULL,
        body         TEXT,
        url          TEXT,
        event_hash   TEXT UNIQUE,
        published_at TIMESTAMP,
        fetched_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        raw_json     TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_re_ticker  ON raw_events(ticker);
    CREATE INDEX IF NOT EXISTS idx_re_source  ON raw_events(source);
    CREATE INDEX IF NOT EXISTS idx_re_pub     ON raw_events(published_at);
    CREATE INDEX IF NOT EXISTS idx_re_subcat  ON raw_events(sub_category);

    CREATE TABLE IF NOT EXISTS classified_events (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id     INTEGER REFERENCES raw_events(id),
        ticker           TEXT,
        company          TEXT,
        event_type       TEXT,
        severity         TEXT,
        severity_score   INTEGER,
        signal_direction TEXT,
        keywords         TEXT,
        summary          TEXT,
        classified_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ai_enriched      INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_ce_ticker   ON classified_events(ticker);
    CREATE INDEX IF NOT EXISTS idx_ce_severity ON classified_events(severity);

    CREATE TABLE IF NOT EXISTS signals (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker           TEXT NOT NULL,
        signal_type      TEXT NOT NULL,
        direction        TEXT NOT NULL,
        confidence       REAL,
        severity         TEXT,
        source_event_id  INTEGER REFERENCES classified_events(id),
        rationale        TEXT,
        valid_from       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        valid_until      TIMESTAMP,
        consumed         INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_sig_ticker   ON signals(ticker);
    CREATE INDEX IF NOT EXISTS idx_sig_consumed ON signals(consumed);

    CREATE TABLE IF NOT EXISTS watchlist (
        ticker    TEXT PRIMARY KEY,
        company   TEXT,
        sector    TEXT,
        priority  INTEGER DEFAULT 1,
        added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS digest_history (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        digest_date    TEXT NOT NULL,
        content        TEXT,
        events_count   INTEGER,
        critical_count INTEGER,
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- ── NEW: Regulatory sub-domain tables ───────────────────────────────────

    -- SEBI EDGAR: SAST / insider / creeping acquisition
    CREATE TABLE IF NOT EXISTS sebi_disclosures (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id INTEGER REFERENCES raw_events(id),
        ticker       TEXT,
        company      TEXT,
        disclosure_type TEXT,   -- SAST_7_2 | SAST_29 | PIT_INSIDER | CREEPING
        acquirer     TEXT,
        acquirer_type TEXT,     -- PROMOTER | FPI | DII | INDIVIDUAL | ENTITY
        pre_holding  REAL,      -- % before
        acquired_pct REAL,      -- % acquired / disposed
        post_holding REAL,      -- % after
        transaction_type TEXT,  -- BUY | SELL | PLEDGE
        amount_cr    REAL,
        exchange     TEXT,
        disclosed_on DATE,
        filing_hash  TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_sd_ticker ON sebi_disclosures(ticker);
    CREATE INDEX IF NOT EXISTS idx_sd_dtype  ON sebi_disclosures(disclosure_type);

    -- MCA / ROC: corporate filings
    CREATE TABLE IF NOT EXISTS mca_filings (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id INTEGER REFERENCES raw_events(id),
        cin          TEXT,      -- Corporate Identification Number
        company      TEXT,
        ticker       TEXT,
        form_type    TEXT,      -- MGT-14 | CHG-1 | DIR-12 | AOC-4 | MGT-7
        description  TEXT,
        charge_amount REAL,     -- for CHG forms
        charge_holder TEXT,
        event_date   DATE,
        filing_hash  TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_mca_ticker    ON mca_filings(ticker);
    CREATE INDEX IF NOT EXISTS idx_mca_form      ON mca_filings(form_type);

    -- NCLT / NCLAT: insolvency case tracker
    CREATE TABLE IF NOT EXISTS insolvency_tracker (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id    INTEGER REFERENCES raw_events(id),
        ticker          TEXT,
        company         TEXT,
        case_number     TEXT UNIQUE,
        bench           TEXT,   -- NCLT Mumbai | NCLT Delhi | NCLAT etc.
        petitioner      TEXT,
        petitioner_type TEXT,   -- FINANCIAL_CREDITOR | OPERATIONAL_CREDITOR | COMPANY
        stage           TEXT,   -- ADMITTED | RESOLUTION | LIQUIDATION | WITHDRAWN | CLOSED
        insolvency_date DATE,
        resolution_professional TEXT,
        claim_amount_cr REAL,
        last_updated    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_ins_ticker ON insolvency_tracker(ticker);
    CREATE INDEX IF NOT EXISTS idx_ins_stage  ON insolvency_tracker(stage);

    -- CCI filings: M&A combination orders
    CREATE TABLE IF NOT EXISTS cci_orders (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id   INTEGER REFERENCES raw_events(id),
        case_number    TEXT UNIQUE,
        acquirer       TEXT,
        target         TEXT,
        target_ticker  TEXT,
        order_type     TEXT,    -- APPROVAL | CONDITIONAL | REJECTION | NOTICE
        combination_type TEXT,  -- MERGER | ACQUISITION | AMALGAMATION | JV
        sector         TEXT,
        order_date     DATE,
        conditions     TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_cci_target ON cci_orders(target_ticker);

    -- CRISIL / ICRA / CARE / India Ratings: full rating history
    CREATE TABLE IF NOT EXISTS credit_ratings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id    INTEGER REFERENCES raw_events(id),
        ticker          TEXT,
        company         TEXT,
        agency          TEXT,   -- CRISIL | ICRA | CARE | INDRA | FITCH | MOODY
        instrument      TEXT,   -- NCD | CP | BANK_LOAN | BOND | TERM_LOAN
        rating          TEXT,   -- AAA | AA+ | ... | D
        rating_prev     TEXT,
        outlook         TEXT,   -- STABLE | POSITIVE | NEGATIVE | WATCH
        outlook_prev    TEXT,
        action          TEXT,   -- UPGRADE | DOWNGRADE | REAFFIRM | WATCH | WITHDRAWN
        amount_cr       REAL,
        rating_date     DATE,
        rationale       TEXT,
        filing_hash     TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_cr_ticker ON credit_ratings(ticker);
    CREATE INDEX IF NOT EXISTS idx_cr_action ON credit_ratings(action);

    -- Promoter pledges (BSE/NSE dedicated pledge disclosures)
    CREATE TABLE IF NOT EXISTS promoter_pledges (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id    INTEGER REFERENCES raw_events(id),
        ticker          TEXT,
        company         TEXT,
        promoter_name   TEXT,
        event_type      TEXT,   -- CREATION | INVOCATION | RELEASE | INCREASE
        shares_pledged  REAL,
        pledge_pct_total REAL,  -- % of total share capital
        pledge_pct_promo REAL,  -- % of promoter holding
        lender          TEXT,
        pledge_date     DATE,
        filing_hash     TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_pp_ticker ON promoter_pledges(ticker);
    CREATE INDEX IF NOT EXISTS idx_pp_type   ON promoter_pledges(event_type);

    -- RBI database: banking & NBFC regulatory
    CREATE TABLE IF NOT EXISTS rbi_circulars (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id    INTEGER REFERENCES raw_events(id),
        circular_number TEXT UNIQUE,
        category        TEXT,   -- MONETARY_POLICY | BANKING_REG | NBFC | FPI_FDI | FOREX
        subject         TEXT,
        impact_sectors  TEXT,   -- comma-separated
        issued_date     DATE,
        effective_date  DATE,
        key_changes     TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_rbi_cat ON rbi_circulars(category);

    -- IRDAI / PFRDA: insurance/pension regulatory
    CREATE TABLE IF NOT EXISTS irdai_filings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id    INTEGER REFERENCES raw_events(id),
        ticker          TEXT,
        company         TEXT,
        filing_type     TEXT,   -- INVESTMENT_DISCLOSURE | SOLVENCY | PENALTY | CIRCULAR
        regulator       TEXT,   -- IRDAI | PFRDA
        period          TEXT,
        aum_cr          REAL,
        solvency_ratio  REAL,
        filing_date     DATE,
        filing_hash     TEXT UNIQUE
    );

    -- Customs & DGFT: trade signals
    CREATE TABLE IF NOT EXISTS trade_signals (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id    INTEGER REFERENCES raw_events(id),
        ticker          TEXT,
        company         TEXT,
        signal_type     TEXT,   -- ANTI_DUMPING | IMPORT_LICENCE | EXPORT_LICENCE | SAFEGUARD
        product         TEXT,
        country         TEXT,
        duty_pct        REAL,
        direction       TEXT,   -- IMPORT | EXPORT
        effective_date  DATE,
        notification_no TEXT,
        filing_hash     TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_ts_ticker ON trade_signals(ticker);

    -- CERSAI / CCIL: securitisation & derivatives
    CREATE TABLE IF NOT EXISTS securitisation_registry (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id    INTEGER REFERENCES raw_events(id),
        ticker          TEXT,
        company         TEXT,
        registration_type TEXT, -- CHARGE_CREATION | CHARGE_SATISFACTION | SECURITISATION
        asset_class     TEXT,
        amount_cr       REAL,
        secured_creditor TEXT,
        registration_date DATE,
        filing_hash     TEXT UNIQUE
    );

    -- NSE bond / CP platform: debt issuances
    CREATE TABLE IF NOT EXISTS debt_issuances (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_event_id    INTEGER REFERENCES raw_events(id),
        ticker          TEXT,
        company         TEXT,
        instrument      TEXT,   -- NCD | CP | BOND | MLDL
        isin            TEXT UNIQUE,
        coupon_pct      REAL,
        maturity_date   DATE,
        issue_size_cr   REAL,
        credit_rating   TEXT,
        issued_date     DATE,
        yield_pct       REAL
    );
    CREATE INDEX IF NOT EXISTS idx_di_ticker ON debt_issuances(ticker);

    -- Source config
    CREATE TABLE IF NOT EXISTS source_config (
        source_id    TEXT PRIMARY KEY,
        label        TEXT,
        source_type  TEXT,
        category     TEXT,
        sub_category TEXT,
        url          TEXT,
        parser_type  TEXT,   -- RSS | JSON_API | HTML_SCRAPE | PDF | MANUAL
        enabled      INTEGER DEFAULT 1,
        last_fetched TIMESTAMP,
        fetch_notes  TEXT    -- access notes / auth requirements
    );
    """)
    conn.commit()

    # ── Seed complete source registry ────────────────────────────────────────
    sources = [
        # ── Regulatory & statutory filings ──────────────────────────────────
        ("SEBI_EDGAR",  "SEBI EDGAR",             "PRIMARY",   "regulatory", "insider_sast",
         "https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doRecognisedFca=yes",
         "HTML_SCRAPE", "Requires session cookie in prod; use Selenium or Playwright"),
        ("SEBI_ORDERS", "SEBI Enforcement Orders", "PRIMARY",  "regulatory", "penalty_orders",
         "https://www.sebi.gov.in/enforcement/orders/",
         "HTML_SCRAPE", "Paginated HTML; scrape order date, entity, penalty amount"),
        ("MCA_ROC",    "MCA21 / ROC Portal",       "PRIMARY",  "regulatory", "corporate_filings",
         "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html",
         "JSON_API",   "MCA v3 API available; needs registration for bulk access"),
        ("MCA_CHARGE", "MCA Charge Registry",      "PRIMARY",  "regulatory", "charge_creation",
         "https://www.mca.gov.in/mcafoportal/viewChargeMaster.do",
         "JSON_API",   "Form CHG-1/CHG-4/CHG-9; available via MCA data services"),
        ("RBI_MASTER", "RBI Master Directions",    "PRIMARY",  "regulatory", "banking_reg",
         "https://rbi.org.in/Scripts/Rss.aspx",
         "RSS",        "Open RSS; no auth needed; covers monetary policy + circulars"),
        ("RBI_PRESS",  "RBI Press Releases",       "PRIMARY",  "regulatory", "monetary_policy",
         "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
         "RSS",        "MPC decisions, repo rate, CRR changes"),
        ("IRDAI_DISC", "IRDAI Investment Disclosures","PRIMARY","regulatory","insurance_reg",
         "https://irdai.gov.in/web/guest/home",
         "HTML_SCRAPE","Quarterly investment + solvency disclosures for listed insurers"),
        ("PFRDA_DISC", "PFRDA NPS Disclosures",   "PRIMARY",  "regulatory", "pension_reg",
         "https://www.pfrda.org.in/",
         "HTML_SCRAPE","Pension fund investment in listed equities — quarterly"),
        ("CCI_ORDERS", "CCI Combination Orders",   "PRIMARY",  "regulatory", "merger_approval",
         "https://www.cci.gov.in/combination-orders",
         "HTML_SCRAPE","All M&A combination approvals/rejections; PDF download per order"),
        ("NCLT_ORDERS","NCLT Case Registry",       "PRIMARY",  "regulatory", "insolvency",
         "https://nclt.gov.in/",
         "HTML_SCRAPE","IBC cases by company name/CIN; bench-wise daily cause list"),
        ("NCLAT",      "NCLAT Appeal Orders",      "PRIMARY",  "regulatory", "insolvency_appeal",
         "https://nclat.nic.in/",
         "HTML_SCRAPE","Appeals against NCLT orders; order PDFs available"),
        ("DGFT_NOTIF", "DGFT Trade Notifications", "SECONDARY","regulatory","trade_policy",
         "https://www.dgft.gov.in/CP/",
         "HTML_SCRAPE","Import/export policy, FTP notifications, anti-dumping"),
        ("CUSTOMS_NOTIF","Customs Anti-Dumping",   "SECONDARY","regulatory","anti_dumping",
         "https://www.cbic.gov.in/",
         "HTML_SCRAPE","CBIC notifications for ADD/CVD duties; sector-specific impact"),
        # ── Credit & debt markets ────────────────────────────────────────────
        ("CRISIL_RAT",  "CRISIL Ratings",          "PRIMARY",  "credit",    "rating_action",
         "https://www.crisil.com/en/home/our-businesses/ratings/credit-ratings-news.html",
         "HTML_SCRAPE","Rating actions RSS-style; upgrade/downgrade/reaffirm + outlook"),
        ("ICRA_RAT",    "ICRA Ratings",            "PRIMARY",  "credit",    "rating_action",
         "https://www.icra.in/Rationale/Index/",
         "HTML_SCRAPE","Rationale PDFs + action type; maps to NSE ticker via company name"),
        ("CARE_RAT",    "CARE Ratings",            "PRIMARY",  "credit",    "rating_action",
         "https://www.careratings.com/",
         "HTML_SCRAPE","Press release feed; structured XML available to subscribers"),
        ("INDRA_RAT",   "India Ratings (Fitch)",   "PRIMARY",  "credit",    "rating_action",
         "https://www.indiaratings.co.in/",
         "HTML_SCRAPE","India Ratings — Fitch group; NBFC / infra sector focus"),
        ("NSE_BOND",    "NSE Bond / CP Platform",  "PRIMARY",  "credit",    "debt_issuance",
         "https://www.nseindia.com/market-data/bonds-trading-information",
         "JSON_API",   "CP issuance rate vs peer; real-time via NSE API (requires session)"),
        ("BSE_BOND",    "BSE Bond Platform",       "PRIMARY",  "credit",    "debt_issuance",
         "https://www.bsebond.com/",
         "JSON_API",   "NCD / bond listings; ISIN-level data"),
        ("CERSAI_REG",  "CERSAI Registry",         "PRIMARY",  "credit",    "securitisation",
         "https://www.cersai.org.in/CERSAI/home.prg",
         "JSON_API",   "Charge creation/satisfaction API — needs CERSAI subscriber login"),
        ("CCIL_REPO",   "CCIL Trade Repository",   "SECONDARY","credit",    "otc_derivatives",
         "https://www.ccilindia.com/web/ccil/tri",
         "JSON_API",   "OTC bond + forex derivatives; corporate hedging pattern changes"),
        ("RBI_CREDIT",  "RBI Sectoral Bank Credit","SECONDARY","credit",    "bank_credit",
         "https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
         "RSS",        "Monthly sectoral credit data; NPA surfacing signal by industry"),
        # ── NSE / BSE corporate announcements (supports both sections) ───────
        ("NSE_CORP",   "NSE Corporate Announcements","PRIMARY","regulatory","corp_announcement",
         "https://www.nseindia.com/api/corporate-announcements?index=equities",
         "JSON_API",   "Real-time; requires NSE session cookie (set via /api/home first)"),
        ("BSE_CORP",   "BSE Corporate Announcements","PRIMARY","regulatory","corp_announcement",
         "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
         "JSON_API",   "Requires BSE Referer header; rate-limited to ~60 req/min"),
        ("NSE_PLEDGE", "NSE Promoter Pledge Data", "PRIMARY",  "regulatory","insider_pledge",
         "https://www.nseindia.com/api/corporates-pledgedata",
         "JSON_API",   "Pledge creation/invocation/release by promoter; requires session"),
        ("BSE_SHP",    "BSE Shareholding Patterns","PRIMARY",  "regulatory","shareholding",
         "https://www.bseindia.com/corporates/shpIndividual.html",
         "HTML_SCRAPE","Quarterly SHP; promoter/FPI/DII/public holding changes"),
    ]

    c.executemany("""
        INSERT OR IGNORE INTO source_config
            (source_id,label,source_type,category,sub_category,url,parser_type,enabled,fetch_notes)
        VALUES (?,?,?,?,?,?,?,1,?)
    """, sources)
    conn.commit()
    conn.close()
    print(f"[DB v2] Initialised → {DB_PATH}  ({len(sources)} sources registered)")

if __name__ == "__main__":
    init_db()
