"""
db/__init__.py — Unified DB initialiser
Brings up all three databases: media_intel, regulatory_intel, equity_research.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import sqlite3
from config import MEDIA_DB_PATH, REGULATORY_DB_PATH, RESEARCH_DB_PATH

# ── Import all DDL functions ──────────────────────────────────────────────────
from db.media_schema    import init_db        as _init_media
from db.insider_schema  import extend_db      as _extend_insider
from db.credit_schema   import extend_db_credit as _extend_credit


def init_all_dbs():
    """Initialise / upgrade all databases. Safe to call repeatedly."""
    # 1. Media DB (media events, alerts, digest history, watchlist)
    media_conn = _init_media(MEDIA_DB_PATH)
    _extend_insider(media_conn)      # insider tables
    _extend_credit(media_conn)       # credit tables
    media_conn.commit()

    # 2. Regulatory DB (raw_events, classified_events, signals, domain tables)
    from db.regulatory_schema import init_db as _init_reg
    _init_reg()

    # 3. Equity research DB
    from equity_research.database.schema import init_db as _init_research
    _init_research()

    print("[DB] All databases initialised.")
    return media_conn


def get_media_conn():
    conn = sqlite3.connect(MEDIA_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
