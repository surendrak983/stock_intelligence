"""
credit_query_api.py — Query interface for Credit & Debt Market signals
Provides structured output for the equity decision model.

Key outputs:
  get_credit_alerts_summary()          per-ticker/sector alert counts
  get_rating_downgrades()              all rating downgrades/watches (last N hours)
  get_cp_stress_issuers()              NBFCs / issuers with elevated CP spreads
  get_cersai_large_charges()           large asset encumbrances
  get_ccil_pattern_flags()             unusual derivative hedging activity
  get_rbi_sector_stress()              sectors with rising NPAs / slowing credit
  get_credit_decision_payload(ticker)  all credit signals for one stock
  get_full_combined_payload(ticker)    Media + Insider + Credit merged
"""

import json, sqlite3, sys, os
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from db.schema import init_db

def _conn(p=None): return init_db(p) if p else init_db()
def _since(h=48):  return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()

SEV_ORDER = "CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END"


# ─── Alert summary ───────────────────────────────────────────────────────────

def get_credit_alerts_summary(hours=48, conn=None):
    """Per-ticker + per-signal-type alert counts."""
    c = conn or _conn()
    rows = c.execute(f"""
        SELECT ticker, company_name, signal_type,
               SUM(CASE WHEN severity='CRITICAL' THEN 1 ELSE 0 END) AS CRITICAL,
               SUM(CASE WHEN severity='HIGH'     THEN 1 ELSE 0 END) AS HIGH,
               SUM(CASE WHEN severity='MEDIUM'   THEN 1 ELSE 0 END) AS MEDIUM,
               COUNT(*) AS total
        FROM credit_alerts WHERE created_at>=?
        GROUP BY ticker, signal_type
        ORDER BY CRITICAL DESC, HIGH DESC
    """, (_since(hours),)).fetchall()
    return [dict(r) for r in rows]


# ─── Rating downgrades ────────────────────────────────────────────────────────

def get_rating_downgrades(hours=168, conn=None):
    """
    All DOWNGRADE / WATCH_NEGATIVE / DEFAULT actions.
    These 'lead equity price by days to weeks' per the tab description.
    """
    c = conn or _conn()
    rows = c.execute(f"""
        SELECT cr.ticker, cr.company_name, cr.rating_agency,
               cr.old_rating, cr.new_rating, cr.rating_action,
               cr.outlook, cr.amount_cr, cr.instrument,
               cr.action_date, ca.severity, ca.reason
        FROM credit_ratings cr
        JOIN credit_alerts ca ON ca.source_table='credit_ratings' AND ca.source_id=cr.id
        WHERE cr.rating_action IN ('DOWNGRADE','WATCH_NEGATIVE','SUSPEND','DEFAULT')
          AND cr.collected_at>=?
        ORDER BY {SEV_ORDER}, cr.amount_cr DESC
    """, (_since(hours),)).fetchall()
    return [dict(r) for r in rows]


# ─── CP / Liquidity stress ────────────────────────────────────────────────────

def get_cp_stress_issuers(hours=48, conn=None):
    """
    NBFCs and others issuing CP at elevated spreads — liquidity stress signal.
    """
    c = conn or _conn()
    rows = c.execute(f"""
        SELECT cp.ticker, cp.issuer_name, cp.issuer_type, cp.cp_type,
               cp.face_value_cr, cp.issuance_rate, cp.peer_spread_bps,
               cp.tenor_days, cp.issuance_date, ca.severity, ca.reason
        FROM cp_issuances cp
        JOIN credit_alerts ca ON ca.source_table='cp_issuances' AND ca.source_id=cp.id
        WHERE ca.severity IN ('CRITICAL','HIGH')
          AND cp.collected_at>=?
        ORDER BY cp.peer_spread_bps DESC
    """, (_since(hours),)).fetchall()
    return [dict(r) for r in rows]


# ─── CERSAI large charges ─────────────────────────────────────────────────────

def get_cersai_large_charges(hours=168, conn=None):
    """Large new charge creations — potential asset encumbrance / stress signals."""
    c = conn or _conn()
    rows = c.execute(f"""
        SELECT cc.ticker, cc.company_name, cc.secured_creditor,
               cc.charge_type, cc.asset_type, cc.charge_amount_cr,
               cc.charge_date, ca.severity, ca.reason
        FROM cersai_charges cc
        JOIN credit_alerts ca ON ca.source_table='cersai_charges' AND ca.source_id=cc.id
        WHERE ca.severity IN ('HIGH','MEDIUM')
          AND cc.collected_at>=?
        ORDER BY cc.charge_amount_cr DESC
    """, (_since(hours),)).fetchall()
    return [dict(r) for r in rows]


# ─── CCIL pattern flags ───────────────────────────────────────────────────────

def get_ccil_pattern_flags(hours=48, conn=None):
    """Unusual OTC derivative hedging activity."""
    c = conn or _conn()
    rows = c.execute(f"""
        SELECT cd.ticker, cd.entity_name, cd.instrument_type,
               cd.notional_cr, cd.hedge_direction, cd.hedge_type,
               cd.pattern_flag, cd.trade_date, ca.severity, ca.reason
        FROM ccil_derivatives cd
        JOIN credit_alerts ca ON ca.source_table='ccil_derivatives' AND ca.source_id=cd.id
        WHERE cd.pattern_flag != 'NORMAL'
          AND cd.collected_at>=?
        ORDER BY cd.notional_cr DESC
    """, (_since(hours),)).fetchall()
    return [dict(r) for r in rows]


# ─── RBI sector stress ────────────────────────────────────────────────────────

def get_rbi_sector_stress(hours=720, conn=None):
    """Sectors with elevated NPAs or decelerating credit — leading indicator."""
    c = conn or _conn()
    rows = c.execute(f"""
        SELECT rd.sector, rd.sub_sector, rd.credit_growth_pct,
               rd.npa_ratio_pct, rd.slippage_ratio_pct,
               rd.stressed_assets_pct, rd.period,
               ca.severity, ca.reason
        FROM rbi_credit_data rd
        JOIN credit_alerts ca ON ca.source_table='rbi_credit_data' AND ca.source_id=rd.id
        WHERE ca.severity IN ('CRITICAL','HIGH','MEDIUM')
          AND rd.collected_at>=?
        ORDER BY rd.npa_ratio_pct DESC
    """, (_since(hours),)).fetchall()
    return [dict(r) for r in rows]


# ─── Per-ticker decision payload ──────────────────────────────────────────────

def get_credit_decision_payload(ticker: str, hours=72, conn=None) -> dict:
    """All credit signals for a single equity ticker."""
    c = conn or _conn()

    alerts = [dict(r) for r in c.execute(f"""
        SELECT signal_type, company_name, severity, reason, created_at
        FROM credit_alerts WHERE ticker=? AND created_at>=?
        ORDER BY {SEV_ORDER}
    """, (ticker, _since(hours))).fetchall()]

    ratings = [dict(r) for r in c.execute("""
        SELECT rating_agency, old_rating, new_rating, rating_action,
               outlook, amount_cr, instrument, action_date
        FROM credit_ratings WHERE ticker=? AND collected_at>=?
        ORDER BY action_date DESC
    """, (ticker, _since(hours))).fetchall()]

    cp = [dict(r) for r in c.execute("""
        SELECT issuer_type, cp_type, face_value_cr, issuance_rate,
               peer_spread_bps, tenor_days, issuance_date
        FROM cp_issuances WHERE ticker=? AND collected_at>=?
        ORDER BY peer_spread_bps DESC
    """, (ticker, _since(hours))).fetchall()]

    cersai = [dict(r) for r in c.execute("""
        SELECT charge_type, asset_type, charge_amount_cr, charge_date, secured_creditor
        FROM cersai_charges WHERE ticker=? AND collected_at>=?
        ORDER BY charge_amount_cr DESC LIMIT 5
    """, (ticker, _since(hours))).fetchall()]

    deriv = [dict(r) for r in c.execute("""
        SELECT instrument_type, notional_cr, hedge_direction,
               hedge_type, pattern_flag, trade_date
        FROM ccil_derivatives WHERE ticker=? AND collected_at>=?
        ORDER BY notional_cr DESC LIMIT 5
    """, (ticker, _since(hours))).fetchall()]

    max_sev = alerts[0]["severity"] if alerts else "NONE"
    crit = sum(1 for a in alerts if a["severity"] == "CRITICAL")
    high = sum(1 for a in alerts if a["severity"] == "HIGH")
    credit_risk_score = min(round(crit * 3 + high * 1.5, 1), 10.0)

    # Dominant rating action
    dom_action = "NONE"
    if ratings:
        for action in ("DEFAULT","SUSPEND","DOWNGRADE","WATCH_NEGATIVE"):
            if any(r["rating_action"] == action for r in ratings):
                dom_action = action; break
        if dom_action == "NONE":
            dom_action = ratings[0]["rating_action"]

    return {
        "ticker":             ticker,
        "as_of":              datetime.now(timezone.utc).isoformat(),
        "hours_window":       hours,
        "max_severity":       max_sev,
        "credit_risk_score":  credit_risk_score,   # 0 clean … 10 distressed
        "dominant_action":    dom_action,
        "alert_count":        len(alerts),
        "alerts":             alerts,
        "ratings":            ratings,
        "cp_issuances":       cp,
        "cersai_charges":     cersai,
        "ccil_derivatives":   deriv,
    }


# ─── Full three-phase combined payload ───────────────────────────────────────

def get_full_combined_payload(ticker: str, hours=24, conn=None) -> dict:
    """
    Merges all three phases:
      Phase 1 — Media signals
      Phase 2 — Insider & ownership signals
      Phase 3 — Credit & debt market signals

    Returns one dict with composite scores for the decision model.
    """
    c = conn or _conn()

    # Phase 1
    try:
        from query_api import get_decision_payload
        media = get_decision_payload(ticker, hours, c)
    except Exception:
        media = {}

    # Phase 2
    try:
        from insider_query_api import get_insider_decision_payload
        insider = get_insider_decision_payload(ticker, hours, c)
    except Exception:
        insider = {}

    # Phase 3
    credit = get_credit_decision_payload(ticker, hours, c)

    # Composite risk (weighted average of three dimensions)
    media_score   = min(media.get("score_sum", 0.0) / 5.0, 10.0)   # normalise
    insider_score = insider.get("governance_score", 0.0)
    credit_score  = credit.get("credit_risk_score", 0.0)

    composite = round(
        media_score   * 0.30 +
        insider_score * 0.35 +
        credit_score  * 0.35,
        2
    )

    # Signal direction  (-1 bear … +1 bull)
    media_sent    = media.get("avg_sentiment", 0.0)
    credit_dir    = -1.0 if credit["dominant_action"] in ("DOWNGRADE","DEFAULT","SUSPEND","WATCH_NEGATIVE") else (
                     0.5 if credit["dominant_action"] in ("UPGRADE","WATCH_POSITIVE") else 0.0)
    trade_sents   = [1 if "BUY" in (t.get("trade_type","")) else -1
                     for t in insider.get("recent_trades",[])]
    insider_dir   = (sum(trade_sents)/len(trade_sents)) if trade_sents else 0.0
    combined_sent = round((media_sent + credit_dir + insider_dir) / 3, 3)

    return {
        "ticker":                  ticker,
        "as_of":                   datetime.now(timezone.utc).isoformat(),
        # ── Composite scores ──
        "composite_risk_score":    composite,      # 0 = clean, 10 = max distress
        "combined_signal":         combined_sent,  # -1 bear … +1 bull
        # ── Per-dimension max severity ──
        "media_max_severity":      media.get("max_severity","NONE"),
        "insider_max_severity":    insider.get("max_severity","NONE"),
        "credit_max_severity":     credit["max_severity"],
        "credit_dominant_action":  credit["dominant_action"],
        # ── Dimension payloads ──
        "media":   media,
        "insider": insider,
        "credit":  credit,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import pprint
    ticker = sys.argv[1] if len(sys.argv) > 1 else "HDFCBANK"
    conn = _conn()
    print("\n── Credit Alert Summary ──")
    pprint.pprint(get_credit_alerts_summary(72, conn)[:6])
    print("\n── Rating Downgrades ──")
    pprint.pprint(get_rating_downgrades(168, conn)[:4])
    print("\n── CP Stress Issuers ──")
    pprint.pprint(get_cp_stress_issuers(72, conn)[:3])
    print("\n── RBI Sector Stress ──")
    pprint.pprint(get_rbi_sector_stress(720, conn)[:4])
    print(f"\n── Full Combined Payload: {ticker} ──")
    p = get_full_combined_payload(ticker, 72, conn)
    print(f"  composite_risk_score : {p['composite_risk_score']}")
    print(f"  combined_signal      : {p['combined_signal']}")
    print(f"  credit_max_severity  : {p['credit_max_severity']}")
    print(f"  credit_dominant_action: {p['credit_dominant_action']}")
    conn.close()
