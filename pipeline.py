"""
pipeline.py — Master pipeline: collects, classifies and dispatches all layers.
Called by the scheduler on every tick.
"""
import logging
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from config import MEDIA_DB_PATH
from db import get_media_conn

logger = logging.getLogger("pipeline")


# ── Layer 1: Collect ─────────────────────────────────────────────────────────

def run_layer1_collect(conn) -> dict:
    """Run all data collectors (media, insider, credit)."""
    results = {}

    # Media / News RSS
    try:
        from collectors.media_collector import collect_all
        results["media"] = collect_all(conn)
    except Exception as e:
        logger.error("media_collector: %s", e); results["media"] = 0

    # Insider signals (SEBI SAST, pledge, QIB, RPT, director, AGM)
    try:
        from collectors.insider_collector import collect_all_insider
        from db.insider_schema import extend_db
        extend_db(conn)
        r = collect_all_insider(conn)
        results["insider"] = sum(r.values())
    except Exception as e:
        logger.error("insider_collector: %s", e); results["insider"] = 0

    # Credit & debt markets
    try:
        from collectors.credit_collector import collect_all_credit
        from db.credit_schema import extend_db_credit
        extend_db_credit(conn)
        r = collect_all_credit(conn)
        results["credit"] = sum(r.values())
    except Exception as e:
        logger.error("credit_collector: %s", e); results["credit"] = 0

    # Regulatory (NSE/BSE corp announcements, RBI RSS, news RSS)
    try:
        from collectors.regulatory_collector import run_collectors
        import sqlite3 as _sq
        _conn_reg = _sq.connect(
            os.path.join(os.path.dirname(__file__), "db", "regulatory_intel.db")
        )
        _conn_reg.row_factory = _sq.Row
        _conn_reg.execute("PRAGMA journal_mode=WAL")
        r = run_collectors(demo_mode=False)
        results["regulatory"] = sum(v for v in r.values() if isinstance(v, int))
        _conn_reg.close()
    except Exception as e:
        logger.error("regulatory_collector: %s", e); results["regulatory"] = 0

    logger.info("[Layer1] collected: %s", results)
    return results


# ── Layer 2: Classify / Score ─────────────────────────────────────────────────

def run_layer2_classify(conn) -> dict:
    """Run all classifiers on unprocessed records."""
    results = {}

    # Media events → alerts
    try:
        from processors.media_classifier import classify_unprocessed
        results["media_alerts"] = classify_unprocessed(conn)
    except Exception as e:
        logger.error("media_classifier: %s", e); results["media_alerts"] = 0

    # Insider signals → insider_alerts
    try:
        from processors.insider_classifier import classify_all_insider
        r = classify_all_insider(conn)
        results["insider_alerts"] = sum(r.values())
    except Exception as e:
        logger.error("insider_classifier: %s", e); results["insider_alerts"] = 0

    # Credit signals → credit_alerts
    try:
        from processors.credit_classifier import classify_all_credit
        r = classify_all_credit(conn)
        results["credit_alerts"] = sum(r.values())
    except Exception as e:
        logger.error("credit_classifier: %s", e); results["credit_alerts"] = 0

    # Regulatory events → signals (in regulatory DB)
    try:
        from processors.regulatory_classifier import classify_unprocessed as reg_classify
        results["regulatory_signals"] = reg_classify(use_ai=False)
    except Exception as e:
        logger.error("regulatory_classifier: %s", e); results["regulatory_signals"] = 0

    logger.info("[Layer2] classified: %s", results)
    return results


# ── Layer 3: Deliver ──────────────────────────────────────────────────────────

def run_layer3_deliver(conn, intraday: bool = True) -> dict:
    """Dispatch alerts via Telegram, WhatsApp, email."""
    results = {}

    # Telegram
    try:
        from delivery.telegram_bot import (fire_pending_tg_alerts,
                                            fire_pending_insider_tg,
                                            fire_pending_credit_tg)
        tg = (fire_pending_tg_alerts(conn)
              + fire_pending_insider_tg(conn)
              + fire_pending_credit_tg(conn))
        results["telegram"] = tg
    except Exception as e:
        logger.error("telegram: %s", e); results["telegram"] = 0

    # WhatsApp (CRITICAL only)
    try:
        from delivery.whatsapp import fire_critical_whatsapp
        results["whatsapp"] = fire_critical_whatsapp(conn)
    except Exception as e:
        logger.error("whatsapp: %s", e); results["whatsapp"] = 0

    logger.info("[Layer3] delivered: %s", results)
    return results


def run_full_pipeline(conn, intraday: bool = True) -> dict:
    """One full L1→L2→L3 cycle."""
    l1 = run_layer1_collect(conn)
    l2 = run_layer2_classify(conn)
    l3 = run_layer3_deliver(conn, intraday=intraday)
    return {"collected": l1, "classified": l2, "delivered": l3}


def run_morning_digest(conn) -> str:
    """Generate all digest variants and email them."""
    from datetime import datetime, timezone, timedelta
    ist_date = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")

    # Media digest
    try:
        from processors.morning_digest import generate_digest
        path = generate_digest(conn, for_date=ist_date)
        logger.info("[Digest] media → %s", path)
        # Email it
        with open(path, encoding="utf-8") as f:
            html = f.read()
        from delivery.email_digest import send_html_email
        send_html_email(f"📰 Media Intelligence Digest — {ist_date}", html)
        # Telegram summary
        row = conn.execute(
            "SELECT item_count FROM digest_history ORDER BY sent_at DESC LIMIT 1"
        ).fetchone()
        if row:
            from delivery.telegram_bot import send_digest_summary
            counts = {s: conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE severity=?", (s,)
            ).fetchone()[0] for s in ("CRITICAL","HIGH","MEDIUM","LOW")}
            send_digest_summary(ist_date, counts)
    except Exception as e:
        logger.error("morning_digest: %s", e)
        path = ""

    return path
