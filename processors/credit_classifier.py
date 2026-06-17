"""
Credit & Debt Markets Classifier — Phase 3
Scores all 5 credit-signal tables → writes to credit_alerts.

Severity logic per source description:
  RATING    : DOWNGRADE / WATCH_NEGATIVE → HIGH-CRITICAL (size+notch-driven)
              SUSPEND / DEFAULT → CRITICAL always
  CP_SPREAD : NBFC CP spread > 200bps over peer → CRITICAL (liquidity stress signal)
              spread 100-200bps → HIGH
  CERSAI    : New large charge creation on distressed co → HIGH
              Satisfaction (positive) → MEDIUM
  CCIL      : UNUSUAL_UNWIND or LARGE_USD_HEDGE → HIGH (hedging-pattern change)
  RBI_CREDIT: Sector NPA > 10%, credit growth < 0 → CRITICAL (NPA leading indicator)
              NPA 7-10% or slippage > 3% → HIGH
"""

import json, logging, sqlite3

logger = logging.getLogger("credit_classifier")

# ── Thresholds ───────────────────────────────────────────────────────────────
RATING_RANK = {"AAA":10,"AA+":9.5,"AA":9,"AA-":8.5,"A+":8,"A":7.5,"A-":7,
               "BBB+":6.5,"BBB":6,"BBB-":5.5,"BB+":5,"BB":4.5,"BB-":4,
               "B+":3.5,"B":3,"B-":2.5,"C":2,"D":1,"DEFAULT":0}

def _rrank(r):
    if not r: return 5.0
    return RATING_RANK.get(r.upper().strip().replace("(SO)","").replace("(CE)","").strip(), 5.0)

CP_SPREAD_CRITICAL_BPS  = 200
CP_SPREAD_HIGH_BPS      = 100
CP_SPREAD_MEDIUM_BPS    =  50

CERSAI_LARGE_CR         = 500    # charge > Rs 500 Cr → HIGH
CCIL_NOTIONAL_HIGH_CR   = 500

NPA_CRITICAL_PCT        = 10.0
NPA_HIGH_PCT            =  7.0
SLIPPAGE_HIGH_PCT        =  3.0
CREDIT_GROWTH_CRITICAL   =  0.0  # negative credit growth = CRITICAL


# ── 1. Ratings ────────────────────────────────────────────────────────────────

def _classify_ratings(conn):
    rows = conn.execute(
        "SELECT * FROM credit_ratings WHERE severity_score=0"
    ).fetchall()
    new = 0
    for r in [dict(x) for x in rows]:
        action   = (r.get("rating_action") or "").upper()
        new_r    = r.get("new_rating") or "NR"
        old_r    = r.get("old_rating") or new_r
        amount   = r.get("amount_cr") or 0.0
        notch_drop = _rrank(old_r) - _rrank(new_r)

        score, severity, reason = 2.0, "LOW", "routine reaffirmation"

        if action in ("SUSPEND","DEFAULT") or new_r == "D":
            score, severity, reason = 9.5, "CRITICAL", \
                f"Rating {action} / DEFAULT — {r['company_name']}"
        elif action == "DOWNGRADE":
            if notch_drop >= 3 or _rrank(new_r) <= 4:
                score, severity, reason = 9.0, "CRITICAL", \
                    f"Downgrade {old_r}→{new_r} ({notch_drop:.1f} notches, sub-investment grade)"
            elif notch_drop >= 2:
                score, severity, reason = 8.0, "CRITICAL", \
                    f"Downgrade {old_r}→{new_r} ({notch_drop:.1f} notches)"
            else:
                score, severity, reason = 7.0, "HIGH", \
                    f"Downgrade {old_r}→{new_r} — {r['company_name']}"
        elif action == "WATCH_NEGATIVE":
            score, severity, reason = 7.5, "HIGH", \
                f"Watch Negative at {new_r} — {r['company_name']}"
        elif action == "OUTLOOK_NEGATIVE":
            score, severity, reason = 6.5, "HIGH", \
                f"Outlook Negative at {new_r}"
        elif action == "WATCH_POSITIVE":
            score, severity, reason = 5.0, "MEDIUM", \
                f"Watch Positive at {new_r} (positive signal)"
        elif action == "UPGRADE":
            score, severity, reason = 4.5, "MEDIUM", \
                f"Upgrade {old_r}→{new_r} (positive signal)"
        elif amount >= 5000:
            score, severity, reason = 4.0, "MEDIUM", \
                f"Reaffirm at {new_r} on Rs {amount:.0f} Cr instrument"

        conn.execute("UPDATE credit_ratings SET severity_score=? WHERE id=?",
                     (score, r["id"]))
        if severity in ("CRITICAL","HIGH","MEDIUM"):
            conn.execute("""INSERT INTO credit_alerts
                (signal_type,source_table,source_id,ticker,company_name,severity,reason)
                VALUES(?,?,?,?,?,?,?)""",
                ("RATING","credit_ratings",r["id"],r["ticker"],
                 r["company_name"],severity,reason))
            new += 1
    return new


# ── 2. CP / Bond Issuances ────────────────────────────────────────────────────

def _classify_cp(conn):
    rows = conn.execute(
        "SELECT * FROM cp_issuances WHERE severity_score=0"
    ).fetchall()
    new = 0
    for r in [dict(x) for x in rows]:
        spread     = r.get("peer_spread_bps") or 0.0
        issuer_type = r.get("issuer_type") or "Corp"
        rate        = r.get("issuance_rate") or 0.0
        fv          = r.get("face_value_cr") or 0.0

        score, severity, reason = 2.0, "LOW", "routine CP/NCD issuance"

        if spread >= CP_SPREAD_CRITICAL_BPS and issuer_type in ("NBFC","HFC","MFI"):
            score, severity, reason = 9.0, "CRITICAL", \
                f"NBFC CP spread {spread:.0f}bps over peer — liquidity stress signal"
        elif spread >= CP_SPREAD_HIGH_BPS:
            score, severity, reason = 7.0, "HIGH", \
                f"CP spread {spread:.0f}bps over peer — elevated funding cost"
        elif spread >= CP_SPREAD_MEDIUM_BPS:
            score, severity, reason = 5.0, "MEDIUM", \
                f"CP spread {spread:.0f}bps — moderate stress"
        elif fv >= 2000:
            score, severity, reason = 4.0, "MEDIUM", \
                f"Large issuance Rs {fv:.0f} Cr ({r['cp_type']})"

        conn.execute("UPDATE cp_issuances SET severity_score=? WHERE id=?",
                     (score, r["id"]))
        if severity in ("CRITICAL","HIGH","MEDIUM"):
            conn.execute("""INSERT INTO credit_alerts
                (signal_type,source_table,source_id,ticker,company_name,severity,reason)
                VALUES(?,?,?,?,?,?,?)""",
                ("CP_SPREAD","cp_issuances",r["id"],r["ticker"],
                 r["issuer_name"],severity,reason))
            new += 1
    return new


# ── 3. CERSAI Charges ─────────────────────────────────────────────────────────

def _classify_cersai(conn):
    rows = conn.execute(
        "SELECT * FROM cersai_charges WHERE severity_score=0"
    ).fetchall()
    new = 0
    for r in [dict(x) for x in rows]:
        ctype  = (r.get("charge_type") or "").upper()
        amount = r.get("charge_amount_cr") or 0.0

        score, severity, reason = 2.0, "LOW", "routine charge filing"

        if ctype == "CREATION" and amount >= CERSAI_LARGE_CR:
            score, severity, reason = 7.0, "HIGH", \
                f"Large charge creation Rs {amount:.0f} Cr — asset encumbrance signal"
        elif ctype == "CREATION":
            score, severity, reason = 5.0, "MEDIUM", \
                f"New charge creation Rs {amount:.0f} Cr"
        elif ctype == "SATISFACTION":
            score, severity, reason = 4.0, "MEDIUM", \
                f"Charge satisfied Rs {amount:.0f} Cr (positive — debt reduction)"
        elif ctype == "MODIFICATION":
            score, severity, reason = 5.5, "MEDIUM", \
                f"Charge modification — terms change"

        conn.execute("UPDATE cersai_charges SET severity_score=? WHERE id=?",
                     (score, r["id"]))
        if severity in ("CRITICAL","HIGH","MEDIUM"):
            conn.execute("""INSERT INTO credit_alerts
                (signal_type,source_table,source_id,ticker,company_name,severity,reason)
                VALUES(?,?,?,?,?,?,?)""",
                ("CERSAI","cersai_charges",r["id"],r["ticker"],
                 r["company_name"],severity,reason))
            new += 1
    return new


# ── 4. CCIL Derivatives ───────────────────────────────────────────────────────

def _classify_ccil(conn):
    rows = conn.execute(
        "SELECT * FROM ccil_derivatives WHERE severity_score=0"
    ).fetchall()
    new = 0
    for r in [dict(x) for x in rows]:
        flag      = (r.get("pattern_flag") or "NORMAL").upper()
        notional  = r.get("notional_cr") or 0.0
        htype     = (r.get("hedge_type") or "NEW").upper()
        direction = (r.get("hedge_direction") or "").upper()

        score, severity, reason = 2.0, "LOW", "normal derivatives activity"

        if flag == "UNUSUAL_UNWIND":
            score, severity, reason = 7.5, "HIGH", \
                f"Unusual hedge unwind Rs {notional:.0f} Cr — hedging pattern change"
        elif flag == "LARGE_USD_HEDGE":
            score, severity, reason = 7.0, "HIGH", \
                f"Large FX hedge {direction} Rs {notional:.0f} Cr — currency risk signal"
        elif flag == "RAPID_ROLLOVER":
            score, severity, reason = 6.0, "HIGH", \
                f"Rapid derivative rollover — short-term funding dependency"
        elif notional >= CCIL_NOTIONAL_HIGH_CR:
            score, severity, reason = 5.0, "MEDIUM", \
                f"Large OTC position Rs {notional:.0f} Cr ({r['instrument_type']})"

        conn.execute("UPDATE ccil_derivatives SET severity_score=? WHERE id=?",
                     (score, r["id"]))
        if severity in ("CRITICAL","HIGH","MEDIUM"):
            conn.execute("""INSERT INTO credit_alerts
                (signal_type,source_table,source_id,ticker,company_name,severity,reason)
                VALUES(?,?,?,?,?,?,?)""",
                ("DERIVATIVE","ccil_derivatives",r["id"],r["ticker"],
                 r["entity_name"],severity,reason))
            new += 1
    return new


# ── 5. RBI Sectoral Credit ────────────────────────────────────────────────────

def _classify_rbi_credit(conn):
    rows = conn.execute(
        "SELECT * FROM rbi_credit_data WHERE severity_score=0"
    ).fetchall()
    new = 0
    for r in [dict(x) for x in rows]:
        npa      = r.get("npa_ratio_pct") or 0.0
        slippage = r.get("slippage_ratio_pct") or 0.0
        growth   = r.get("credit_growth_pct") or 99.0   # 99 = unknown
        stressed = r.get("stressed_assets_pct") or 0.0
        sector   = r.get("sector","General")

        score, severity, reason = 2.0, "LOW", f"{sector}: normal credit metrics"

        if npa >= NPA_CRITICAL_PCT or growth < CREDIT_GROWTH_CRITICAL:
            score, severity, reason = 9.0, "CRITICAL", \
                f"{sector}: NPA {npa:.1f}% / credit growth {growth:.1f}% — NPA ahead of NPL"
        elif npa >= NPA_HIGH_PCT or slippage >= SLIPPAGE_HIGH_PCT:
            score, severity, reason = 7.0, "HIGH", \
                f"{sector}: NPA {npa:.1f}%, slippage {slippage:.1f}% — stress building"
        elif stressed >= 5.0:
            score, severity, reason = 6.0, "HIGH", \
                f"{sector}: stressed assets {stressed:.1f}%"
        elif npa >= 4.0:
            score, severity, reason = 5.0, "MEDIUM", \
                f"{sector}: NPA {npa:.1f}% — elevated"

        conn.execute("UPDATE rbi_credit_data SET severity_score=? WHERE id=?",
                     (score, r["id"]))
        if severity in ("CRITICAL","HIGH","MEDIUM"):
            conn.execute("""INSERT INTO credit_alerts
                (signal_type,source_table,source_id,ticker,company_name,severity,reason)
                VALUES(?,?,?,?,?,?,?)""",
                ("RBI_CREDIT","rbi_credit_data",r["id"],None,
                 sector,severity,reason))
            new += 1
    return new


# ── Master ────────────────────────────────────────────────────────────────────

def classify_all_credit(conn: sqlite3.Connection) -> dict:
    logger.info("== Credit Classifier START ==")
    r = {
        "ratings":    _classify_ratings(conn),
        "cp":         _classify_cp(conn),
        "cersai":     _classify_cersai(conn),
        "ccil":       _classify_ccil(conn),
        "rbi_credit": _classify_rbi_credit(conn),
    }
    conn.commit()
    logger.info("== Credit Classifier END: %s ==", r)
    return r


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from db.schema import init_db
    from db.credit_schema import extend_db_credit
    conn = init_db()
    extend_db_credit(conn)
    print(classify_all_credit(conn))
    conn.close()
