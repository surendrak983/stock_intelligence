"""
Credit & Debt Markets Collector — Phase 3
5 sources: CRISIL/ICRA/CARE, NSE CP, CERSAI, CCIL, RBI credit data.
"""
import hashlib, json, logging, re, sqlite3
from datetime import datetime, timezone
from typing import Optional
import feedparser, requests
from bs4 import BeautifulSoup

logger = logging.getLogger("credit_collector")
HEADERS = {"User-Agent": "MediaIntelBot/1.0"}

def _hash(*p): return hashlib.sha256("|".join(str(x) for x in p).encode()).hexdigest()
def _now(): return datetime.now(timezone.utc).isoformat()
def _get(url, timeout=12, **kw):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, **kw)
        r.raise_for_status(); return r
    except Exception as e:
        logger.warning("GET %s → %s", url[:60], e); return None

RATING_RANK = {"AAA":10,"AA+":9.5,"AA":9,"AA-":8.5,"A+":8,"A":7.5,"A-":7,
               "BBB+":6.5,"BBB":6,"BBB-":5.5,"BB+":5,"BB":4.5,"BB-":4,
               "B+":3.5,"B":3,"B-":2.5,"C":2,"D":1,"DEFAULT":0}

def _rrank(r): return RATING_RANK.get(r.upper().strip().replace("(SO)","").replace("(CE)","").strip(), 5.0)

def _detect_action(old, new, text):
    tl=text.lower()
    if "suspend" in tl: return "SUSPEND"
    if "withdraw" in tl: return "WITHDRAW"
    if "watch" in tl and "positive" in tl: return "WATCH_POSITIVE"
    if "watch" in tl and ("negative" in tl or "developing" in tl): return "WATCH_NEGATIVE"
    if "negative" in tl or "downgrade" in tl: return "DOWNGRADE"
    if "positive" in tl or "upgrade" in tl: return "UPGRADE"
    if old and new:
        if _rrank(new)<_rrank(old)-0.4: return "DOWNGRADE"
        if _rrank(new)>_rrank(old)+0.4: return "UPGRADE"
    return "REAFFIRM"

def _parse_cr(text):
    m=re.search(r"(?:rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s*(cr|lakh|mn)?", text.lower())
    if not m: return 0.0
    v=float(m.group(1).replace(",","")); u=m.group(2) or "cr"
    if u=="lakh": v/=100
    if u=="mn":   v/=10
    return round(v,2)

def _extract_ratings(text):
    m=re.search(r'from\s+([A-Z]{1,4}[+-]?)\s+to\s+([A-Z]{1,4}[+-]?)', text, re.I)
    if m: return m.group(1).upper(), m.group(2).upper()
    m=re.search(r'(?:at|to|affirmed)\s+([A-Z]{1,4}[+-]?)', text, re.I)
    if m: return None, m.group(1).upper()
    return None, "NR"

RATING_FEEDS = [
    ("BSE",          "https://www.bseindia.com/data/xml/notices.xml"),
    ("SEBI",         "https://www.sebi.gov.in/rss/sebi_bulletin.xml"),
    ("ICRA",         "https://www.icra.in/rating/rss"),
    ("CARE",         "https://www.careratings.com/press_release_rss.xml"),
    ("India Ratings","https://www.indiaratings.co.in/PressRelease/rss"),
]
RATING_KW=["rating","downgrade","upgrade","watch","outlook","reaffirm","credit watch",
           "default","ncd","commercial paper","bank loan","subordinated","debenture"]

def collect_ratings(conn):
    ins=0
    for agency, url in RATING_FEEDS:
        try: fp=feedparser.parse(url)
        except: continue
        for e in fp.entries:
            title=e.get("title","").strip(); lnk=e.get("link","").strip()
            summary=BeautifulSoup(e.get("summary",e.get("description","")), "html.parser").get_text(" ",strip=True)[:600]
            text=f"{title} {summary}".lower()
            if not any(k in text for k in RATING_KW): continue
            for a in ("CRISIL","ICRA","CARE","India Ratings"):
                if a.lower() in text: agency=a; break
            m=re.search(r"\(([A-Z&]{2,20})\)", title); ticker=m.group(1) if m else None
            old_r,new_r=_extract_ratings(f"{title} {summary}")
            action=_detect_action(old_r or "",new_r,f"{title} {summary}")
            amount=_parse_cr(f"{title} {summary}")
            outlook=("Negative" if "negative" in text else
                     "Positive" if "positive" in text else
                     "Watch"    if "watch"    in text else "Stable")
            instrument="NCD"
            for ins_kw,ins_v in [("commercial paper","CP"),("cp ","CP"),
                                  ("bank loan","Bank_Loan"),("bond","Bond"),("ncd","NCD")]:
                if ins_kw in text: instrument=ins_v; break
            company=re.sub(r"\s*\([A-Z&]+\)\s*","",title).strip()[:200]
            h=_hash(lnk,title)
            try:
                conn.execute("""INSERT OR IGNORE INTO credit_ratings
                    (hash,ticker,company_name,rating_agency,instrument,old_rating,new_rating,
                     rating_action,outlook,amount_cr,action_date,source_url)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (h,ticker,company,agency,instrument,old_r,new_r,action,outlook,amount,_now()[:10],lnk))
                if conn.execute("SELECT changes()").fetchone()[0]: ins+=1
            except sqlite3.IntegrityError: pass
    conn.commit(); logger.info("[ratings] %d",ins); return ins

NBFC_PEER=7.80; CORP_PEER=7.20
CP_KW=["commercial paper","cp issuance","ncd","bond issue","certificate of deposit",
       "nbfc","liquidity","money market","cd issuance","debt issue"]

def collect_cp(conn):
    ins=0
    fp=feedparser.parse("https://www.bseindia.com/data/xml/notices.xml")
    for e in fp.entries:
        title=e.get("title","").strip(); url=e.get("link","").strip()
        summary=BeautifulSoup(e.get("summary",""),"html.parser").get_text(" ",strip=True)[:500]
        text=f"{title} {summary}".lower()
        if not any(k in text for k in CP_KW): continue
        m=re.search(r"\(([A-Z&]{2,20})\)",title); ticker=m.group(1) if m else None
        issuer_type="Corp"
        for t in ["nbfc","hfc","mfi","housing finance","microfinance"]:
            if t in text: issuer_type="NBFC"; break
        for t in [" bank "," banking "]:
            if t in text: issuer_type="Bank"; break
        rate_m=re.search(r"(\d+\.\d+)\s*%",text); rate=float(rate_m.group(1)) if rate_m else 0.0
        fv=_parse_cr(f"{title} {summary}")
        tenor_m=re.search(r"(\d+)\s*(?:day|days)",text); tenor=int(tenor_m.group(1)) if tenor_m else 90
        peer=NBFC_PEER if issuer_type in("NBFC","HFC","MFI") else CORP_PEER
        spread=round((rate-peer)*100,1) if rate>0 else 0.0
        cp_type="CP"
        if "ncd" in text: cp_type="NCD"
        if "certificate of deposit" in text or " cd " in text: cp_type="CD"
        issuer=re.sub(r"\s*\([A-Z&]+\)\s*","",title).strip()[:200]
        h=_hash(url,title)
        try:
            conn.execute("""INSERT OR IGNORE INTO cp_issuances
                (hash,ticker,issuer_name,issuer_type,cp_type,face_value_cr,
                 issuance_rate,peer_spread_bps,tenor_days,issuance_date,source_url)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (h,ticker,issuer,issuer_type,cp_type,fv,rate,spread,tenor,_now()[:10],url))
            if conn.execute("SELECT changes()").fetchone()[0]: ins+=1
        except sqlite3.IntegrityError: pass
    conn.commit(); logger.info("[cp] %d",ins); return ins

CHARGE_KW=["charge creat","charge satisf","charge modif","secured creditor",
            "hypothecation","mortgage","debenture trust","charge register"]

def collect_cersai(conn):
    ins=0
    fp=feedparser.parse("https://www.bseindia.com/data/xml/notices.xml")
    for e in fp.entries:
        title=e.get("title","").strip(); url=e.get("link","").strip()
        summary=BeautifulSoup(e.get("summary",""),"html.parser").get_text(" ",strip=True)[:500]
        text=f"{title} {summary}".lower()
        if not any(k in text for k in CHARGE_KW): continue
        m=re.search(r"\(([A-Z&]{2,20})\)",title); ticker=m.group(1) if m else None
        ctype="CREATION"
        if "satisf" in text or "release" in text: ctype="SATISFACTION"
        elif "modif" in text: ctype="MODIFICATION"
        atype="Mixed"
        for at,kws in [("Immovable",["land","property","building","immovable"]),
                       ("Movable",["plant","machinery","vehicle","movable"]),
                       ("Receivables",["receivable","book debt","invoice"])]:
            if any(k in text for k in kws): atype=at; break
        amt=_parse_cr(f"{title} {summary}")
        company=re.sub(r"\s*\([A-Z&]+\)\s*","",title).strip()[:200]
        cred_m=re.search(r"(?:bank|trust|finance|creditor)[:\s]+([^,\n.]{5,50})",text)
        creditor=cred_m.group(1).strip().title() if cred_m else None
        h=_hash(url,title)
        try:
            conn.execute("""INSERT OR IGNORE INTO cersai_charges
                (hash,ticker,company_name,secured_creditor,charge_type,
                 asset_type,charge_amount_cr,charge_date,source_url)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (h,ticker,company,creditor,ctype,atype,amt,_now()[:10],url))
            if conn.execute("SELECT changes()").fetchone()[0]: ins+=1
        except sqlite3.IntegrityError: pass
    conn.commit(); logger.info("[cersai] %d",ins); return ins

CCIL_KW=["irs","interest rate swap","ois","ccs","cross currency","fx forward",
         "forward contract","hedge","otc derivative","bond derivative","forex derivative"]

def collect_ccil(conn):
    ins=0
    fp=feedparser.parse("https://www.bseindia.com/data/xml/notices.xml")
    for e in fp.entries:
        title=e.get("title","").strip(); url=e.get("link","").strip()
        summary=BeautifulSoup(e.get("summary",""),"html.parser").get_text(" ",strip=True)[:500]
        text=f"{title} {summary}".lower()
        if not any(k in text for k in CCIL_KW): continue
        m=re.search(r"\(([A-Z&]{2,20})\)",title); ticker=m.group(1) if m else None
        instr="OTC_BOND"
        for k,v in [("irs","IRS"),("ois","OIS"),("ccs","CCS"),("fx forward","FX_Forward"),("cross currency","CCS")]:
            if k in text: instr=v; break
        direction="NORMAL"
        if "pay fixed" in text: direction="PAY_FIXED"
        elif "rcv fixed" in text or "receive fixed" in text: direction="RCV_FIXED"
        elif "buy usd" in text or "buy dollar" in text: direction="BUY_USD"
        elif "sell usd" in text: direction="SELL_USD"
        htype="NEW"
        if "unwind" in text or "clos" in text: htype="UNWIND"
        elif "rollover" in text or "roll " in text: htype="ROLLOVER"
        notional=_parse_cr(f"{title} {summary}")
        flag="NORMAL"
        if htype=="UNWIND" and notional>500: flag="UNUSUAL_UNWIND"
        elif direction in("BUY_USD","SELL_USD") and notional>1000: flag="LARGE_USD_HEDGE"
        elif htype=="ROLLOVER": flag="RAPID_ROLLOVER"
        entity=re.sub(r"\s*\([A-Z&]+\)\s*","",title).strip()[:200]
        h=_hash(url,title)
        try:
            conn.execute("""INSERT OR IGNORE INTO ccil_derivatives
                (hash,ticker,entity_name,instrument_type,notional_cr,
                 hedge_direction,hedge_type,trade_date,pattern_flag,source_url)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (h,ticker,entity,instr,notional,direction,htype,_now()[:10],flag,url))
            if conn.execute("SELECT changes()").fetchone()[0]: ins+=1
        except sqlite3.IntegrityError: pass
    conn.commit(); logger.info("[ccil] %d",ins); return ins

RBI_KW=["sectoral credit","credit growth","npa","non-performing","banking sector",
        "stressed asset","slippage","credit offtake","bank credit","priority sector",
        "msme credit","retail credit","credit quality"]

SECTOR_MAP=[
    (["agriculture","agri","crop","kisan"],           "Agriculture"),
    (["msme","micro small","small enterprise"],        "MSME"),
    (["retail","personal loan","home loan","housing"], "Retail"),
    (["infrastructure","road","power","telecom"],      "Infrastructure"),
    (["industrial","industry","manufacturing"],        "Industry"),
    (["service","commercial real estate","cre"],       "Services"),
    (["nbfc","non-bank","shadow bank"],                "NBFC"),
    (["export","import","trade finance"],              "Trade"),
]

def _sector(text):
    tl=text.lower()
    for kws,s in SECTOR_MAP:
        if any(k in tl for k in kws): return s
    return "General"

def _pct(pattern,text):
    m=re.search(pattern,text); return float(m.group(1)) if m else 0.0

def collect_rbi_credit(conn):
    ins=0
    for url in ["https://www.rbi.org.in/rss/RBINotifications.xml",
                "https://www.rbi.org.in/rss/PressRelease.xml"]:
        try: fp=feedparser.parse(url)
        except: continue
        for e in fp.entries:
            title=e.get("title","").strip(); link=e.get("link","").strip()
            summary=BeautifulSoup(e.get("summary",e.get("description","")),"html.parser").get_text(" ",strip=True)[:800]
            text=f"{title} {summary}".lower()
            if not any(k in text for k in RBI_KW): continue
            sector=_sector(text)
            cg=_pct(r"credit\s+growth[^\d]*(\d+\.?\d*)\s*%",text)
            npa=_pct(r"npa[^\d]*(\d+\.?\d*)\s*%",text)
            slip=_pct(r"slippage[^\d]*(\d+\.?\d*)\s*%",text)
            stress=_pct(r"stressed[^\d]*(\d+\.?\d*)\s*%",text)
            pm=re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})",text)
            period=f"{pm.group(1)[:3].capitalize()} {pm.group(2)}" if pm else _now()[:7]
            h=_hash(link,title,sector)
            try:
                conn.execute("""INSERT OR IGNORE INTO rbi_credit_data
                    (hash,sector,credit_growth_pct,npa_ratio_pct,
                     slippage_ratio_pct,stressed_assets_pct,period,source_url)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (h,sector,cg,npa,slip,stress,period,link))
                if conn.execute("SELECT changes()").fetchone()[0]: ins+=1
            except sqlite3.IntegrityError: pass
    conn.commit(); logger.info("[rbi] %d",ins); return ins

def collect_all_credit(conn):
    logger.info("== Credit Collection START ==")
    r={"ratings":collect_ratings(conn),"cp":collect_cp(conn),
       "cersai":collect_cersai(conn),"ccil":collect_ccil(conn),
       "rbi_credit":collect_rbi_credit(conn)}
    logger.info("== Credit Collection END: %s ==",r); return r

if __name__=="__main__":
    import sys,os; sys.path.insert(0,os.path.join(os.path.dirname(__file__),".."))
    from db.schema import init_db; from db.credit_schema import extend_db_credit
    conn=init_db(); extend_db_credit(conn)
    print(collect_all_credit(conn)); conn.close()
