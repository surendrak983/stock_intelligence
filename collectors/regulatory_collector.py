"""
collectors.py v2 — Production collectors for all 26 Regulatory sources.
Each function documents:
  - The real endpoint / access method
  - Auth / session requirements
  - What to parse and where it goes
  - Fallback when blocked by CORS/auth

Run from India VPN or a server with Indian IP for best results.
"""
import hashlib, json, logging, re, urllib.request, urllib.error
from datetime import datetime, timezone, date
from typing import Optional
from db import get_conn

logger = logging.getLogger("collectors")

# ── Helpers ───────────────────────────────────────────────────────────────────
def h(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()

def ins_raw(conn, source, source_type, category, sub_cat,
            ticker, company, title, body, url="", pub=None):
    hsh = h(source, title, ticker or "")
    try:
        conn.execute("""
            INSERT OR IGNORE INTO raw_events
                (source,source_type,category,sub_category,ticker,company,
                 title,body,url,event_hash,published_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (source,source_type,category,sub_cat,ticker,company,
              title,body,url,hsh,pub or datetime.utcnow()))
        return conn.execute("SELECT id FROM raw_events WHERE event_hash=?",(hsh,)).fetchone()[0]
    except Exception as e:
        logger.error(f"ins_raw: {e}")
        return None

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-IN,en;q=0.9",
}

def fetch_json(url, extra_headers=None, timeout=15) -> Optional[dict]:
    """GET JSON endpoint. Returns None on any error."""
    hdrs = {**HEADERS, **(extra_headers or {})}
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.warning(f"fetch_json {url}: {e}")
        return None

def fetch_rss(url, timeout=15) -> list[dict]:
    """Parse RSS/Atom feed. Returns list of {title,url,summary,published}."""
    try:
        import feedparser
        feed = feedparser.parse(url)
        out = []
        for e in feed.entries:
            pub = None
            if hasattr(e,"published_parsed") and e.published_parsed:
                pub = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
            out.append({
                "title":   e.get("title",""),
                "url":     e.get("link",""),
                "summary": e.get("summary",""),
                "published": pub,
            })
        return out
    except Exception as e:
        logger.warning(f"fetch_rss {url}: {e}")
        return []

def ticker_from_text(text: str) -> Optional[str]:
    NSE = {
        "reliance industries":"RELIANCE","tata consultancy":"TCS",
        "hdfc bank":"HDFCBANK","icici bank":"ICICIBANK","infosys":"INFY",
        "state bank":"SBIN","wipro":"WIPRO","axis bank":"AXISBANK",
        "bajaj finance":"BAJFINANCE","bajaj finserv":"BAJAJFINSV",
        "larsen":"LT","itc limited":"ITC","kotak mahindra":"KOTAKBANK",
        "hcl tech":"HCLTECH","maruti suzuki":"MARUTI","sun pharma":"SUNPHARMA",
        "tata steel":"TATASTEEL","tata motors":"TATAMOTORS",
        "adani enterprises":"ADANIENT","adani ports":"ADANIPORTS",
        "bharti airtel":"BHARTIARTL","zomato":"ZOMATO","paytm":"PAYTM",
        "yes bank":"YESBANK","vedanta":"VEDL","jsw steel":"JSWSTEEL",
        "dlf":"DLFINDIA","lici":"LICI","sbi life":"SBILIFE",
        "idfc first":"IDFCFIRSTB","tata power":"TATAPOWER","cipla":"CIPLA",
        "irctc":"IRCTC","pc jeweller":"PCJEWELLER","zee entertainment":"ZEEL",
        "srei":"SREI","gtl infra":"GTLINFRA","reliance capital":"RELCAP",
    }
    low = text.lower()
    for name, tkr in NSE.items():
        if name in low:
            return tkr
    SYMBOLS = {"RELIANCE","TCS","HDFCBANK","ICICIBANK","INFY","SBIN","WIPRO",
               "AXISBANK","BAJFINANCE","LT","ITC","KOTAKBANK","HCLTECH",
               "MARUTI","SUNPHARMA","TATASTEEL","TATAMOTORS","ADANIENT",
               "ADANIPORTS","BHARTIARTL","ZOMATO","PAYTM","YESBANK","VEDL",
               "JSWSTEEL","DLFINDIA","LICI","SBILIFE","IDFCFIRSTB","TATAPOWER",
               "CIPLA","IRCTC","PCJEWELLER","ZEEL","SREI","GTLINFRA","RELCAP",
               "BAJAJFINSV","NTPC","ONGC","POWERGRID","COALINDIA","BPCL","IOC"}
    for sym in SYMBOLS:
        if re.search(rf"\b{sym}\b", text.upper()):
            return sym
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 1 — Regulatory & statutory filings
# ══════════════════════════════════════════════════════════════════════════════

def collect_sebi_edgar():
    """
    SEBI EDGAR — Insider trading, SAST, creeping acquisition filings.
    PRODUCTION:
      URL: https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doRecognisedFca=yes
      Auth: Session cookie from browser login; use requests.Session()
      Parser: HTML table scraper — each row = one disclosure
      Fields: entity name, PAN, acquirer type, pre/post holding, date
    FALLBACK: NSE bulk deal bhavcopy
      https://www.nseindia.com/api/block-deal
    """
    logger.info("[SEBI_EDGAR] collector — needs session cookie in prod; skipping live fetch")
    return 0

def collect_nse_announcements():
    """
    NSE Corporate Announcements — board meetings, results, director changes.
    PRODUCTION:
      Step 1: GET https://www.nseindia.com/api/home  (sets session cookie)
      Step 2: GET https://www.nseindia.com/api/corporate-announcements?index=equities
      Headers: Cookie from step 1, Referer: https://www.nseindia.com/
      Rate limit: ~60 req/min; parse 'symbol','desc','an_dt'
    """
    url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
    data = fetch_json(url, extra_headers={"Referer":"https://www.nseindia.com/"})
    if not data:
        return 0
    conn = get_conn()
    saved = 0
    for ann in (data if isinstance(data, list) else []):
        title   = ann.get("desc","") or ann.get("subject","")
        ticker  = (ann.get("symbol","") or "").upper() or ticker_from_text(title)
        company = ann.get("comp","")
        ins_raw(conn,"NSE_CORP","PRIMARY","regulatory","corp_announcement",
                ticker,company,title,"",ann.get("attchmntFile",""))
        saved += 1
    conn.commit(); conn.close()
    return saved

def collect_bse_announcements():
    """
    BSE Corporate Announcements API.
    PRODUCTION:
      URL: https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?...
      Headers: Referer: https://www.bseindia.com/
      Response: JSON with 'Table' key → list of announcements
      Fields: HEADLINE, Company_Name, SCRIP_CD, NEWS_DT, ATTACHMENTNAME
    """
    url = ("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?"
           "pageno=1&subcategory=&typecode=0&scrip_cd=&Action=0&"
           "Category=Corp+Act&Sch_Flg=1")
    data = fetch_json(url, extra_headers={"Referer":"https://www.bseindia.com/"})
    if not data or "Table" not in data:
        return 0
    conn = get_conn()
    saved = 0
    for ann in data.get("Table",[]):
        title  = ann.get("HEADLINE","") or ann.get("ANNSubject","")
        ticker = (ann.get("SCRIP_CD","") or ann.get("SYMBOL","") or "").upper()
        ins_raw(conn,"BSE_CORP","PRIMARY","regulatory","corp_announcement",
                ticker or ticker_from_text(title),
                ann.get("Company_Name",""), title, "", "")
        saved += 1
    conn.commit(); conn.close()
    return saved

def collect_mca_filings():
    """
    MCA21 v3 API — charge creation/satisfaction, director changes, annual filings.
    PRODUCTION:
      Endpoint: https://www.mca.gov.in/mcafoportal/viewChargeMaster.do
      Auth: MCA Data Services subscription (https://www.mca.gov.in/content/mca/global/en/mca/data-services.html)
      Bulk access: MCA Data Services API (paid, ₹5/query for individual or bulk extract)
      Alternatively scrape: https://efiling.mca.gov.in/efs-filing/recentlyfilings
      Key form types: CHG-1 (charge creation), CHG-4 (satisfaction), DIR-12 (director),
                      MGT-14 (resolutions), AOC-4 (accounts), MGT-7 (annual return)
    """
    logger.info("[MCA_ROC] collector — needs MCA Data Services subscription in prod")
    return 0

def collect_rbi_feeds():
    """
    RBI RSS feeds — press releases, circulars, monetary policy.
    PRODUCTION:
      URLs:
        Press releases: https://rbi.org.in/Scripts/Rss.aspx (open, no auth)
        Master circulars: https://rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx
    """
    conn = get_conn()
    saved = 0
    for url, sub in [
        ("https://rbi.org.in/Scripts/Rss.aspx", "monetary_policy"),
    ]:
        for item in fetch_rss(url):
            if not item["title"]:
                continue
            ins_raw(conn,"RBI_MASTER","PRIMARY","regulatory",sub,
                    None,None,item["title"],item.get("summary",""),
                    item.get("url",""),item.get("published"))
            saved += 1
    conn.commit(); conn.close()
    return saved

def collect_nclt_cases():
    """
    NCLT case registry — IBC admissions, liquidation orders.
    PRODUCTION:
      URL: https://nclt.gov.in/ → Cause List PDFs (bench-wise)
      Parser: PDF text extraction (pdfplumber) from daily cause list
      Key fields: case number, company, petitioner, bench, next date
      Alternative: ibbi.gov.in has structured CIRP data in downloadable Excel
        https://ibbi.gov.in/home/public-disclosure
        This is the BEST structured source — no auth needed.
    """
    # IBBI public disclosure — best free source for IBC data
    url = "https://ibbi.gov.in/home/public-disclosure"
    logger.info("[NCLT_ORDERS] IBBI public disclosure — use pdfplumber on downloaded Excel in prod")
    return 0

def collect_cci_orders():
    """
    CCI combination orders — M&A approvals, conditional approvals, rejections.
    PRODUCTION:
      URL: https://www.cci.gov.in/combination-orders
      Parser: HTML table → order date, parties, case number, type
      PDFs: each order links to PDF — extract conditions using pdfplumber
      No auth needed; public portal.
    """
    logger.info("[CCI_ORDERS] HTML scraper needed — use BeautifulSoup on combination-orders page")
    return 0

def collect_sebi_orders():
    """
    SEBI Enforcement / Adjudication Orders.
    PRODUCTION:
      URL: https://www.sebi.gov.in/enforcement/orders/
      Filter: Date range, category (adjudication / settlement / show cause)
      Parser: HTML table; each row → entity, order date, penalty, type
      No auth needed; public portal.
    """
    logger.info("[SEBI_ORDERS] HTML scraper needed — use BeautifulSoup on enforcement/orders page")
    return 0

def collect_dgft_notifications():
    """
    DGFT trade notifications — import/export licences, anti-dumping.
    PRODUCTION:
      URL: https://www.dgft.gov.in/CP/?opt=notification
      Also: https://www.cbic.gov.in/entities/notification (Customs notifications)
      Parser: HTML table; gazette notification number, subject, date, product/sector
      Key signals: anti-dumping duty rates, safeguard duties, FTP policy changes
    """
    logger.info("[DGFT_NOTIF] HTML scraper needed — paginated notification tables")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 2 — Credit & debt markets
# ══════════════════════════════════════════════════════════════════════════════

def collect_credit_ratings():
    """
    CRISIL / ICRA / CARE / India Ratings — rating actions.
    PRODUCTION:
      CRISIL: https://www.crisil.com/en/home/our-businesses/ratings/credit-ratings-news.html
              HTML scraper; each card = rating action (upgrade/downgrade/reaffirm)
      ICRA:   https://www.icra.in/Rationale/Index/  — HTML table with PDF rationale
      CARE:   https://www.careratings.com/        — press release listing
      IndRa:  https://www.indiaratings.co.in/      — structured news feed

      BEST APPROACH: Subscribe to CRISIL Data Terminal or
        use https://api.ratingsdirect.com (S&P/CRISIL joint) for structured data.
      FREE PROXY: NSE filing search for "rating reaffirmation" announcements
        (companies are required to disclose rating actions via stock exchange).
    """
    # Try NSE announcements with rating filter
    url = ("https://www.nseindia.com/api/corporate-announcements?"
           "index=equities&category=-1")
    data = fetch_json(url, extra_headers={"Referer":"https://www.nseindia.com/"})
    if not data:
        logger.info("[CRISIL_RAT] NSE session needed — use session cookie in prod")
        return 0
    conn = get_conn()
    saved = 0
    rating_kws = {"rating","crisil","icra","care ratings","downgrad","upgrad","reaffirm"}
    for ann in (data if isinstance(data,list) else []):
        title = (ann.get("desc","") or "").lower()
        if any(k in title for k in rating_kws):
            ins_raw(conn,"CRISIL_RAT","PRIMARY","credit","rating_action",
                    (ann.get("symbol","") or "").upper(),
                    ann.get("comp",""),ann.get("desc",""),"")
            saved += 1
    conn.commit(); conn.close()
    return saved

def collect_nse_bond():
    """
    NSE Bond / CP Platform — commercial paper issuances, NCD listings.
    PRODUCTION:
      URL: https://www.nseindia.com/market-data/bonds-trading-information
      Session required (same cookie approach as corporate announcements)
      Endpoint: https://www.nseindia.com/api/allBonds-traded-archive
      Fields: symbol, isin, coupon, maturity, last_yield, issue_size
      CP rate vs peer: compare 91-day CP rate of NBFCs for liquidity stress signal
    """
    logger.info("[NSE_BOND] NSE session cookie required — same flow as collect_nse_announcements")
    return 0

def collect_cersai():
    """
    CERSAI — Central Registry of Securitisation.
    PRODUCTION:
      URL: https://www.cersai.org.in/CERSAI/home.prg
      Auth: Subscriber login (banks / NBFCs / regulators get access)
      API: REST API available for registered subscribers
      Alternative: Charge information also available via MCA21 (CHG-1/CHG-4 forms)
      Signal value: New charge creation = borrowing; charge satisfaction = debt repayment
    """
    logger.info("[CERSAI_REG] Subscriber login required — use MCA CHG forms as free proxy")
    return 0

def collect_ccil():
    """
    CCIL Trade Repository — OTC bond/forex derivatives.
    PRODUCTION:
      URL: https://www.ccilindia.com/web/ccil/tri
      Auth: CCIL member access (banks have automatic access)
      Data: Aggregated (not entity-level) OTC data is publicly available
        https://www.ccilindia.com/web/ccil/trade-reporting-statistics
      Signal: Spike in corporate FX hedges = forex risk concern
               Large bond forward sales = bearish on interest rates
    """
    logger.info("[CCIL_REPO] Aggregated public stats at ccilindia.com/tri; entity-level needs membership")
    return 0

def collect_rbi_credit_data():
    """
    RBI sectoral bank credit — monthly data by industry.
    PRODUCTION:
      URL: https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx
      Look for: 'Sectoral Deployment of Bank Credit' press releases (monthly)
      Data: Excel attachment with credit to industry, services, personal loans
      Signal: YoY credit growth by sector before NPAs surface
      Direct data: https://dbie.rbi.org.in/DBIE/dbie.rbi?site=statistics (DBIE portal)
    """
    for item in fetch_rss("https://rbi.org.in/Scripts/Rss.aspx"):
        if "credit" in item.get("title","").lower() or "deployment" in item.get("title","").lower():
            conn = get_conn()
            ins_raw(conn,"RBI_CREDIT","SECONDARY","credit","bank_credit",
                    None,None,item["title"],item.get("summary",""),
                    item.get("url",""),item.get("published"))
            conn.commit(); conn.close()
    return 0

def collect_promoter_pledges():
    """
    Promoter pledge disclosures — NSE/BSE dedicated pledge data.
    PRODUCTION:
      NSE: https://www.nseindia.com/api/corporates-pledgedata?index=equities
           Session cookie required; returns pledge_pct, lender, date
      BSE: https://www.bseindia.com/corporates/pledgedata.html
           HTML scraper
      Gazette: Regulation 31(1) SEBI (SAST) — disclosed within 7 days of event
      Key signals:
        - Pledge creation by promoter → funding stress
        - Pledge invocation (lender sells) → forced selling pressure
        - Pledge % > 50% of promoter holding → HIGH risk flag
        - Pledge release → positive deleveraging signal
    """
    url = "https://www.nseindia.com/api/corporates-pledgedata?index=equities"
    data = fetch_json(url, extra_headers={"Referer":"https://www.nseindia.com/"})
    if not data:
        logger.info("[NSE_PLEDGE] NSE session cookie required in prod")
        return 0
    conn = get_conn()
    saved = 0
    for p in (data if isinstance(data,list) else []):
        ticker = (p.get("symbol","") or "").upper()
        title  = (f"Pledge {p.get('event_type','event')} — {ticker}: "
                  f"{p.get('pledge_pct',0):.2f}% of capital")
        ins_raw(conn,"NSE_PLEDGE","PRIMARY","regulatory","insider_pledge",
                ticker, p.get("company",""), title, json.dumps(p))
        saved += 1
    conn.commit(); conn.close()
    return saved

def collect_shareholding_patterns():
    """
    BSE Shareholding Patterns — quarterly SHP submissions.
    PRODUCTION:
      URL: https://www.bseindia.com/corporates/shpIndividual.html
      Direct data endpoint (POST): https://api.bseindia.com/BseIndiaAPI/api/SHP/w
      Body: {"scripcode":"500325","qtrid":"2024Q4"}
      Fields: promoter_holding, fpi_holding, dii_holding, public_holding, pledge_pct
      Frequency: Quarterly (within 21 days of quarter end)
      Key signals:
        - Promoter holding < 26% → loss of special resolution veto
        - FPI holding change → institutional sentiment
        - DII increase → domestic institutional accumulation
    """
    logger.info("[BSE_SHP] BSE API accessible with Referer header; parse quarterly SHP by scrip code")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 3 — News / Media (Signal layer)
# ══════════════════════════════════════════════════════════════════════════════

NEWS_FEEDS = [
    ("ET_MARKETS",   "ET Markets",
     "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "SIGNAL"),
    ("LIVEMINT",     "LiveMint Companies",
     "https://www.livemint.com/rss/companies", "SIGNAL"),
    ("MONEYCONTROL", "MoneyControl Business",
     "https://www.moneycontrol.com/rss/business.xml", "SIGNAL"),
    ("BS_MARKETS",   "Business Standard Markets",
     "https://www.business-standard.com/rss/markets-106.rss", "SIGNAL"),
    ("CNBCTV18",     "CNBC TV18 Markets",
     "https://www.cnbctv18.com/rss/market.xml", "SIGNAL"),
    ("HINDUBIZLINE", "Hindu BusinessLine",
     "https://www.thehindubusinessline.com/rss/markets/", "SIGNAL"),
]

def collect_news_rss():
    conn = get_conn()
    saved = 0
    for sid, label, url, stype in NEWS_FEEDS:
        for item in fetch_rss(url):
            if not item["title"]:
                continue
            ticker = ticker_from_text(item["title"]+" "+item.get("summary",""))
            ins_raw(conn, sid, stype, "news", "media_signal",
                    ticker, None, item["title"],
                    item.get("summary",""), item.get("url",""),
                    item.get("published"))
            saved += 1
    conn.commit(); conn.close()
    return saved


# ══════════════════════════════════════════════════════════════════════════════
#  Master runner
# ══════════════════════════════════════════════════════════════════════════════

def run_collectors(demo_mode=False):
    """Run all collectors. demo_mode uses pre-injected demo data."""
    if demo_mode:
        from demo_data import inject_all
        return {"DEMO": inject_all()}

    results = {}
    results["NSE_CORP"]   = collect_nse_announcements()
    results["BSE_CORP"]   = collect_bse_announcements()
    results["RBI_MASTER"] = collect_rbi_feeds()
    results["RBI_CREDIT"] = collect_rbi_credit_data()
    results["NEWS_RSS"]   = collect_news_rss()
    results["CRISIL_RAT"] = collect_credit_ratings()
    results["NSE_PLEDGE"] = collect_promoter_pledges()
    # Stubs (require auth / scraper setup):
    for src in ["SEBI_EDGAR","MCA_ROC","NCLT_ORDERS","CCI_ORDERS",
                "SEBI_ORDERS","DGFT_NOTIF","NSE_BOND","CERSAI_REG",
                "CCIL_REPO","BSE_SHP","IRDAI_DISC"]:
        results[src] = 0  # replace 0 with function call once auth configured

    return results

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from db import init_db; init_db()
    r = run_collectors(demo_mode=False)
    print("[Collectors] Results:", r)
