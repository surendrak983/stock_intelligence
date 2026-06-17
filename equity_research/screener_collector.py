"""
Collector: Screener.in
Fetches: 10-yr financials, shareholding history, peer comparison
Source type: Secondary (Aggregated / interpreted)

Uses: requests + BeautifulSoup scraping OR manual CSV import
"""

import sqlite3
import requests
import json
import time
import os
from datetime import datetime, date
from bs4 import BeautifulSoup

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'equity_research.db')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; EquityResearchBot/1.0)',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

BASE_URL = 'https://www.screener.in'


def get_conn():
    return sqlite3.connect(DB_PATH)


def log_pull(conn, source, ticker, status, records=0, error=None):
    conn.execute("""
        INSERT INTO data_pull_log (source, ticker, status, records_fetched, error_msg)
        VALUES (?, ?, ?, ?, ?)
    """, (source, ticker, status, records, error))
    conn.commit()


def fetch_company_data(ticker: str) -> dict:
    """
    Fetch company data from Screener.in.
    Falls back to structured dummy data for offline/demo use.
    """
    url = f"{BASE_URL}/company/{ticker}/consolidated/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return parse_screener_html(resp.text, ticker)
    except Exception as e:
        print(f"  [Screener] Live fetch failed for {ticker}: {e}")
        print(f"  [Screener] Using demo/manual import mode")
        return None


def parse_screener_html(html: str, ticker: str) -> dict:
    """Parse Screener.in HTML for key financial data."""
    soup = BeautifulSoup(html, 'html.parser')
    result = {'ticker': ticker, 'financials': [], 'shareholding': []}

    # --- Parse quarterly/annual P&L table ---
    tables = soup.select('section#profit-loss table')
    for table in tables[:1]:
        headers = [th.get_text(strip=True) for th in table.select('thead th')]
        rows = table.select('tbody tr')
        data_map = {}
        for row in rows:
            cols = [td.get_text(strip=True).replace(',', '') for td in row.select('td')]
            if cols:
                data_map[cols[0]] = cols[1:]
        # Build annual records
        for i, period in enumerate(headers[1:]):
            try:
                rec = {
                    'period_end': period,
                    'period_type': 'annual',
                    'revenue_cr': float(data_map.get('Sales', [None] * (i + 2))[i] or 0),
                    'pat_cr': float(data_map.get('Net Profit', [None] * (i + 2))[i] or 0),
                    'eps': float(data_map.get('EPS in Rs', [None] * (i + 2))[i] or 0),
                }
                result['financials'].append(rec)
            except Exception:
                continue

    return result


def import_financials_from_dict(conn, ticker: str, records: list):
    """Store parsed financial records to SQLite."""
    count = 0
    for r in records:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO screener_financials
                (ticker, period_end, period_type, revenue_cr, pat_cr, eps,
                 roce_pct, roe_pct, debt_to_equity, capex_cr, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                ticker,
                r.get('period_end'),
                r.get('period_type', 'annual'),
                r.get('revenue_cr'),
                r.get('pat_cr'),
                r.get('eps'),
                r.get('roce_pct'),
                r.get('roe_pct'),
                r.get('debt_to_equity'),
                r.get('capex_cr'),
            ))
            count += 1
        except Exception as e:
            print(f"    Insert error for {ticker}: {e}")
    conn.commit()
    return count


def import_shareholding(conn, ticker: str, records: list):
    """Store shareholding records."""
    count = 0
    for r in records:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO screener_shareholding
                (ticker, period_end, promoter_pct, promoter_pledge_pct,
                 dii_pct, fii_pct, public_pct, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                ticker,
                r.get('period_end'),
                r.get('promoter_pct'),
                r.get('promoter_pledge_pct', 0),
                r.get('dii_pct'),
                r.get('fii_pct'),
                r.get('public_pct'),
            ))
            count += 1
        except Exception as e:
            print(f"    Shareholding insert error: {e}")
    conn.commit()
    return count


def bulk_import_from_json(json_path: str):
    """
    Bulk import from a JSON file.
    Expected format:
    {
      "RELIANCE": {
        "financials": [...],
        "shareholding": [...]
      }
    }
    """
    conn = get_conn()
    with open(json_path) as f:
        data = json.load(f)

    total = 0
    for ticker, content in data.items():
        fin_count = import_financials_from_dict(conn, ticker, content.get('financials', []))
        sh_count = import_shareholding(conn, ticker, content.get('shareholding', []))
        log_pull(conn, 'screener.in', ticker, 'success', fin_count + sh_count)
        print(f"  ✅ {ticker}: {fin_count} financial rows, {sh_count} shareholding rows")
        total += fin_count + sh_count

    conn.close()
    print(f"\nTotal records imported: {total}")


def run_for_ticker(ticker: str):
    """Main entry point — try live fetch, else prompt manual import."""
    conn = get_conn()
    print(f"\n[Screener.in] Processing: {ticker}")

    data = fetch_company_data(ticker)
    if data and data.get('financials'):
        count = import_financials_from_dict(conn, ticker, data['financials'])
        log_pull(conn, 'screener.in', ticker, 'success', count)
        print(f"  ✅ {count} financial records stored")
    else:
        log_pull(conn, 'screener.in', ticker, 'partial', 0,
                 'Live fetch unavailable — use bulk_import_from_json()')
        print(f"  ℹ️  Use bulk_import_from_json('data/screener_export.json') for offline import")

    conn.close()


# ─── SAMPLE DATA SEEDER (for demo / testing) ─────────────────────────────────

SAMPLE_DATA = {
    "RELIANCE": {
        "financials": [
            {"period_end": "2024-03-31", "period_type": "annual", "revenue_cr": 899041, "pat_cr": 69621, "eps": 103.2, "roce_pct": 11.2, "roe_pct": 9.8, "debt_to_equity": 0.39, "capex_cr": 132000},
            {"period_end": "2023-03-31", "period_type": "annual", "revenue_cr": 817473, "pat_cr": 66702, "eps": 98.9, "roce_pct": 10.8, "roe_pct": 9.4, "debt_to_equity": 0.41, "capex_cr": 141000},
            {"period_end": "2022-03-31", "period_type": "annual", "revenue_cr": 721634, "pat_cr": 60705, "eps": 90.1, "roce_pct": 10.2, "roe_pct": 8.9, "debt_to_equity": 0.43, "capex_cr": 138000},
            {"period_end": "2021-03-31", "period_type": "annual", "revenue_cr": 486326, "pat_cr": 53739, "eps": 79.7, "roce_pct": 9.9, "roe_pct": 8.5, "debt_to_equity": 0.37, "capex_cr": 85000},
        ],
        "shareholding": [
            {"period_end": "2024-09-30", "promoter_pct": 50.3, "promoter_pledge_pct": 0.0, "dii_pct": 16.2, "fii_pct": 22.1, "public_pct": 11.4},
            {"period_end": "2024-06-30", "promoter_pct": 50.3, "promoter_pledge_pct": 0.0, "dii_pct": 15.9, "fii_pct": 22.4, "public_pct": 11.4},
        ]
    },
    "TCS": {
        "financials": [
            {"period_end": "2024-03-31", "period_type": "annual", "revenue_cr": 240893, "pat_cr": 45908, "eps": 124.6, "roce_pct": 56.4, "roe_pct": 50.6, "debt_to_equity": 0.04, "capex_cr": 5120},
            {"period_end": "2023-03-31", "period_type": "annual", "revenue_cr": 225458, "pat_cr": 42303, "eps": 114.7, "roce_pct": 53.2, "roe_pct": 47.1, "debt_to_equity": 0.05, "capex_cr": 4890},
            {"period_end": "2022-03-31", "period_type": "annual", "revenue_cr": 191754, "pat_cr": 38327, "eps": 103.7, "roce_pct": 50.8, "roe_pct": 44.9, "debt_to_equity": 0.06, "capex_cr": 4650},
        ],
        "shareholding": [
            {"period_end": "2024-09-30", "promoter_pct": 71.8, "promoter_pledge_pct": 0.0, "dii_pct": 8.4, "fii_pct": 12.6, "public_pct": 7.2},
        ]
    },
    "HDFC": {
        "financials": [
            {"period_end": "2024-03-31", "period_type": "annual", "revenue_cr": 283065, "pat_cr": 60812, "eps": 80.1, "roce_pct": 8.9, "roe_pct": 16.4, "debt_to_equity": 8.2},
            {"period_end": "2023-03-31", "period_type": "annual", "revenue_cr": 196952, "pat_cr": 44109, "eps": 79.3, "roce_pct": 9.1, "roe_pct": 17.2, "debt_to_equity": 7.9},
        ],
        "shareholding": [
            {"period_end": "2024-09-30", "promoter_pct": 0.0, "promoter_pledge_pct": 0.0, "dii_pct": 38.2, "fii_pct": 29.1, "public_pct": 32.7},
        ]
    }
}


def seed_sample_data():
    """Seed database with sample data for testing."""
    conn = get_conn()
    total = 0
    for ticker, content in SAMPLE_DATA.items():
        fin_count = import_financials_from_dict(conn, ticker, content.get('financials', []))
        sh_count = import_shareholding(conn, ticker, content.get('shareholding', []))
        log_pull(conn, 'screener.in', ticker, 'success', fin_count + sh_count)
        total += fin_count + sh_count
        print(f"  🌱 Seeded {ticker}: {fin_count} fin + {sh_count} shareholding rows")
    conn.close()
    print(f"  Total seeded: {total} records")


if __name__ == '__main__':
    seed_sample_data()
