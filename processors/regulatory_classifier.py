"""
classifier.py v2 — Extended for all Regulatory sub-categories.
Reads raw_events → classified_events → signals.
Sub-domain tables (sebi_disclosures, credit_ratings etc.) already populated
by collectors; classifier only needs to score + signal.
"""
import json, logging, re
from datetime import datetime, timedelta
import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(__file__))); from db.regulatory_schema import get_conn

logger = logging.getLogger("classifier")

# ── Event type rules ──────────────────────────────────────────────────────────
EVENT_TYPES = {
    "INSIDER_TRADE": {
        "keywords": ["insider trading","kmp sold","kmp bought","pit reg","pit compliance",
                     "promoter sold","promoter bought","sast regulation","bulk deal",
                     "block deal","creeping acquisition","stake acquisition"],
        "base": 72,
    },
    "PROMOTER_PLEDGE": {
        "keywords": ["pledge creation","pledge invocation","pledge release",
                     "pledged shares","pledge invoked","margin call","lender invokes"],
        "base": 78,
    },
    "MERGER_ACQUISITION": {
        "keywords": ["merger","acquisition","takeover","open offer","scheme of arrangement",
                     "cci approval","cci approves","combination","amalgamation","demerger",
                     "strategic divestment","stake sale"],
        "base": 80,
    },
    "INSOLVENCY": {
        "keywords": ["insolvency","ibc","nclt","nclat","liquidation","cirp",
                     "resolution professional","moratorium","winding up",
                     "resolution plan","going concern","going-concern"],
        "base": 90,
    },
    "REGULATORY_PENALTY": {
        "keywords": ["sebi order","penalty","adjudication","show cause","enforcement",
                     "suspension","ban","barred","investigation","summons","fined",
                     "irdai penalty","sebi ban"],
        "base": 85,
    },
    "CREDIT_RATING_CHANGE": {
        "keywords": ["rating downgrade","rating upgrade","negative outlook","positive outlook",
                     "watch negative","watch positive","reaffirm","credit watch",
                     "crisil","icra","care ratings","india ratings","downgraded","upgraded",
                     "rating watch"],
        "base": 76,
    },
    "CORPORATE_FILING": {
        "keywords": ["chg-1","chg-4","dir-12","mgt-14","aoc-4","mgt-7","charge creation",
                     "charge satisfaction","board resolution","director change",
                     "ncd issuance","special resolution","annual accounts"],
        "base": 50,
    },
    "RESULTS_EARNINGS": {
        "keywords": ["q1 results","q2 results","q3 results","q4 results",
                     "quarterly results","annual results","net profit","revenue",
                     "ebitda","guidance","eps","profit up","profit down"],
        "base": 55,
    },
    "MACRO_REGULATORY": {
        "keywords": ["repo rate","rbi policy","monetary policy","mpc","rbi raises",
                     "rbi circular","priority sector","fpi limit","fdi","nbfc regulation"],
        "base": 68,
    },
    "TRADE_POLICY": {
        "keywords": ["anti-dumping","import licence","export licence","safeguard duty",
                     "dgft","cbic","customs notification","add duty","cvd"],
        "base": 60,
    },
    "INSURANCE_REGULATORY": {
        "keywords": ["irdai","pfrda","solvency ratio","investment disclosure",
                     "ulip","bancassurance","insurance penalty"],
        "base": 55,
    },
    "DEBT_ISSUANCE": {
        "keywords": ["ncd issuance","cp issuance","commercial paper","bond platform",
                     "cersai","securitisation","ptc issued","otc derivative",
                     "forex hedge","ccil","isin"],
        "base": 48,
    },
}

BULLISH_KW = [
    "merger approved","cci approval","profit up","revenue up","rating upgrade",
    "positive outlook","promoter bought","acquisition","buyback","bonus",
    "guidance maintained","reaffirmed aaa","strong","growth","record","beats",
    "charge satisfaction","pledge release","anti-dumping extended","safeguard",
    "reappointment","net debt free","upgrade","turnaround","watch positive",
]
BEARISH_KW = [
    "insolvency","ibc","liquidation","winding up","rating downgrade","going concern",
    "negative outlook","watch negative","insider sold","kmp sold","promoter sold",
    "pledge invocation","pledge invoked","margin call","penalty","sebi order","ban",
    "barred","investigation","profit down","guidance cut","npa","repo rate",
    "rate hike","anti-dumping duty on","import licence mandatory","stress",
    "downgrade","downgraded","fined","dissenting","rejected",
]

def classify_direction(text):
    l = text.lower()
    b = sum(1 for k in BULLISH_KW if k in l)
    s = sum(1 for k in BEARISH_KW if k in l)
    return "BEARISH" if s > b else ("BULLISH" if b > s else "NEUTRAL")

def classify_event_type(text):
    l = text.lower()
    best, best_score, matched = "CORPORATE_FILING", 20, []
    for etype, cfg in EVENT_TYPES.items():
        hits = [k for k in cfg["keywords"] if k in l]
        if hits:
            score = min(cfg["base"] + len(hits)*3, 100)
            if score > best_score:
                best, best_score, matched = etype, score, hits
    return best, best_score, matched

def score_to_severity(score):
    if score >= 85: return "CRITICAL"
    if score >= 65: return "HIGH"
    if score >= 45: return "MEDIUM"
    return "LOW"

SUMMARIES = {
    "INSIDER_TRADE":       lambda co,t: f"⚠️  Insider activity — {co}: {t[:75]}",
    "PROMOTER_PLEDGE":     lambda co,t: f"🔒 Promoter pledge event — {co}: {t[:75]}",
    "MERGER_ACQUISITION":  lambda co,t: f"🤝 M&A / combination — {co}: {t[:75]}",
    "INSOLVENCY":          lambda co,t: f"🚨 Insolvency / IBC — {co}: {t[:75]}",
    "REGULATORY_PENALTY":  lambda co,t: f"⛔ Regulatory action — {co}: {t[:75]}",
    "CREDIT_RATING_CHANGE":lambda co,t: f"📊 Rating event — {co}: {t[:75]}",
    "CORPORATE_FILING":    lambda co,t: f"📋 Corporate filing — {co}: {t[:75]}",
    "RESULTS_EARNINGS":    lambda co,t: f"📈 Earnings — {co}: {t[:75]}",
    "MACRO_REGULATORY":    lambda co,t: f"🏦 Macro / RBI — {t[:80]}",
    "TRADE_POLICY":        lambda co,t: f"🌏 Trade signal — {co}: {t[:75]}",
    "INSURANCE_REGULATORY":lambda co,t: f"🛡️  Insurance reg — {co}: {t[:75]}",
    "DEBT_ISSUANCE":       lambda co,t: f"💳 Debt / credit markets — {co}: {t[:75]}",
}

def classify_unprocessed(use_ai=False, batch=100):
    conn = get_conn()
    rows = conn.execute("""
        SELECT r.* FROM raw_events r
        LEFT JOIN classified_events c ON c.raw_event_id = r.id
        WHERE c.id IS NULL
        ORDER BY r.fetched_at DESC LIMIT ?
    """, (batch,)).fetchall()

    watchlist = {r["ticker"] for r in conn.execute("SELECT ticker FROM watchlist").fetchall()}
    done = 0

    for row in rows:
        txt = f"{row['title']} {row['body'] or ''}"
        etype, score, kws = classify_event_type(txt)
        direction = classify_direction(txt)
        severity = score_to_severity(score)
        co = row["company"] or row["ticker"] or "Unknown"
        summary = SUMMARIES.get(etype, lambda c,t: f"📌 {c}: {t[:80]}")(co, row["title"])

        cur = conn.execute("""
            INSERT INTO classified_events
                (raw_event_id,ticker,company,event_type,severity,severity_score,
                 signal_direction,keywords,summary,ai_enriched)
            VALUES (?,?,?,?,?,?,?,?,?,0)
        """, (row["id"],row["ticker"],row["company"],etype,severity,score,
              direction,",".join(kws),summary))
        cls_id = cur.lastrowid

        # Signal for CRITICAL/HIGH or watchlist ticker
        ticker = row["ticker"] or "MARKET"
        if severity in ("CRITICAL","HIGH") or ticker in watchlist:
            hours = {"CRITICAL":72,"HIGH":48,"MEDIUM":24,"LOW":12}[severity]
            conn.execute("""
                INSERT INTO signals
                    (ticker,signal_type,direction,confidence,severity,
                     source_event_id,rationale,valid_until)
                VALUES (?,?,?,?,?,?,?,?)
            """, (ticker, row["sub_category"] if row["sub_category"] else "REGULATORY".upper(),
                  direction, round(score/100,2), severity, cls_id,
                  summary, datetime.utcnow()+timedelta(hours=hours)))
        done += 1

    conn.commit()
    conn.close()
    return done

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from db import init_db; init_db()
    n = classify_unprocessed()
    print(f"[Classifier] {n} events classified")
