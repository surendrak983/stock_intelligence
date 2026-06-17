"""
Insider Signals Classifier — Phase 2
Scores all 6 insider-signal tables → writes to insider_alerts.

Severity rules (CRITICAL/HIGH/MEDIUM/LOW):
  INSIDER_TRADE : UPSI-window size, sell vs buy, promoter/KMP
  PLEDGE        : absolute pct, delta, new vs release
  QIB           : allotment type, size
  RPT           : value as % revenue, red-flag count
  DIRECTOR      : disqualification status, defaulting companies
  AGM/EGM       : minority dissent %, resolution passed/failed
"""

import json, logging, sqlite3

logger = logging.getLogger("insider_classifier")

PLEDGE_CRITICAL_PCT  = 50.0
PLEDGE_HIGH_PCT      = 25.0
PLEDGE_INCREASE_HIGH = 10.0
TRADE_CRITICAL_CR    = 50.0
TRADE_HIGH_CR        = 5.0
TRADE_BUY_MEDIUM_CR  = 2.0
RPT_CRITICAL_PCT     = 5.0
RPT_HIGH_PCT         = 2.0
DISSENT_CRITICAL_PCT = 25.0
DISSENT_HIGH_PCT     = 10.0


def _classify_insider_trades(conn):
    rows = conn.execute("SELECT * FROM insider_trades WHERE severity_score=0").fetchall()
    new = 0
    for r in [dict(x) for x in rows]:
        val=r.get("trade_value_cr") or 0.0
        ttype=(r.get("trade_type") or "").upper()
        window=(r.get("window_type") or "").upper()
        is_sell=any(s in ttype for s in ["SELL","SAST","DISPOSAL"])
        is_buy="BUY" in ttype or "ACQUI" in ttype
        score,severity,reason=2.0,"LOW","routine disclosure"
        if "UPSI" in window and is_sell:
            if val>=TRADE_CRITICAL_CR: score,severity,reason=9.5,"CRITICAL",f"UPSI-window SELL Rs{val:.1f}Cr"
            elif val>=TRADE_HIGH_CR:   score,severity,reason=7.5,"HIGH",f"UPSI-window SELL Rs{val:.1f}Cr"
            else:                      score,severity,reason=6.0,"HIGH","UPSI-window sale"
        elif is_sell and val>=TRADE_CRITICAL_CR: score,severity,reason=8.0,"CRITICAL",f"Large promoter SELL Rs{val:.1f}Cr"
        elif is_sell and val>=TRADE_HIGH_CR:     score,severity,reason=6.5,"HIGH",f"Promoter SELL Rs{val:.1f}Cr"
        elif is_buy and val>=TRADE_BUY_MEDIUM_CR:score,severity,reason=5.0,"MEDIUM",f"Promoter BUY Rs{val:.1f}Cr (positive)"
        conn.execute("UPDATE insider_trades SET severity_score=? WHERE id=?",(score,r["id"]))
        if severity in ("CRITICAL","HIGH","MEDIUM"):
            conn.execute("INSERT INTO insider_alerts(signal_type,source_table,source_id,ticker,severity,reason) VALUES(?,?,?,?,?,?)",
                         ("INSIDER_TRADE","insider_trades",r["id"],r["ticker"],severity,reason)); new+=1
    return new


def _classify_pledge(conn):
    rows=conn.execute("SELECT * FROM pledge_tracker WHERE severity_score=0").fetchall()
    new=0
    for r in [dict(x) for x in rows]:
        pct=r.get("pledge_pct") or 0.0; change=r.get("change_pct") or 0.0
        ctype=(r.get("change_type") or "").upper()
        score,severity,reason=2.0,"LOW","routine pledge update"
        if pct>=PLEDGE_CRITICAL_PCT:          score,severity,reason=9.0,"CRITICAL",f"Pledge {pct:.1f}% — extreme stress"
        elif pct>=PLEDGE_HIGH_PCT:            score,severity,reason=7.0,"HIGH",f"Pledge {pct:.1f}%"
        elif "INCREASE" in ctype and change>=PLEDGE_INCREASE_HIGH: score,severity,reason=6.5,"HIGH",f"Pledge+{change:.1f}pp"
        elif "NEW" in ctype:                  score,severity,reason=6.0,"HIGH","New pledge"
        elif "DECREAS" in ctype or "REVOK" in ctype: score,severity,reason=4.0,"MEDIUM","Pledge released"
        conn.execute("UPDATE pledge_tracker SET severity_score=? WHERE id=?",(score,r["id"]))
        if severity in ("CRITICAL","HIGH","MEDIUM"):
            conn.execute("INSERT INTO insider_alerts(signal_type,source_table,source_id,ticker,severity,reason) VALUES(?,?,?,?,?,?)",
                         ("PLEDGE","pledge_tracker",r["id"],r["ticker"],severity,reason)); new+=1
    return new


def _classify_qib(conn):
    rows=conn.execute("SELECT * FROM qib_allotments WHERE severity_score=0").fetchall()
    new=0
    for r in [dict(x) for x in rows]:
        atype=(r.get("allotment_type") or "").upper(); size_cr=r.get("allotment_size_cr") or 0.0
        if "QIP" in atype or "ANCHOR" in atype: score,severity,reason=7.0,"HIGH",f"{atype} Rs{size_cr:.0f}Cr — institutional conviction"
        elif "PREFER" in atype:                 score,severity,reason=6.0,"HIGH",f"Preferential Rs{size_cr:.0f}Cr"
        elif "RIGHTS" in atype:                 score,severity,reason=5.0,"MEDIUM","Rights issue"
        else:                                   score,severity,reason=3.0,"LOW","Allotment"
        conn.execute("UPDATE qib_allotments SET severity_score=? WHERE id=?",(score,r["id"]))
        if severity in ("CRITICAL","HIGH","MEDIUM"):
            conn.execute("INSERT INTO insider_alerts(signal_type,source_table,source_id,ticker,severity,reason) VALUES(?,?,?,?,?,?)",
                         ("QIB","qib_allotments",r["id"],r["ticker"],severity,reason)); new+=1
    return new


def _classify_rpt(conn):
    rows=conn.execute("SELECT * FROM related_party_txns WHERE severity_score=0").fetchall()
    new=0
    for r in [dict(x) for x in rows]:
        pct_rev=r.get("txn_pct_revenue") or 0.0; flags=json.loads(r.get("red_flags") or "[]")
        score,severity,reason=3.0,"LOW","RPT routine"
        if pct_rev>=RPT_CRITICAL_PCT or "tunnelling risk" in flags: score,severity,reason=9.0,"CRITICAL",f"RPT {pct_rev:.1f}%rev / tunnelling"
        elif pct_rev>=RPT_HIGH_PCT or len(flags)>=2:                score,severity,reason=7.0,"HIGH",f"RPT {pct_rev:.1f}%rev flags:{flags}"
        elif flags:                                                  score,severity,reason=5.5,"MEDIUM",f"RPT flag:{flags[0]}"
        conn.execute("UPDATE related_party_txns SET severity_score=? WHERE id=?",(score,r["id"]))
        if severity in ("CRITICAL","HIGH","MEDIUM"):
            conn.execute("INSERT INTO insider_alerts(signal_type,source_table,source_id,ticker,severity,reason) VALUES(?,?,?,?,?,?)",
                         ("RPT","related_party_txns",r["id"],r["ticker"],severity,reason)); new+=1
    return new


def _classify_directors(conn):
    rows=conn.execute("SELECT * FROM director_checks WHERE severity_score=0").fetchall()
    new=0
    for r in [dict(x) for x in rows]:
        disq=r.get("disqualified",0); defaulting=json.loads(r.get("defaulting_companies") or "[]")
        desig=(r.get("designation") or "").lower()
        if disq:        score,severity,reason=9.5,"CRITICAL",f"MCA disqualified: {r.get('disq_reason','')}"
        elif defaulting:score,severity,reason=7.5,"HIGH",f"Director in {len(defaulting)} defaulting cos"
        elif "resign" in desig: score,severity,reason=6.5,"HIGH","Director resignation"
        else:           score,severity,reason=4.0,"MEDIUM","Director appointment"
        conn.execute("UPDATE director_checks SET severity_score=? WHERE id=?",(score,r["id"]))
        if severity in ("CRITICAL","HIGH","MEDIUM"):
            conn.execute("INSERT INTO insider_alerts(signal_type,source_table,source_id,ticker,severity,reason) VALUES(?,?,?,?,?,?)",
                         ("DIRECTOR","director_checks",r["id"],r["ticker"],severity,reason)); new+=1
    return new


def _classify_agm(conn):
    rows=conn.execute("SELECT * FROM agm_egm_outcomes WHERE severity_score=0").fetchall()
    new=0
    for r in [dict(x) for x in rows]:
        dissent=r.get("minority_dissent_pct") or r.get("votes_against_pct") or 0.0
        passed=r.get("resolution_passed",1)
        if dissent>=DISSENT_CRITICAL_PCT:    score,severity,reason=9.0,"CRITICAL",f"Minority dissent {dissent:.1f}%"
        elif dissent>=DISSENT_HIGH_PCT:      score,severity,reason=7.0,"HIGH",f"Minority dissent {dissent:.1f}%"
        elif not passed:                     score,severity,reason=7.0,"HIGH","Resolution rejected"
        else:                               score,severity,reason=3.5,"LOW","Passed, low dissent"
        conn.execute("UPDATE agm_egm_outcomes SET severity_score=? WHERE id=?",(score,r["id"]))
        if severity in ("CRITICAL","HIGH","MEDIUM"):
            conn.execute("INSERT INTO insider_alerts(signal_type,source_table,source_id,ticker,severity,reason) VALUES(?,?,?,?,?,?)",
                         ("AGM","agm_egm_outcomes",r["id"],r["ticker"],severity,reason)); new+=1
    return new


def classify_all_insider(conn):
    r={}
    r["insider_trades"]=_classify_insider_trades(conn)
    r["pledge"]=_classify_pledge(conn)
    r["qib"]=_classify_qib(conn)
    r["rpt"]=_classify_rpt(conn)
    r["directors"]=_classify_directors(conn)
    r["agm"]=_classify_agm(conn)
    conn.commit()
    logger.info("Insider classify done: %s",r)
    return r


if __name__=="__main__":
    import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),".."))
    from db.schema import init_db; from db.insider_schema import extend_db
    conn=init_db(); extend_db(conn)
    print(classify_all_insider(conn)); conn.close()
