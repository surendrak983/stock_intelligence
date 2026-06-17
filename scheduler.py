"""
scheduler.py — Three-tier cron loop (IST-aware)
  1. collect_and_alert  every 15 min   09:15–15:30 IST  (market hours)
  2. overnight_scan     every 60 min   15:30–09:00 IST
  3. morning_digest     once daily at  07:50 IST

Run:  python scheduler.py
      python scheduler.py --run-once      (test: all three jobs once)
      python scheduler.py --demo          (inject demo data first)
"""
import argparse, logging, os, sys, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))

from config import (INTRADAY_INTERVAL_MIN, OVERNIGHT_INTERVAL_MIN,
                    DIGEST_TIME_IST, MARKET_OPEN, MARKET_CLOSE)
from db import get_media_conn, init_all_dbs
from pipeline import run_full_pipeline, run_morning_digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "logs", "scheduler.log")),
    ],
)
logger = logging.getLogger("scheduler")


def _ist_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

def _hm(dt: datetime) -> tuple:
    return dt.hour, dt.minute

def _in_market(hm: tuple) -> bool:
    return MARKET_OPEN <= hm <= MARKET_CLOSE


def run_scheduler(run_once: bool = False, demo: bool = False):
    init_all_dbs()
    conn = get_media_conn()
    logger.info("=== Stock Intelligence Scheduler STARTED ===")

    if demo:
        _inject_demo(conn)

    if run_once:
        logger.info("=== RUN-ONCE MODE ===")
        res = run_full_pipeline(conn, intraday=True)
        logger.info("Pipeline result: %s", res)
        run_morning_digest(conn)
        conn.close()
        return

    last_intraday  = None
    last_overnight = None
    last_digest    = None

    while True:
        now_ist = _ist_now()
        hm      = _hm(now_ist)
        day     = now_ist.strftime("%Y-%m-%d")

        # ── collect + alert every 15 min during market hours ─────────────
        if _in_market(hm):
            bucket = now_ist.replace(second=0, microsecond=0)
            bucket = bucket.replace(minute=(bucket.minute // INTRADAY_INTERVAL_MIN)
                                            * INTRADAY_INTERVAL_MIN)
            if last_intraday != bucket:
                last_intraday = bucket
                logger.info("[%02d:%02d IST] collect_and_alert", hm[0], hm[1])
                try:
                    run_full_pipeline(conn, intraday=True)
                except Exception as e:
                    logger.error("intraday error: %s", e)

        # ── overnight scan every 60 min ───────────────────────────────────
        elif not _in_market(hm):
            bucket = now_ist.replace(second=0, microsecond=0, minute=0)
            if last_overnight != bucket:
                last_overnight = bucket
                logger.info("[%02d:%02d IST] overnight_scan", hm[0], hm[1])
                try:
                    run_full_pipeline(conn, intraday=False)
                except Exception as e:
                    logger.error("overnight error: %s", e)

        # ── morning digest once at DIGEST_TIME_IST ────────────────────────
        dh, dm = DIGEST_TIME_IST
        if hm == (dh, dm) and last_digest != day:
            last_digest = day
            logger.info("[%02d:%02d IST] morning_digest", hm[0], hm[1])
            try:
                run_morning_digest(conn)
            except Exception as e:
                logger.error("morning_digest error: %s", e)

        time.sleep(30)


def _inject_demo(conn):
    """Inject sample events so the system has data to display immediately."""
    import json, hashlib
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    demo_events = [
        ("PTI", "Primary", "regulatory",
         "SEBI bans XYZ Capital from market for 2 years on insider trading charges",
         '["YESBANK"]', 9.5, -0.8),
        ("Economic Times", "Secondary", "earnings",
         "Reliance Q4 results: Net profit up 18% YoY, beats estimates",
         '["RELIANCE"]', 6.5, 0.7),
        ("MoneyControl", "Secondary", "regulatory",
         "HDFC Bank promoter pledge increases to 32% — concern for analysts",
         '["HDFCBANK"]', 7.2, -0.5),
        ("Reuters India", "Primary", "macro",
         "RBI holds repo rate at 6.5%, maintains accommodative stance",
         '[]', 5.0, 0.1),
        ("BSE", "Primary", "insider",
         "TCS director buys 50,000 shares worth Rs 18.5 Cr in open market",
         '["TCS"]', 5.5, 0.6),
        ("CNBCTV18", "Secondary", "credit",
         "CRISIL downgrades Vedanta NCD rating to BB+ from BBB- on liquidity concerns",
         '["VEDL"]', 8.0, -0.7),
    ]
    for (src, tier, etype, title, tickers, score, sent) in demo_events:
        hsh = hashlib.sha256(f"{src}|{title}".encode()).hexdigest()
        conn.execute("""
            INSERT OR IGNORE INTO events
            (hash,source_name,source_tier,title,tickers,event_type,
             published_at,severity_score,raw_sentiment)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (hsh, src, tier, title, tickers, etype, now, score, sent))
        row = conn.execute("SELECT id FROM events WHERE hash=?", (hsh,)).fetchone()
        if row:
            sev = ("CRITICAL" if score>=8.5 else "HIGH" if score>=6.5
                   else "MEDIUM" if score>=4.5 else "LOW")
            import json as _j
            for t in (_j.loads(tickers) or [None]):
                conn.execute("""
                    INSERT OR IGNORE INTO alerts
                    (event_id, severity, ticker, reason)
                    VALUES (?,?,?,?)
                """, (row[0], sev, t, "demo data"))
    conn.commit()
    logger.info("[Demo] Injected %d sample events.", len(demo_events))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Stock Intelligence Scheduler")
    p.add_argument("--run-once", action="store_true", help="Run once and exit")
    p.add_argument("--demo",     action="store_true", help="Inject demo data first")
    args = p.parse_args()
    run_scheduler(run_once=args.run_once, demo=args.demo)
