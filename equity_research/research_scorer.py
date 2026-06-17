"""
Research Score Aggregator
Combines all 7 sources into a composite research score (0–100)
that feeds into the decision-making model.

Scoring Framework:
  Valuation    (25 pts): PE vs sector, PB, EV/EBITDA discount
  Quality      (25 pts): ROCE, ROE, OCF quality, debt comfort
  Growth       (20 pts): Revenue CAGR, PAT CAGR, EPS revision trend
  Ownership    (15 pts): Promoter pledge, FII change, DII confidence
  Sentiment    (15 pts): Broker consensus, concall sentiment delta
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'equity_research.db')


def get_conn():
    return sqlite3.connect(DB_PATH)


# ─── INDIVIDUAL SCORE COMPONENTS ─────────────────────────────────────────────

def score_valuation(conn, ticker: str) -> tuple[float, dict]:
    """Score valuation attractiveness (0–25)."""
    detail = {}
    score = 12.5  # start at midpoint

    # Latest financials for PE proxy
    row = conn.execute("""
        SELECT revenue_cr, pat_cr, eps FROM screener_financials
        WHERE ticker = ? ORDER BY period_end DESC LIMIT 1
    """, (ticker,)).fetchone()

    if row:
        revenue, pat, eps = row
        detail['latest_pat_cr'] = pat
        detail['latest_eps'] = eps

    # Peer comparison data
    peer_rows = conn.execute("""
        SELECT metric, ticker_value, sector_median FROM screener_peer_comparison
        WHERE ticker = ? ORDER BY as_of_date DESC LIMIT 10
    """, (ticker,)).fetchall()

    for metric, tv, sm in peer_rows:
        if sm and tv:
            discount_pct = (sm - tv) / sm * 100
            detail[f'{metric}_discount_pct'] = round(discount_pct, 1)
            if metric == 'PE':
                if discount_pct > 20:
                    score += 8
                elif discount_pct > 0:
                    score += 4
                elif discount_pct < -20:
                    score -= 8
                elif discount_pct < 0:
                    score -= 4

    return min(25.0, max(0.0, score)), detail


def score_quality(conn, ticker: str) -> tuple[float, dict]:
    """Score business quality (0–25)."""
    detail = {}
    score = 12.5

    rows = conn.execute("""
        SELECT roce_pct, roe_pct, debt_to_equity, ocf_cr, pat_cr
        FROM screener_financials
        WHERE ticker = ? ORDER BY period_end DESC LIMIT 5
    """, (ticker,)).fetchall()

    if not rows:
        return score, detail

    roces = [r[0] for r in rows if r[0]]
    roes = [r[1] for r in rows if r[1]]
    des = [r[2] for r in rows if r[2] is not None]
    ocf_pat = [(r[3] / r[4]) if r[3] and r[4] else None for r in rows]

    if roces:
        avg_roce = sum(roces) / len(roces)
        detail['roce_5yr_avg'] = round(avg_roce, 1)
        if avg_roce >= 20:
            score += 7
        elif avg_roce >= 15:
            score += 4
        elif avg_roce >= 10:
            score += 1
        else:
            score -= 3

    if roes:
        avg_roe = sum(roes) / len(roes)
        detail['roe_5yr_avg'] = round(avg_roe, 1)
        if avg_roe >= 18:
            score += 4
        elif avg_roe >= 12:
            score += 2

    if des:
        avg_de = sum(des) / len(des)
        detail['avg_debt_equity'] = round(avg_de, 2)
        if avg_de < 0.3:
            score += 5
        elif avg_de < 0.75:
            score += 2
        elif avg_de > 2.0:
            score -= 5

    valid_ocf = [x for x in ocf_pat if x is not None]
    if valid_ocf:
        avg_ocf = sum(valid_ocf) / len(valid_ocf)
        detail['ocf_pat_ratio'] = round(avg_ocf, 2)
        if avg_ocf >= 0.9:
            score += 4
        elif avg_ocf >= 0.7:
            score += 2
        elif avg_ocf < 0.5:
            score -= 3

    return min(25.0, max(0.0, score)), detail


def score_growth(conn, ticker: str) -> tuple[float, dict]:
    """Score growth trajectory (0–20)."""
    detail = {}
    score = 10.0

    rows = conn.execute("""
        SELECT period_end, revenue_cr, pat_cr, eps
        FROM screener_financials
        WHERE ticker = ? AND period_type = 'annual'
        ORDER BY period_end DESC LIMIT 4
    """, (ticker,)).fetchall()

    if len(rows) >= 3:
        rev_latest = rows[0][1]
        rev_3y = rows[2][1]
        pat_latest = rows[0][2]
        pat_3y = rows[2][2]

        if rev_latest and rev_3y and rev_3y > 0:
            cagr_rev = ((rev_latest / rev_3y) ** (1/3) - 1) * 100
            detail['revenue_cagr_3y'] = round(cagr_rev, 1)
            if cagr_rev >= 20:
                score += 5
            elif cagr_rev >= 12:
                score += 3
            elif cagr_rev >= 6:
                score += 1
            else:
                score -= 2

        if pat_latest and pat_3y and pat_3y > 0:
            cagr_pat = ((pat_latest / pat_3y) ** (1/3) - 1) * 100
            detail['pat_cagr_3y'] = round(cagr_pat, 1)
            if cagr_pat >= 20:
                score += 5
            elif cagr_pat >= 12:
                score += 3
            elif cagr_pat >= 6:
                score += 1
            else:
                score -= 2

    # EPS revision trend (last 6 months)
    revisions = conn.execute("""
        SELECT direction, COUNT(*) as cnt FROM trendlyne_estimate_revisions
        WHERE ticker = ? AND revision_date >= date('now', '-180 days')
        GROUP BY direction
    """, (ticker,)).fetchall()

    rev_map = {r[0]: r[1] for r in revisions}
    upgrades = rev_map.get('upgrade', 0)
    downgrades = rev_map.get('downgrade', 0)
    if upgrades + downgrades > 0:
        if upgrades > downgrades:
            detail['eps_revision_trend'] = 'upgrade'
            score += 4
        elif downgrades > upgrades:
            detail['eps_revision_trend'] = 'downgrade'
            score -= 4
        else:
            detail['eps_revision_trend'] = 'mixed'

    return min(20.0, max(0.0, score)), detail


def score_ownership(conn, ticker: str) -> tuple[float, dict]:
    """Score ownership quality (0–15)."""
    detail = {}
    score = 7.5

    # Latest shareholding
    sh = conn.execute("""
        SELECT promoter_pct, promoter_pledge_pct, fii_pct, dii_pct
        FROM screener_shareholding
        WHERE ticker = ? ORDER BY period_end DESC LIMIT 2
    """, (ticker,)).fetchall()

    if sh:
        promo, pledge, fii, dii = sh[0]
        detail['promoter_pct'] = promo
        detail['promoter_pledge_pct'] = pledge

        if pledge is not None:
            if pledge == 0:
                score += 5
            elif pledge < 10:
                score += 2
            elif pledge < 25:
                score -= 2
            else:
                score -= 6

        if len(sh) >= 2:
            fii_prev = sh[1][2]
            if fii is not None and fii_prev is not None:
                fii_delta = fii - fii_prev
                detail['fii_change_qoq'] = round(fii_delta, 2)
                if fii_delta > 1:
                    score += 4
                elif fii_delta > 0:
                    score += 2
                elif fii_delta < -1:
                    score -= 4
                elif fii_delta < 0:
                    score -= 2

    # Check pledging events
    pledge_events = conn.execute("""
        SELECT event_type FROM trendlyne_promoter_pledging
        WHERE ticker = ? ORDER BY event_date DESC LIMIT 5
    """, (ticker,)).fetchall()

    invoked = sum(1 for (e,) in pledge_events if e == 'pledge_invoked')
    if invoked > 0:
        score -= 5
        detail['pledge_invoked_events'] = invoked

    return min(15.0, max(0.0, score)), detail


def score_sentiment(conn, ticker: str) -> tuple[float, dict]:
    """Score analyst & management sentiment (0–15)."""
    detail = {}
    score = 7.5

    # Broker consensus
    targets = conn.execute("""
        SELECT recommendation FROM trendlyne_analyst_targets
        WHERE ticker = ? ORDER BY report_date DESC LIMIT 10
    """, (ticker,)).fetchall()

    if targets:
        recs = [r[0] for r in targets]
        buys = sum(1 for r in recs if 'BUY' in r.upper())
        sells = sum(1 for r in recs if 'SELL' in r.upper())
        holds = len(recs) - buys - sells
        total = len(recs)

        buy_pct = buys / total * 100
        detail['analyst_count'] = total
        detail['buy_pct'] = round(buy_pct, 0)
        detail['consensus'] = ('Strong Buy' if buy_pct >= 70 else
                                'Buy' if buy_pct >= 50 else
                                'Hold' if buy_pct >= 30 else 'Sell')

        if buy_pct >= 70:
            score += 5
        elif buy_pct >= 50:
            score += 2
        elif buy_pct < 30:
            score -= 3

    # Concall sentiment
    nlp = conn.execute("""
        SELECT sentiment_label, score_delta, guidance_tone, red_flags
        FROM concall_nlp_analysis
        WHERE ticker = ? ORDER BY fiscal_period DESC LIMIT 1
    """, (ticker,)).fetchone()

    if nlp:
        sent_label, delta, guidance, flags_json = nlp
        detail['concall_sentiment'] = sent_label
        detail['guidance_tone'] = guidance
        flags = json.loads(flags_json) if flags_json else []
        detail['red_flags'] = flags

        if sent_label == 'positive':
            score += 4
        elif sent_label == 'negative':
            score -= 4

        if delta is not None:
            detail['sentiment_delta'] = delta
            if delta > 0.1:
                score += 2
            elif delta < -0.1:
                score -= 2

        if flags:
            score -= len(flags) * 1.5
            detail['sentiment_shift'] = 'deteriorated' if flags else 'stable'

    return min(15.0, max(0.0, score)), detail


# ─── COMPOSITE SCORER ─────────────────────────────────────────────────────────

def generate_research_score(ticker: str) -> dict:
    """Generate full composite research score for a ticker."""
    conn = get_conn()

    v_score, v_detail = score_valuation(conn, ticker)
    q_score, q_detail = score_quality(conn, ticker)
    g_score, g_detail = score_growth(conn, ticker)
    o_score, o_detail = score_ownership(conn, ticker)
    s_score, s_detail = score_sentiment(conn, ticker)

    total = round(v_score + q_score + g_score + o_score + s_score, 1)

    components = {
        'valuation': {'score': round(v_score, 1), 'max': 25, 'detail': v_detail},
        'quality':   {'score': round(q_score, 1), 'max': 25, 'detail': q_detail},
        'growth':    {'score': round(g_score, 1), 'max': 20, 'detail': g_detail},
        'ownership': {'score': round(o_score, 1), 'max': 15, 'detail': o_detail},
        'sentiment': {'score': round(s_score, 1), 'max': 15, 'detail': s_detail},
    }

    # Interpret total score
    rating = ('STRONG BUY'   if total >= 80 else
              'BUY'           if total >= 65 else
              'ACCUMULATE'    if total >= 52 else
              'HOLD'          if total >= 40 else
              'REDUCE'        if total >= 28 else 'SELL')

    # Persist to DB
    conn.execute("""
        INSERT OR REPLACE INTO research_summary
        (ticker, generated_at, roce_5yr_avg, roe_5yr_avg, debt_equity,
         revenue_cagr_3y, pat_cagr_3y, eps_revision_6m,
         promoter_pledge_pct, fii_change_qoq,
         consensus_recommendation, analyst_count,
         concall_sentiment, sentiment_shift,
         research_score, score_components)
        VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ticker,
        q_detail.get('roce_5yr_avg'), q_detail.get('roe_5yr_avg'),
        q_detail.get('avg_debt_equity'),
        g_detail.get('revenue_cagr_3y'), g_detail.get('pat_cagr_3y'),
        g_detail.get('eps_revision_trend'),
        o_detail.get('promoter_pledge_pct'), o_detail.get('fii_change_qoq'),
        s_detail.get('consensus'), s_detail.get('analyst_count'),
        s_detail.get('concall_sentiment'), s_detail.get('sentiment_shift'),
        total, json.dumps(components)
    ))
    conn.commit()
    conn.close()

    return {
        'ticker': ticker,
        'total_score': total,
        'rating': rating,
        'components': components,
        'generated_at': datetime.now().isoformat()
    }


def run_all_tickers():
    """Generate research scores for all active watchlist tickers."""
    conn = get_conn()
    tickers = [r[0] for r in conn.execute(
        "SELECT ticker FROM watchlist WHERE is_active = 1"
    ).fetchall()]
    conn.close()

    results = []
    for t in tickers:
        try:
            res = generate_research_score(t)
            print(f"  📈 {t}: {res['total_score']}/100 → {res['rating']}")
            results.append(res)
        except Exception as e:
            print(f"  ❌ {t}: Error — {e}")

    results.sort(key=lambda x: x['total_score'], reverse=True)
    return results


if __name__ == '__main__':
    result = generate_research_score('TCS')
    print(json.dumps(result, indent=2))
