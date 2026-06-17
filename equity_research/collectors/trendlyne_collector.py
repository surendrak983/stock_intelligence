"""
Collector: Trendlyne
Fetches: Earnings estimate revisions, promoter pledging alerts, analyst target tracker
Source type: Secondary
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'equity_research.db')


def get_conn():
    return sqlite3.connect(DB_PATH)


def log_pull(conn, source, ticker, status, records=0, error=None):
    conn.execute("""
        INSERT INTO data_pull_log (source, ticker, status, records_fetched, error_msg)
        VALUES (?, ?, ?, ?, ?)
    """, (source, ticker, status, records, error))
    conn.commit()


def import_estimate_revisions(conn, records: list):
    count = 0
    for r in records:
        try:
            pct = ((r['new_estimate'] - r['old_estimate']) / abs(r['old_estimate']) * 100
                   if r.get('old_estimate') else None)
            direction = ('upgrade' if pct and pct > 2 else
                         'downgrade' if pct and pct < -2 else 'maintained')
            conn.execute("""
                INSERT OR IGNORE INTO trendlyne_estimate_revisions
                (ticker, analyst_house, revision_date, estimate_type, period,
                 old_estimate, new_estimate, pct_change, direction, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                r['ticker'], r.get('analyst_house'), r['revision_date'],
                r.get('estimate_type', 'EPS'), r.get('period'),
                r.get('old_estimate'), r['new_estimate'], pct, direction
            ))
            count += 1
        except Exception as e:
            print(f"    Revision insert error: {e}")
    conn.commit()
    return count


def import_promoter_pledging(conn, records: list):
    count = 0
    for r in records:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO trendlyne_promoter_pledging
                (ticker, event_date, event_type, shares_pledged, pct_of_total,
                 cumulative_pledge_pct, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                r['ticker'], r['event_date'], r['event_type'],
                r.get('shares_pledged'), r.get('pct_of_total'),
                r.get('cumulative_pledge_pct')
            ))
            count += 1
        except Exception as e:
            print(f"    Pledging insert error: {e}")
    conn.commit()
    return count


def import_analyst_targets(conn, records: list):
    count = 0
    for r in records:
        try:
            upside = ((r['target_price'] - r.get('current_price', r['target_price'])) /
                      r.get('current_price', r['target_price']) * 100
                      if r.get('current_price') else None)
            conn.execute("""
                INSERT OR REPLACE INTO trendlyne_analyst_targets
                (ticker, analyst_house, report_date, recommendation,
                 target_price, current_price_at_report, upside_pct, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                r['ticker'], r['analyst_house'], r['report_date'],
                r['recommendation'], r['target_price'],
                r.get('current_price'), upside
            ))
            count += 1
        except Exception as e:
            print(f"    Target insert error: {e}")
    conn.commit()
    return count


# ─── SAMPLE DATA ─────────────────────────────────────────────────────────────

SAMPLE_REVISIONS = [
    {"ticker": "TCS", "analyst_house": "Kotak", "revision_date": "2025-10-15",
     "estimate_type": "EPS", "period": "FY26E", "old_estimate": 130.5, "new_estimate": 134.2},
    {"ticker": "TCS", "analyst_house": "Motilal", "revision_date": "2025-10-15",
     "estimate_type": "EPS", "period": "FY26E", "old_estimate": 128.0, "new_estimate": 126.5},
    {"ticker": "RELIANCE", "analyst_house": "IIFL", "revision_date": "2025-10-20",
     "estimate_type": "Revenue", "period": "FY26E", "old_estimate": 930000, "new_estimate": 955000},
    {"ticker": "HDFC", "analyst_house": "Nuvama", "revision_date": "2025-10-18",
     "estimate_type": "EPS", "period": "FY26E", "old_estimate": 85.0, "new_estimate": 88.5},
]

SAMPLE_PLEDGING = [
    {"ticker": "ADANIPORTS", "event_date": "2025-09-01", "event_type": "pledge_released",
     "shares_pledged": 5000000, "pct_of_total": 0.2, "cumulative_pledge_pct": 1.8},
    {"ticker": "ADANIPORTS", "event_date": "2025-06-01", "event_type": "pledge_created",
     "shares_pledged": 8000000, "pct_of_total": 0.35, "cumulative_pledge_pct": 2.0},
]

SAMPLE_TARGETS = [
    {"ticker": "TCS", "analyst_house": "Kotak", "report_date": "2025-10-15",
     "recommendation": "BUY", "target_price": 4200, "current_price": 3850},
    {"ticker": "TCS", "analyst_house": "Motilal", "report_date": "2025-10-15",
     "recommendation": "BUY", "target_price": 4050, "current_price": 3850},
    {"ticker": "TCS", "analyst_house": "IIFL", "report_date": "2025-09-20",
     "recommendation": "HOLD", "target_price": 3900, "current_price": 3820},
    {"ticker": "RELIANCE", "analyst_house": "Nuvama", "report_date": "2025-10-20",
     "recommendation": "BUY", "target_price": 3200, "current_price": 2780},
    {"ticker": "RELIANCE", "analyst_house": "Kotak", "report_date": "2025-10-18",
     "recommendation": "BUY", "target_price": 3100, "current_price": 2780},
    {"ticker": "HDFC", "analyst_house": "Motilal", "report_date": "2025-10-22",
     "recommendation": "BUY", "target_price": 1950, "current_price": 1720},
]


def seed_sample_data():
    conn = get_conn()
    r1 = import_estimate_revisions(conn, SAMPLE_REVISIONS)
    r2 = import_promoter_pledging(conn, SAMPLE_PLEDGING)
    r3 = import_analyst_targets(conn, SAMPLE_TARGETS)
    print(f"  🌱 Trendlyne: {r1} revisions, {r2} pledging, {r3} targets seeded")
    conn.close()


if __name__ == '__main__':
    seed_sample_data()
