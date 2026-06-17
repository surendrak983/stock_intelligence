"""
main.py — Stock Intelligence System — Unified Entry Point

Usage:
  python main.py demo          Run pipeline with demo data, show results
  python main.py collect       Run live collectors once
  python main.py classify      Classify unprocessed events
  python main.py digest        Generate & save today's HTML digest
  python main.py alerts        Print all CRITICAL/HIGH alerts
  python main.py decisions     Run decision model on current signals
  python main.py status        Database statistics
  python main.py watchlist     Show / manage watchlist
  python main.py add TICKER    Add ticker to watchlist
  python main.py dashboard     Start web dashboard (localhost:5000)
  python main.py research      Run equity research scoring (Phase 3)
  python main.py schedule      Start continuous scheduler (live mode)
  python main.py schedule-demo Start scheduler with demo data (3 iterations)
"""

import sys, os, json, logging
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def bootstrap():
    from db import init_all_dbs
    init_all_dbs()
    _seed_watchlist()


def _seed_watchlist():
    from config import DEFAULT_WATCHLIST
    from db import get_media_conn
    conn = get_media_conn()
    existing = {r[0] for r in conn.execute(
        "SELECT ticker FROM watchlist_config WHERE ticker IS NOT NULL"
    ).fetchall()}
    for ticker in DEFAULT_WATCHLIST:
        if ticker not in existing:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist_config(ticker,threshold,active) VALUES(?,?,1)",
                (ticker, "HIGH"),
            )
    conn.commit()
    conn.close()


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_demo():
    from db import get_media_conn
    from scheduler import _inject_demo
    from pipeline import run_layer2_classify, run_layer3_deliver

    conn = get_media_conn()
    print("\n[1/3] Injecting demo data…")
    _inject_demo(conn)

    print("[2/3] Classifying…")
    r2 = run_layer2_classify(conn)
    print(f"  → {r2}")

    print("[3/3] Dispatching alerts…")
    r3 = run_layer3_deliver(conn, intraday=True)
    print(f"  → {r3}")

    cmd_alerts_inner(conn)
    conn.close()


def cmd_collect():
    from db import get_media_conn
    from pipeline import run_layer1_collect
    conn = get_media_conn()
    r = run_layer1_collect(conn)
    print(json.dumps(r, indent=2))
    conn.close()


def cmd_classify():
    from db import get_media_conn
    from pipeline import run_layer2_classify
    conn = get_media_conn()
    r = run_layer2_classify(conn)
    print(json.dumps(r, indent=2))
    conn.close()


def cmd_digest():
    from db import get_media_conn
    from pipeline import run_morning_digest
    conn = get_media_conn()
    path = run_morning_digest(conn)
    print(f"  ✓ Digest → {path}")
    conn.close()


def cmd_alerts_inner(conn):
    SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    rows = conn.execute("""
        SELECT a.severity, a.ticker, a.reason,
               e.title, e.source_name, e.published_at
        FROM alerts a JOIN events e ON a.event_id = e.id
        WHERE a.severity IN ('CRITICAL','HIGH')
        ORDER BY a.created_at DESC LIMIT 30
    """).fetchall()

    insider = conn.execute("""
        SELECT severity, ticker, signal_type, reason, created_at
        FROM insider_alerts
        WHERE severity IN ('CRITICAL','HIGH')
        ORDER BY created_at DESC LIMIT 10
    """).fetchall()

    credit = conn.execute("""
        SELECT severity, ticker, company_name, signal_type, reason, created_at
        FROM credit_alerts
        WHERE severity IN ('CRITICAL','HIGH')
        ORDER BY created_at DESC LIMIT 10
    """).fetchall()

    total = len(rows) + len(insider) + len(credit)
    if not total:
        print("\n  ✅ No CRITICAL/HIGH alerts in database. Run 'python main.py demo' first.")
        return

    EMOJI = {"CRITICAL": "🚨", "HIGH": "⚠️"}

    if rows:
        print(f"\n{'='*72}\n  📰 MEDIA ALERTS ({len(rows)})\n{'='*72}")
        for r in rows:
            print(f"  {EMOJI.get(r['severity'],'')} [{r['severity']:8s}] "
                  f"{r['ticker'] or 'MARKET':12s} | {r['source_name']}")
            print(f"    {r['title'][:90]}")

    if insider:
        print(f"\n{'='*72}\n  🔒 INSIDER ALERTS ({len(insider)})\n{'='*72}")
        for r in insider:
            print(f"  {EMOJI.get(r['severity'],'')} [{r['severity']:8s}] "
                  f"{r['ticker'] or '':12s} | {r['signal_type']}")
            print(f"    {r['reason'][:90]}")

    if credit:
        print(f"\n{'='*72}\n  💳 CREDIT ALERTS ({len(credit)})\n{'='*72}")
        for r in credit:
            print(f"  {EMOJI.get(r['severity'],'')} [{r['severity']:8s}] "
                  f"{r['ticker'] or '':12s} | {r['company_name'] or ''}")
            print(f"    {r['reason'][:90]}")


def cmd_alerts():
    from db import get_media_conn
    conn = get_media_conn()
    cmd_alerts_inner(conn)
    conn.close()


def cmd_decisions():
    from processors.decision_model import DecisionModel
    dm = DecisionModel(mark_consumed=False)
    decisions = dm.run()
    if not decisions:
        print("  No pending signals.")
        return
    print(f"\n{'='*72}\n  📊 EQUITY DECISIONS ({len(decisions)})\n{'='*72}")
    for d in decisions:
        print(d)
        print()


def cmd_status():
    from db import get_media_conn
    import sqlite3
    from config import REGULATORY_DB_PATH
    conn = get_media_conn()

    def cnt(table, where="1"):
        try: return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
        except: return "—"

    print(f"\n{'='*56}\n  DATABASE STATUS\n{'='*56}")
    print(f"  {'Media events':<30} {cnt('events'):>6}")
    print(f"  {'Media alerts':<30} {cnt('alerts'):>6}")
    print(f"  {'Insider alerts':<30} {cnt('insider_alerts'):>6}")
    print(f"  {'Credit alerts':<30} {cnt('credit_alerts'):>6}")
    print(f"  {'Digests generated':<30} {cnt('digest_history'):>6}")
    print(f"  {'Watchlist tickers':<30} {cnt('watchlist_config', 'active=1 AND ticker IS NOT NULL'):>6}")

    print("\n  Severity breakdown (media alerts):")
    for sev in ("CRITICAL","HIGH","MEDIUM","LOW"):
        print(f"    {sev:<10} {cnt('alerts', f'severity=\"{sev}\"'):>4}")

    # Regulatory DB
    try:
        rc = sqlite3.connect(REGULATORY_DB_PATH)
        re = rc.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
        ce = rc.execute("SELECT COUNT(*) FROM classified_events").fetchone()[0]
        rc.close()
        print(f"\n  {'Regulatory raw events':<30} {re:>6}")
        print(f"  {'Regulatory classified':<30} {ce:>6}")
    except:
        pass
    print()
    conn.close()


def cmd_watchlist():
    from db import get_media_conn
    conn = get_media_conn()
    rows = conn.execute(
        "SELECT ticker, keyword, threshold, active FROM watchlist_config ORDER BY ticker"
    ).fetchall()
    conn.close()
    print(f"\n  {'TICKER':<14} {'KEYWORD':<20} {'THRESHOLD':<10} ACTIVE")
    print("  " + "─"*54)
    for r in rows:
        print(f"  {(r['ticker'] or ''):.<14} {(r['keyword'] or ''):.<20} "
              f"{r['threshold']:<10} {'✓' if r['active'] else '✗'}")


def cmd_add_ticker(ticker: str):
    from db import get_media_conn
    conn = get_media_conn()
    conn.execute(
        "INSERT OR IGNORE INTO watchlist_config(ticker,threshold,active) VALUES(?,?,1)",
        (ticker.upper(), "HIGH"),
    )
    conn.commit()
    conn.close()
    print(f"  ✓ Added {ticker.upper()} to watchlist")


def cmd_dashboard():
    from delivery.web_dashboard import run_dashboard
    run_dashboard()


def cmd_research():
    from equity_research.main import main as research_main
    research_main()


def cmd_schedule(demo: bool = False, iterations: int = None):
    from scheduler import run_scheduler
    run_scheduler(run_once=(iterations is not None and iterations <= 1), demo=demo)


# ── Entry point ───────────────────────────────────────────────────────────────

USAGE = __doc__

if __name__ == "__main__":
    bootstrap()

    args = sys.argv[1:]
    cmd  = args[0] if args else "demo"

    dispatch = {
        "demo":          cmd_demo,
        "collect":       cmd_collect,
        "classify":      cmd_classify,
        "digest":        cmd_digest,
        "alerts":        cmd_alerts,
        "decisions":     cmd_decisions,
        "status":        cmd_status,
        "watchlist":     cmd_watchlist,
        "dashboard":     cmd_dashboard,
        "research":      cmd_research,
    }

    if cmd == "add" and len(args) > 1:
        cmd_add_ticker(args[1])
    elif cmd == "schedule":
        cmd_schedule(demo=False)
    elif cmd == "schedule-demo":
        cmd_schedule(demo=True, iterations=3)
    elif cmd in dispatch:
        dispatch[cmd]()
    else:
        print(USAGE)
