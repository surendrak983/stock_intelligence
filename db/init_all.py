"""
db/init_all.py — Master DB initializer
Creates and migrates all three databases (media, regulatory, research)
in a single call: `python -m db.init_all`
"""

import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import (
    DB_MEDIA, DB_REGULATORY, DB_RESEARCH,
    DEFAULT_WATCHLIST, BASE_DIR
)


# ─────────────────────────────────────────────────────────────────────────────
# 1.  MEDIA DB  (events, alerts, insider signals, credit signals)
# ─────────────────────────────────────────────────────────────────────────────

def init_media_db() -> sqlite3.Connection:
    """
    Initialise media_intel.db:
    Phase 1 schema (media events + alerts)
    + Phase 2 schema (insider signals)
    + Phase 3 schema (credit signals)
    """
    from db.media_schema   import init_db    as _base
    from db.insider_schema import extend_db  as _insider
    from db.credit_schema  import extend_db_credit as _credit

    conn = _base(str(DB_MEDIA))
    _insider(conn)
    _credit(conn)

    # Seed default watchlist_config if empty
    n = conn.execute("SELECT COUNT(*) FROM watchlist_config").fetchone()[0]
    if n == 0:
        seeds = [
            (t, None, "HIGH") for t, *_ in DEFAULT_WATCHLIST
        ] + [
            (None, kw, sev) for kw, sev in [
                ("RBI",           "CRITICAL"),
                ("SEBI",          "CRITICAL"),
                ("NCLT",          "CRITICAL"),
                ("FPI",           "HIGH"),
                ("interest rate", "HIGH"),
                ("earnings",      "MEDIUM"),
                ("pledge",        "HIGH"),
                ("insider",       "HIGH"),
            ]
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO watchlist_config(ticker, keyword, threshold) VALUES(?,?,?)",
            seeds,
        )
        conn.commit()

    print(f"[DB] media_intel.db → OK  ({DB_MEDIA})")
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# 2.  REGULATORY DB  (26 source registry, SEBI/NCLT/MCA/RBI/CCI etc.)
# ─────────────────────────────────────────────────────────────────────────────

def init_regulatory_db() -> sqlite3.Connection:
    """
    Initialise regulatory_intel.db using roh1/db.py schema.
    Also seeds the watchlist from DEFAULT_WATCHLIST.
    """
    # Temporarily adjust DB_PATH used by the module
    import db.regulatory_schema as reg_mod
    orig = reg_mod.DB_PATH
    reg_mod.DB_PATH = str(DB_REGULATORY)
    reg_mod.init_db()
    reg_mod.DB_PATH = orig

    conn = sqlite3.connect(str(DB_REGULATORY), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Seed watchlist
    for ticker, company, sector, priority in DEFAULT_WATCHLIST:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist(ticker, company, sector, priority) VALUES(?,?,?,?)",
            (ticker, company, sector, priority),
        )
    conn.commit()
    print(f"[DB] regulatory_intel.db → OK  ({DB_REGULATORY})")
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# 3.  RESEARCH DB  (Screener, Trendlyne, concalls, broker reports)
# ─────────────────────────────────────────────────────────────────────────────

def init_research_db() -> sqlite3.Connection:
    """Initialise equity_research.db using sum2 schema."""
    import db.research_schema as res_mod
    orig = res_mod.DB_PATH
    res_mod.DB_PATH = str(DB_RESEARCH)
    res_mod.init_db(str(DB_RESEARCH))
    res_mod.DB_PATH = orig

    conn = sqlite3.connect(str(DB_RESEARCH))
    conn.row_factory = sqlite3.Row

    # Seed watchlist
    for ticker, company, sector, _ in DEFAULT_WATCHLIST:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist(ticker, company_name, sector) VALUES(?,?,?)",
            (ticker, company, sector),
        )
    conn.commit()
    print(f"[DB] equity_research.db  → OK  ({DB_RESEARCH})")
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Master init
# ─────────────────────────────────────────────────────────────────────────────

def init_all() -> dict:
    """Initialise all three databases. Returns dict of open connections."""
    print("\n[DB] Initialising all databases…")
    return {
        "media":      init_media_db(),
        "regulatory": init_regulatory_db(),
        "research":   init_research_db(),
    }


def status_all():
    """Print row counts from all key tables."""
    conns = init_all()

    print("\n══════════ DATABASE STATUS ══════════")

    media_tables = [
        "events", "alerts", "insider_trades", "pledge_tracker",
        "qib_allotments", "related_party_txns", "director_checks",
        "agm_egm_outcomes", "insider_alerts",
        "credit_ratings", "cp_issuances", "cersai_charges",
        "ccil_derivatives", "rbi_credit_data", "credit_alerts",
        "digest_history", "watchlist_config",
    ]
    print("\n  ── Media DB ──")
    for t in media_tables:
        try:
            n = conns["media"].execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"    {t:<30} {n:>6} rows")
        except Exception:
            pass

    reg_tables = [
        "raw_events", "classified_events", "signals", "watchlist",
        "sebi_disclosures", "mca_filings", "insolvency_tracker",
        "cci_orders", "credit_ratings", "promoter_pledges",
        "rbi_circulars", "irdai_filings", "trade_signals",
        "source_config", "digest_history",
    ]
    print("\n  ── Regulatory DB ──")
    for t in reg_tables:
        try:
            n = conns["regulatory"].execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"    {t:<30} {n:>6} rows")
        except Exception:
            pass

    res_tables = [
        "watchlist", "screener_financials", "screener_shareholding",
        "trendlyne_estimate_revisions", "trendlyne_analyst_targets",
        "broker_reports", "concall_transcripts", "concall_nlp_analysis",
        "corporate_actions", "research_summary",
    ]
    print("\n  ── Research DB ──")
    for t in res_tables:
        try:
            n = conns["research"].execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"    {t:<30} {n:>6} rows")
        except Exception:
            pass

    print()
    for c in conns.values():
        c.close()


if __name__ == "__main__":
    status_all()
