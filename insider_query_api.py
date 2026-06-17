"""
insider_query_api.py — Query interface for Insider & Ownership signals
Key outputs:
  get_insider_alerts_summary()         alerts by ticker + signal_type
  get_pledge_stress_tickers()          rising/high pledge tickers
  get_governance_risk_tickers()        director / AGM / RPT risk
  get_conviction_buys()                QIB anchors + insider BUYs
  get_insider_decision_payload(ticker) full insider payload for one ticker
  get_combined_payload(ticker)         Phase 1 media + Phase 2 insider merged
"""
import json, sqlite3, sys, os
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from db.schema import init_db

def _conn(p=None): return init_db(p) if p else init_db()
def _since(h=24): return (datetime.now(timezone.utc)-timedelta(hours=h)).isoformat()

def get_insider_alerts_summary(hours=48, conn=None):
    c=conn or _conn()
    rows=c.execute("""
        SELECT ticker,signal_type,
               SUM(CASE WHEN severity='CRITICAL' THEN 1 ELSE 0 END) AS CRITICAL,
               SUM(CASE WHEN severity='HIGH' THEN 1 ELSE 0 END) AS HIGH,
               SUM(CASE WHEN severity='MEDIUM' THEN 1 ELSE 0 END) AS MEDIUM,
               COUNT(*) AS total
        FROM insider_alerts WHERE created_at>=?
        GROUP BY ticker,signal_type ORDER BY CRITICAL DESC,HIGH DESC
    """,(_since(hours),)).fetchall()
    return [dict(r) for r in rows]

def get_pledge_stress_tickers(hours=168, conn=None):
    c=conn or _conn()
    rows=c.execute("""
        SELECT p.ticker,p.pledge_pct,p.change_pct,p.change_type,
               p.promoter_name,p.pledge_date,ia.severity,ia.reason
        FROM pledge_tracker p
        JOIN insider_alerts ia ON ia.source_table='pledge_tracker' AND ia.source_id=p.id
        WHERE ia.severity IN ('CRITICAL','HIGH') AND p.collected_at>=?
        ORDER BY p.pledge_pct DESC
    """,(_since(hours),)).fetchall()
    return [dict(r) for r in rows]

def get_governance_risk_tickers(hours=168, conn=None):
    c=conn or _conn()
    rows=c.execute("""
        SELECT ia.ticker,ia.signal_type,ia.severity,ia.reason,ia.created_at
        FROM insider_alerts ia
        WHERE ia.signal_type IN ('DIRECTOR','AGM','RPT')
          AND ia.severity IN ('CRITICAL','HIGH') AND ia.created_at>=?
        ORDER BY ia.severity,ia.created_at DESC
    """,(_since(hours),)).fetchall()
    return [dict(r) for r in rows]

def get_conviction_buys(hours=168, conn=None):
    c=conn or _conn()
    qib=c.execute("""
        SELECT q.ticker,q.allotment_type,q.anchor_name,
               q.allotment_size_cr,q.price,q.allotment_date,ia.severity,ia.reason
        FROM qib_allotments q
        JOIN insider_alerts ia ON ia.source_table='qib_allotments' AND ia.source_id=q.id
        WHERE q.collected_at>=? ORDER BY q.allotment_size_cr DESC
    """,(_since(hours),)).fetchall()
    buys=c.execute("""
        SELECT it.ticker,it.trader_name,it.trader_category,
               it.quantity,it.trade_value_cr,it.trade_date,ia.severity,ia.reason
        FROM insider_trades it
        JOIN insider_alerts ia ON ia.source_table='insider_trades' AND ia.source_id=it.id
        WHERE ia.signal_type='INSIDER_TRADE'
          AND (it.trade_type LIKE '%BUY%' OR it.trade_type LIKE '%ACQUI%')
          AND it.collected_at>=? ORDER BY it.trade_value_cr DESC
    """,(_since(hours),)).fetchall()
    return {"qib_anchor_allotments":[dict(r) for r in qib],"insider_buys":[dict(r) for r in buys]}

def get_insider_decision_payload(ticker, hours=48, conn=None):
    c=conn or _conn()
    alerts=[dict(r) for r in c.execute("""
        SELECT signal_type,severity,reason,created_at FROM insider_alerts
        WHERE ticker=? AND created_at>=?
        ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
                               WHEN 'MEDIUM' THEN 3 ELSE 4 END
    """,(ticker,_since(hours))).fetchall()]
    pledge=c.execute("SELECT pledge_pct,change_pct,change_type,pledge_date FROM pledge_tracker WHERE ticker=? ORDER BY pledge_date DESC LIMIT 1",(ticker,)).fetchone()
    trades=[dict(r) for r in c.execute("SELECT trader_category,trade_type,trade_value_cr,trade_date,window_type FROM insider_trades WHERE ticker=? AND collected_at>=? ORDER BY trade_date DESC",(ticker,_since(hours))).fetchall()]
    rpt=[dict(r) for r in c.execute("SELECT txn_type,txn_value_cr,txn_pct_revenue,red_flags FROM related_party_txns WHERE ticker=? AND collected_at>=? ORDER BY txn_value_cr DESC LIMIT 3",(ticker,_since(hours))).fetchall()]
    directors=[dict(r) for r in c.execute("SELECT director_name,designation,disqualified,disq_reason FROM director_checks WHERE ticker=? AND collected_at>=?",(ticker,_since(hours))).fetchall()]
    agm=[dict(r) for r in c.execute("SELECT meeting_type,resolution_title,votes_for_pct,minority_dissent_pct,resolution_passed,dissent_flag FROM agm_egm_outcomes WHERE ticker=? AND collected_at>=? ORDER BY meeting_date DESC LIMIT 3",(ticker,_since(hours))).fetchall()]
    max_sev=alerts[0]["severity"] if alerts else "NONE"
    crit=sum(1 for a in alerts if a["severity"]=="CRITICAL")
    high=sum(1 for a in alerts if a["severity"]=="HIGH")
    return {
        "ticker":ticker,"as_of":datetime.now(timezone.utc).isoformat(),"hours_window":hours,
        "max_severity":max_sev,"governance_score":min(round(crit*3+high*1.5,1),10.0),
        "alert_count":len(alerts),"alerts":alerts,"pledge":dict(pledge) if pledge else {},
        "recent_trades":trades,"rpt_issues":rpt,"director_flags":directors,"agm_outcomes":agm,
    }

def get_combined_payload(ticker, hours=24, conn=None):
    c=conn or _conn()
    try:
        from query_api import get_decision_payload
        media=get_decision_payload(ticker,hours,c)
    except Exception:
        media={}
    insider=get_insider_decision_payload(ticker,hours,c)
    media_score=media.get("score_sum",0.0)
    insider_score=insider.get("governance_score",0.0)*1.5
    composite=min(round(media_score*0.4+insider_score*0.6,2),10.0)
    media_sent=media.get("avg_sentiment",0.0)
    ts=[1 if "BUY" in (t.get("trade_type","")) else -1 for t in insider.get("recent_trades",[])]
    insider_dir=(sum(ts)/len(ts)) if ts else 0.0
    return {
        "ticker":ticker,"as_of":datetime.now(timezone.utc).isoformat(),
        "composite_risk_score":composite,
        "combined_sentiment":round((media_sent+insider_dir)/2,3),
        "media_max_severity":media.get("max_severity","NONE"),
        "insider_max_severity":insider.get("max_severity","NONE"),
        "media":media,"insider":insider,
    }

if __name__=="__main__":
    import pprint
    ticker=sys.argv[1] if len(sys.argv)>1 else "RELIANCE"
    conn=_conn()
    print("\n── Insider Alert Summary ──"); pprint.pprint(get_insider_alerts_summary(48,conn)[:5])
    print("\n── Pledge Stress ──"); pprint.pprint(get_pledge_stress_tickers(168,conn)[:3])
    print("\n── Governance Risk ──"); pprint.pprint(get_governance_risk_tickers(168,conn)[:3])
    print("\n── Conviction Buys ──"); pprint.pprint(get_conviction_buys(168,conn))
    print(f"\n── Combined Payload for {ticker} ──"); pprint.pprint(get_combined_payload(ticker,48,conn))
    conn.close()
