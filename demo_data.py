"""
demo_data.py — Realistic demo events covering ALL Regulatory tab sub-categories.
Each entry maps to a raw_event + a sub-domain table insert.
Run standalone:  python demo_data.py
"""
import hashlib, json, sqlite3
from datetime import date, datetime
from db import get_conn, init_db

# ── helpers ──────────────────────────────────────────────────────────────────
def h(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()

def ins_raw(conn, source, source_type, category, sub_cat, ticker, company,
            title, body, url=""):
    hsh = h(source, title, ticker or "")
    conn.execute("""
        INSERT OR IGNORE INTO raw_events
            (source,source_type,category,sub_category,ticker,company,
             title,body,url,event_hash,published_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
    """, (source,source_type,category,sub_cat,ticker,company,title,body,url,hsh))
    return conn.execute("SELECT id FROM raw_events WHERE event_hash=?",(hsh,)).fetchone()[0]

# ══════════════════════════════════════════════════════════════════════════════
#  SEBI EDGAR — Insider / SAST
# ══════════════════════════════════════════════════════════════════════════════
SEBI_EVENTS = [
    dict(ticker="RELIANCE",  company="Reliance Industries",
         title="SAST Reg 7(2): Promoter entity acquires 1.87% via open market",
         body="Reliance Industries Holdings Pvt Ltd acquired 1.87% additional stake. Post-acquisition promoter holding: 50.32%. Triggers SAST Reg 7(2) disclosure.",
         dtype="SAST_7_2", acquirer="Reliance Industries Holdings Pvt Ltd",
         acquirer_type="PROMOTER", pre=48.45, acq=1.87, post=50.32,
         txn="BUY", amt=4850.0),
    dict(ticker="WIPRO",     company="Wipro Ltd",
         title="PIT Reg: KMP disposal — CFO sells ₹45 Cr shares pre-earnings window",
         body="Jatin Dalal (CFO, Wipro) disposed 8,20,000 shares at avg ₹548. Trade executed 3 trading days before Q4 results. SEBI PIT compliance window closed.",
         dtype="PIT_INSIDER", acquirer="Jatin Dalal",
         acquirer_type="INDIVIDUAL", pre=0.014, acq=-0.008, post=0.006,
         txn="SELL", amt=44.9),
    dict(ticker="ADANIENT",  company="Adani Enterprises",
         title="SAST Reg 29(2): GQG Partners increases stake to 4.12%",
         body="GQG Partners LLC files Reg 29(2) — total holding crosses 4% threshold. Acquired additional 0.43% in open market on 14-Jun-2026.",
         dtype="SAST_29", acquirer="GQG Partners LLC",
         acquirer_type="FPI", pre=3.69, acq=0.43, post=4.12,
         txn="BUY", amt=1240.0),
    dict(ticker="BAJAJFINSV", company="Bajaj Finserv",
         title="Creeping Acquisition: Promoter increases stake by 0.97% (FY26 cumulative: 4.8%)",
         body="Bajaj Holdings & Investment crosses 4% creeping acquisition limit in financial year — mandatory open offer threshold under Reg 3(2) SAST triggered for evaluation.",
         dtype="CREEPING", acquirer="Bajaj Holdings & Investment Ltd",
         acquirer_type="PROMOTER", pre=60.71, acq=0.97, post=61.68,
         txn="BUY", amt=890.0),
    dict(ticker="ZOMATO",    company="Zomato Ltd",
         title="PIT: Pre-IPO investor Info Edge sells 2.3% stake — block deal",
         body="Info Edge (India) Ltd disposes 19,87,40,000 shares (2.27%) via block deal at ₹215/share. Post-disposal holding: 11.43%. Comply with PIT; trading window open.",
         dtype="PIT_INSIDER", acquirer="Info Edge India Ltd",
         acquirer_type="ENTITY", pre=13.70, acq=-2.27, post=11.43,
         txn="SELL", amt=4273.0),
]

# ══════════════════════════════════════════════════════════════════════════════
#  MCA / ROC — Corporate filings
# ══════════════════════════════════════════════════════════════════════════════
MCA_EVENTS = [
    dict(ticker="TATASTEEL",  company="Tata Steel Ltd",
         title="CHG-1: Charge creation ₹8,500 Cr — SBI consortium term loan",
         body="Tata Steel registers charge of ₹8,500 Cr in favour of SBI-led consortium for Kalinganagar Phase-2 expansion. Charge ID: 100867432.",
         cin="L27100MH1907PLC000260", form="CHG-1",
         desc="Term loan facility — Kalinganagar Phase 2 capex", amt=8500.0,
         holder="State Bank of India (consortium lead)"),
    dict(ticker="YESBANK",   company="Yes Bank Ltd",
         title="DIR-12: CEO Prashant Kumar reappointed; two independent directors retire",
         body="Yes Bank board approves reappointment of MD & CEO Prashant Kumar for 3-year term. ID Brahm Dutt and Maheswar Sahu retire by rotation — not seeking re-election.",
         cin="L65190MH2003PLC143249", form="DIR-12",
         desc="CEO reappointment + independent director cessation", amt=None,
         holder=None),
    dict(ticker="VEDL",      company="Vedanta Ltd",
         title="CHG-4: Charge satisfaction ₹3,200 Cr — prepayment of Barclays facility",
         body="Vedanta Ltd satisfies charge (ID: 100543210) on ₹3,200 Cr facility from Barclays Bank PLC post early repayment. Net debt reduction signal.",
         cin="L13209MH1965PLC291394", form="CHG-4",
         desc="Satisfaction of charge — Barclays revolving facility", amt=3200.0,
         holder="Barclays Bank PLC"),
    dict(ticker="HCLTECH",   company="HCL Technologies",
         title="MGT-14: Special resolution — ₹5,000 Cr NCD issuance approved",
         body="HCL Technologies shareholders approve issuance of up to ₹5,000 Cr NCDs via special resolution at EGM held 10-Jun-2026. Proceeds earmarked for working capital + acquisition funding.",
         cin="L74140DL1991PLC046369", form="MGT-14",
         desc="Special resolution for NCD issuance up to ₹5,000 Cr", amt=5000.0,
         holder=None),
    dict(ticker="PAYTM",    company="One97 Communications",
         title="AOC-4: Annual accounts FY25 filed — going-concern note by auditors",
         body="One97 Communications files AOC-4 for FY2024-25. Statutory auditor (SR Batliboi) includes emphasis-of-matter paragraph on continued losses and going-concern uncertainty in payments business.",
         cin="L72200DL2000PLC107997", form="AOC-4",
         desc="Annual accounts FY25 — auditor emphasis of matter (going concern)", amt=None,
         holder=None),
]

# ══════════════════════════════════════════════════════════════════════════════
#  NCLT / NCLAT — Insolvency
# ══════════════════════════════════════════════════════════════════════════════
INSOLVENCY_EVENTS = [
    dict(ticker="GTLINFRA",  company="GTL Infrastructure Ltd",
         title="NCLT Mumbai: IBC petition admitted — IDBI Bank (FC) ₹3,842 Cr",
         body="NCLT Mumbai Bench (IA 2341/2026) admits CIRP petition by IDBI Bank against GTL Infrastructure Ltd. Moratorium effective immediately. IRP: Anuj Jain.",
         case="IBA/56/2026/NCLT-MUM", bench="NCLT Mumbai",
         petitioner="IDBI Bank Ltd", ptype="FINANCIAL_CREDITOR",
         stage="ADMITTED", amt=3842.0, rp="Anuj Jain"),
    dict(ticker="RELCAP",   company="Reliance Capital Ltd",
         title="NCLAT: Administrator's resolution plan challenged by dissenting CoC member",
         body="Hinduja Group challenges NCLAT approval of IndusInd-backed resolution plan for Reliance Capital. NCLAT stay granted pending hearing on 20-Jun-2026.",
         case="CA/1124/2025/NCLAT", bench="NCLAT New Delhi",
         petitioner="Hinduja Group (dissenting CoC)", ptype="FINANCIAL_CREDITOR",
         stage="RESOLUTION", amt=23000.0, rp="Nageswara Rao Y"),
    dict(ticker="SREI",     company="SREI Infrastructure Finance",
         title="NCLT Kolkata: CIRP enters liquidation — no viable resolution plan received",
         body="NCLT Kolkata passes liquidation order for SREI Infrastructure Finance. All 10 resolution plans rejected by CoC. Liquidator: Mahesh Bhatt appointed.",
         case="CP/132/2021/NCLT-KOL", bench="NCLT Kolkata",
         petitioner="RBI (regulator-initiated)", ptype="FINANCIAL_CREDITOR",
         stage="LIQUIDATION", amt=31000.0, rp="Mahesh Bhatt (Liquidator)"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  CCI — M&A combination orders
# ══════════════════════════════════════════════════════════════════════════════
CCI_EVENTS = [
    dict(target_ticker="HDFCBANK", acquirer="HDFC Ltd", target="HDFC Bank Ltd",
         title="CCI approves HDFC-HDFC Bank merger — no conditions imposed",
         body="Competition Commission of India grants unconditional approval for amalgamation of HDFC Ltd into HDFC Bank. No substantive competition concern in retail banking or home loans market.",
         case="C-2022/08/942", order="APPROVAL", combo="MERGER", sector="Banking / NBFC",
         conditions=None),
    dict(target_ticker="CIPLA",   acquirer="Blackstone Group", target="Cipla Ltd",
         title="CCI: Blackstone 10.1% stake acquisition in Cipla — approved with monitoring",
         body="CCI approves Blackstone's acquisition of 10.1% stake in Cipla from promoters. Conditional on Blackstone not acquiring board representation beyond 1 nominee director for 3 years.",
         case="C-2026/03/1041", order="CONDITIONAL", combo="ACQUISITION", sector="Pharmaceuticals",
         conditions="Board nomination capped at 1; no veto rights on pricing/R&D"),
    dict(target_ticker="IRCTC",   acquirer="Railways Ministry / DIPAM", target="IRCTC",
         title="CCI notified: Government proposes further strategic divestment of IRCTC stake",
         body="DIPAM files combination notice with CCI for potential 10% stake sale in IRCTC via OFS. CCI review under 30-day clock. No horizontal/vertical competition overlap identified.",
         case="C-2026/05/1098", order="NOTICE", combo="ACQUISITION", sector="Transportation / Logistics",
         conditions=None),
]

# ══════════════════════════════════════════════════════════════════════════════
#  CRISIL / ICRA / CARE — Rating actions
# ══════════════════════════════════════════════════════════════════════════════
RATING_EVENTS = [
    dict(ticker="BAJFINANCE",  company="Bajaj Finance Ltd",
         agency="CRISIL", instr="NCD", rating="AAA", prev="AAA",
         outlook="STABLE", prev_outlook="STABLE", action="REAFFIRM",
         amt=25000.0,
         rationale="Strong capitalisation (CAR 24.8%), diversified AUM ₹3.4L Cr, best-in-class asset quality (GNPA 0.85%). No change in risk profile."),
    dict(ticker="YESBANK",    company="Yes Bank Ltd",
         agency="ICRA",   instr="BANK_LOAN", rating="BB+", prev="BBB-",
         outlook="NEGATIVE", prev_outlook="STABLE", action="DOWNGRADE",
         amt=18000.0,
         rationale="Continued stress in restructured book (18.2% of net advances). Capital adequacy under watch; government support no longer assumed post-reconstruction scheme completion."),
    dict(ticker="TATAMOTORS", company="Tata Motors Ltd",
         agency="CARE",   instr="NCD", rating="AA", prev="AA-",
         outlook="POSITIVE", prev_outlook="STABLE", action="UPGRADE",
         amt=8500.0,
         rationale="JLR turnaround materially complete; consolidated EBITDA margins at 14.2% vs 9.1% FY23. Net debt reduced by ₹22,000 Cr. EV transition on track."),
    dict(ticker="DLFINDIA",   company="DLF Ltd",
         agency="INDRA",  instr="BOND", rating="AA-", prev="AA-",
         outlook="POSITIVE", prev_outlook="STABLE", action="WATCH",
         amt=3000.0,
         rationale="Placed on Rating Watch Positive on back of strong pre-sales ₹14,778 Cr in FY26 and net debt-free consolidated balance sheet milestone. Formal upgrade review in 90 days."),
    dict(ticker="VEDL",       company="Vedanta Ltd",
         agency="CRISIL", instr="NCD", rating="A-", prev="A",
         outlook="NEGATIVE", prev_outlook="STABLE", action="DOWNGRADE",
         amt=12000.0,
         rationale="Holdco leverage elevated post ₹13,000 Cr dividend upstream to Vedanta Resources. Refinancing risk on $1.2Bn bond maturity in FY27 remains key monitorable."),
]

# ══════════════════════════════════════════════════════════════════════════════
#  Promoter Pledges
# ══════════════════════════════════════════════════════════════════════════════
PLEDGE_EVENTS = [
    dict(ticker="ADANIENT",  company="Adani Enterprises",
         title="Pledge invocation: Lender sells 1.2% pledged shares — margin call triggered",
         body="Deutsche Bank AG invokes pledge on 1,03,40,000 shares of Adani Enterprises held by promoter entity Emerging Markets Horizon Fund. Invocation at ₹2,340/share. Promoter pledge now 14.8% of total capital.",
         promoter="Emerging Markets Horizon Fund", event="INVOCATION",
         shares=1.034e7, pct_total=1.18, pct_promo=2.31, lender="Deutsche Bank AG"),
    dict(ticker="ZEEL",     company="Zee Entertainment",
         title="Pledge creation: Promoter pledges additional 3.4% for personal loan facility",
         body="Essel Group promoter entity creates fresh pledge on 3.4% (3,26,00,000 shares) in favour of IIFL Finance. Cumulative promoter pledge rises to 67.3% of promoter holding — elevated risk.",
         promoter="Essel Group Holdings", event="CREATION",
         shares=3.26e7, pct_total=3.40, pct_promo=67.3, lender="IIFL Finance Ltd"),
    dict(ticker="SUNPHARMA", company="Sun Pharmaceutical",
         title="Pledge release: Promoter Dilip Shanghvi releases entire pledge on 2.1% stake",
         body="Sun Pharma Industries promoter Dilip Shanghvi releases pledge on 2,51,20,000 shares from HDFC Bank. Promoter pledge now NIL. Full release — positive signal.",
         promoter="Dilip Shanghvi", event="RELEASE",
         shares=2.512e7, pct_total=2.08, pct_promo=0.0, lender="HDFC Bank Ltd"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  RBI Circulars
# ══════════════════════════════════════════════════════════════════════════════
RBI_EVENTS = [
    dict(ticker=None, circular="RBI/2026-27/34 DOR.STR.REC.12",
         title="RBI raises repo rate 25bps to 6.75% — MPC votes 4:2",
         body="Monetary Policy Committee raises policy repo rate by 25 basis points to 6.75%. SDF rate: 6.50%. MSF: 7.00%. GDP growth projection retained at 7.0%. CPI target: 4.5%.",
         cat="MONETARY_POLICY", sectors="Banking,NBFC,Real Estate,Auto",
         key="Repo: 6.50%→6.75%; SDF: 6.25%→6.50%; MSF: 6.75%→7.00%"),
    dict(ticker=None, circular="RBI/2026-27/41 FIDD.CO.Plan.BC.5",
         title="RBI mandates priority sector lending recalibration — NBFC targets tightened",
         body="RBI revises PSL targets for NBFCs with asset size >₹20,000 Cr. Agriculture subtype target raised from 8% to 10% of ANBC. Weaker/stressed sectors get enhanced sub-targets.",
         cat="NBFC", sectors="NBFC,Microfinance,Agriculture",
         key="PSL agri sub-target: 8%→10% for large NBFCs; compliance by Mar-2027"),
    dict(ticker=None, circular="RBI/2026-27/28 A.P.(DIR Series) Circ.4",
         title="FPI investment limit in corporate bonds revised to 15% of outstanding stock",
         body="RBI in consultation with SEBI raises FPI investment ceiling in corporate bonds from 9% to 15% of outstanding stock. Voluntary retention route (VRR) limit also raised.",
         cat="FPI_FDI", sectors="Banking,NBFC,Corporate Bonds",
         key="FPI corpbond limit: 9%→15%; VRR limit raised to ₹2.5L Cr"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  IRDAI / PFRDA
# ══════════════════════════════════════════════════════════════════════════════
IRDAI_EVENTS = [
    dict(ticker="LICI",    company="LIC of India",
         title="IRDAI Q4 FY26: LIC equity investment disclosure — ₹42,300 Cr deployed in equities",
         body="LIC discloses quarterly investment statement per Reg 9. Equity exposure: ₹42,300 Cr (new deployment FY26-Q4). Top additions: HDFC Bank, SBI, Infosys. Solvency ratio: 1.87x (min: 1.50x).",
         ftype="INVESTMENT_DISCLOSURE", reg="IRDAI",
         aum=1240000.0, solv=1.87),
    dict(ticker="SBILIFE", company="SBI Life Insurance",
         title="IRDAI penalty: SBI Life fined ₹50 Lakh for mis-selling ULIP products",
         body="IRDAI imposes ₹50 Lakh penalty on SBI Life Insurance for violation of IRDA (Protection of Policyholders' Interests) Regulations 2017 — mis-selling in bancassurance channel.",
         ftype="PENALTY", reg="IRDAI",
         aum=None, solv=None),
]

# ══════════════════════════════════════════════════════════════════════════════
#  DGFT / Customs — Trade signals
# ══════════════════════════════════════════════════════════════════════════════
TRADE_EVENTS = [
    dict(ticker="JSWSTEEL",  company="JSW Steel",
         title="Anti-dumping duty on hot-rolled steel from China extended 5 years",
         body="DGTR recommends extension of 18.9% anti-dumping duty on HR Coil/Sheet from China for 5 years. Final CBIC notification expected within 30 days. JSW Steel primary beneficiary.",
         stype="ANTI_DUMPING", product="Hot Rolled Coil / Sheet (Steel)",
         country="China", duty=18.9, direction="IMPORT"),
    dict(ticker="SUNPHARMA", company="Sun Pharmaceutical",
         title="DGFT: API import licence mandatory for 14 categories — tightening supply chain",
         body="DGFT notification mandates prior licence for import of 14 Active Pharmaceutical Ingredient categories from non-FTA countries. Affects Sun Pharma, Cipla, Dr Reddy's API procurement.",
         stype="IMPORT_LICENCE", product="Active Pharmaceutical Ingredients (API)",
         country="China / non-FTA", duty=None, direction="IMPORT"),
    dict(ticker="TATAPOWER", company="Tata Power",
         title="Safeguard duty on solar cells extended — 40% duty maintained for 2 years",
         body="CBIC extends 40% safeguard duty on solar cells and modules from China and Malaysia for 2 more years. Domestic manufacturers (Tata Power Solar, Waaree) primary beneficiaries.",
         stype="SAFEGUARD", product="Solar Cells and Modules",
         country="China, Malaysia", duty=40.0, direction="IMPORT"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  CERSAI / CCIL / NSE Bond — Credit market infrastructure
# ══════════════════════════════════════════════════════════════════════════════
CREDIT_INFRA_EVENTS = [
    dict(ticker="BAJFINANCE", company="Bajaj Finance Ltd",
         title="CERSAI: Charge creation on mortgage pool — ₹12,800 Cr securitisation",
         body="Bajaj Finance registers securitisation transaction on mortgage pool of ₹12,800 Cr with CERSAI. Senior tranche rated AAA by CRISIL. Pass-through certificate (PTC) issued to mutual funds.",
         rtype="SECURITISATION", asset="Mortgage / Home Loan Pool", amt=12800.0,
         creditor="HDFC Mutual Fund / Nippon MF (PTC holders)"),
    dict(ticker="IDFCFIRSTB",company="IDFC First Bank",
         title="NSE Bond: IDFC First Bank CP issuance — 8.45% rate vs peer avg 8.12%",
         body="IDFC First Bank issues ₹500 Cr commercial paper at 8.45% (91-day maturity). Peer NBFC-bank CP avg: 8.12%. Spread of 33bps signals mild liquidity stress — FY26 Q2 credit watch.",
         rtype="DEBT_ISSUANCE", instr="CP", coupon=8.45, mat="2026-09-12",
         size=500.0, rating="A1+", yield_=8.45),
    dict(ticker="TATASTEEL",  company="Tata Steel Ltd",
         title="CCIL: Tata Steel forex hedge — ₹4,200 Cr USD/INR forward sold",
         body="CCIL trade repository shows Tata Steel has sold $500M (₹4,200 Cr) USD/INR forward contracts maturing Dec-2026. Suggests management expects INR weakness — import cost hedging.",
         rtype="OTC_DERIVATIVE", asset="USD/INR Forward", amt=4200.0,
         creditor="Counterparty banks (aggregated CCIL data)"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  SEBI Enforcement Orders
# ══════════════════════════════════════════════════════════════════════════════
SEBI_ORDERS = [
    dict(ticker="NSE",      company="NSE Ltd",
         title="SEBI adjudication: NSE fined ₹200 Cr for co-location algorithm preferential access",
         body="SEBI adjudication order imposes ₹200 Cr penalty on NSE for systemic algo trading advantage given to select brokers via co-location facility during 2010-2015. MD & CEO debarred 3 years.",
         severity="CRITICAL"),
    dict(ticker="PCJEWELLER",company="PC Jeweller",
         title="SEBI ban: PC Jeweller promoters barred 5 years for fraudulent fund diversion",
         body="SEBI bans PC Jeweller and 13 related entities from securities market for 5 years for fraudulent diversion of funds raised via FPO. Penalty: ₹35 Cr. Case: WTM/ABN/IVD/2026.",
         severity="CRITICAL"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  Master inject function
# ══════════════════════════════════════════════════════════════════════════════
def inject_all():
    init_db()
    conn = get_conn()
    total = 0

    # ── SEBI EDGAR ───────────────────────────────────────────────────────────
    for ev in SEBI_EVENTS:
        rid = ins_raw(conn,"SEBI_EDGAR","PRIMARY","regulatory","insider_sast",
                     ev["ticker"],ev["company"],ev["title"],ev["body"])
        conn.execute("""
            INSERT OR IGNORE INTO sebi_disclosures
                (raw_event_id,ticker,company,disclosure_type,acquirer,acquirer_type,
                 pre_holding,acquired_pct,post_holding,transaction_type,amount_cr,
                 exchange,disclosed_on,filing_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (rid,ev["ticker"],ev["company"],ev["dtype"],ev["acquirer"],
              ev["acquirer_type"],ev["pre"],ev["acq"],ev["post"],
              ev["txn"],ev["amt"],"NSE/BSE",str(date.today()),h("sd",rid)))
        total += 1

    # ── MCA / ROC ────────────────────────────────────────────────────────────
    for ev in MCA_EVENTS:
        rid = ins_raw(conn,"MCA_ROC","PRIMARY","regulatory","corporate_filings",
                     ev["ticker"],ev["company"],ev["title"],ev["body"])
        conn.execute("""
            INSERT OR IGNORE INTO mca_filings
                (raw_event_id,cin,company,ticker,form_type,description,
                 charge_amount,charge_holder,event_date,filing_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (rid,ev["cin"],ev["company"],ev["ticker"],ev["form"],
              ev["desc"],ev.get("amt"),ev.get("holder"),str(date.today()),h("mca",rid)))
        total += 1

    # ── NCLT / NCLAT ─────────────────────────────────────────────────────────
    for ev in INSOLVENCY_EVENTS:
        rid = ins_raw(conn,"NCLT_ORDERS","PRIMARY","regulatory","insolvency",
                     ev["ticker"],ev["company"],ev["title"],ev["body"])
        conn.execute("""
            INSERT OR IGNORE INTO insolvency_tracker
                (raw_event_id,ticker,company,case_number,bench,petitioner,
                 petitioner_type,stage,insolvency_date,resolution_professional,
                 claim_amount_cr)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (rid,ev["ticker"],ev["company"],ev["case"],ev["bench"],
              ev["petitioner"],ev["ptype"],ev["stage"],str(date.today()),
              ev["rp"],ev["amt"]))
        total += 1

    # ── CCI ──────────────────────────────────────────────────────────────────
    for ev in CCI_EVENTS:
        rid = ins_raw(conn,"CCI_ORDERS","PRIMARY","regulatory","merger_approval",
                     ev["target_ticker"],ev["target"],ev["title"],ev["body"])
        conn.execute("""
            INSERT OR IGNORE INTO cci_orders
                (raw_event_id,case_number,acquirer,target,target_ticker,
                 order_type,combination_type,sector,order_date,conditions)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (rid,ev["case"],ev["acquirer"],ev["target"],ev["target_ticker"],
              ev["order"],ev["combo"],ev["sector"],str(date.today()),
              ev.get("conditions")))
        total += 1

    # ── Credit Ratings ───────────────────────────────────────────────────────
    for ev in RATING_EVENTS:
        rid = ins_raw(conn,"CRISIL_RAT","PRIMARY","credit","rating_action",
                     ev["ticker"],ev["company"],
                     f"{ev['agency']}: {ev['action']} — {ev['ticker']} {ev['instr']} {ev['rating']} ({ev['outlook']})",
                     ev["rationale"])
        conn.execute("""
            INSERT OR IGNORE INTO credit_ratings
                (raw_event_id,ticker,company,agency,instrument,rating,rating_prev,
                 outlook,outlook_prev,action,amount_cr,rating_date,rationale,filing_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (rid,ev["ticker"],ev["company"],ev["agency"],ev["instr"],
              ev["rating"],ev["prev"],ev["outlook"],ev["prev_outlook"],
              ev["action"],ev["amt"],str(date.today()),ev["rationale"],h("cr",rid)))
        total += 1

    # ── Promoter Pledges ─────────────────────────────────────────────────────
    for ev in PLEDGE_EVENTS:
        rid = ins_raw(conn,"NSE_PLEDGE","PRIMARY","regulatory","insider_pledge",
                     ev["ticker"],ev["company"],ev["title"],ev["body"])
        conn.execute("""
            INSERT OR IGNORE INTO promoter_pledges
                (raw_event_id,ticker,company,promoter_name,event_type,
                 shares_pledged,pledge_pct_total,pledge_pct_promo,lender,
                 pledge_date,filing_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (rid,ev["ticker"],ev["company"],ev["promoter"],ev["event"],
              ev["shares"],ev["pct_total"],ev["pct_promo"],ev["lender"],
              str(date.today()),h("pp",rid)))
        total += 1

    # ── RBI Circulars ────────────────────────────────────────────────────────
    for ev in RBI_EVENTS:
        rid = ins_raw(conn,"RBI_MASTER","PRIMARY","regulatory","monetary_policy",
                     None,None,ev["title"],ev["body"])
        conn.execute("""
            INSERT OR IGNORE INTO rbi_circulars
                (raw_event_id,circular_number,category,subject,impact_sectors,
                 issued_date,key_changes)
            VALUES (?,?,?,?,?,?,?)
        """, (rid,ev["circular"],ev["cat"],ev["title"],ev["sectors"],
              str(date.today()),ev["key"]))
        total += 1

    # ── IRDAI ────────────────────────────────────────────────────────────────
    for ev in IRDAI_EVENTS:
        rid = ins_raw(conn,"IRDAI_DISC","PRIMARY","regulatory","insurance_reg",
                     ev["ticker"],ev["company"],ev["title"],ev["body"])
        conn.execute("""
            INSERT OR IGNORE INTO irdai_filings
                (raw_event_id,ticker,company,filing_type,regulator,
                 aum_cr,solvency_ratio,filing_date,filing_hash)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (rid,ev["ticker"],ev["company"],ev["ftype"],ev["reg"],
              ev.get("aum"),ev.get("solv"),str(date.today()),h("irdai",rid)))
        total += 1

    # ── Trade signals ────────────────────────────────────────────────────────
    for ev in TRADE_EVENTS:
        rid = ins_raw(conn,"DGFT_NOTIF","SECONDARY","regulatory","trade_policy",
                     ev["ticker"],ev["company"],ev["title"],ev["body"])
        conn.execute("""
            INSERT OR IGNORE INTO trade_signals
                (raw_event_id,ticker,company,signal_type,product,country,
                 duty_pct,direction,effective_date,filing_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (rid,ev["ticker"],ev["company"],ev["stype"],ev["product"],
              ev["country"],ev.get("duty"),ev["direction"],
              str(date.today()),h("ts",rid)))
        total += 1

    # ── Credit market infra ──────────────────────────────────────────────────
    for ev in CREDIT_INFRA_EVENTS:
        rid = ins_raw(conn,"NSE_BOND","PRIMARY","credit","debt_issuance",
                     ev["ticker"],ev["company"],ev["title"],ev["body"])
        if ev["rtype"] == "DEBT_ISSUANCE":
            conn.execute("""
                INSERT OR IGNORE INTO debt_issuances
                    (raw_event_id,ticker,company,instrument,isin,coupon_pct,
                     maturity_date,issue_size_cr,credit_rating,issued_date,yield_pct)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (rid,ev["ticker"],ev["company"],ev["instr"],
                  h("isin",rid)[:12].upper(),ev["coupon"],
                  ev.get("mat"),ev["size"],ev.get("rating"),
                  str(date.today()),ev.get("yield_")))
        elif ev["rtype"] == "SECURITISATION":
            conn.execute("""
                INSERT OR IGNORE INTO securitisation_registry
                    (raw_event_id,ticker,company,registration_type,asset_class,
                     amount_cr,secured_creditor,registration_date,filing_hash)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (rid,ev["ticker"],ev["company"],"SECURITISATION",
                  ev["asset"],ev["amt"],ev["creditor"],
                  str(date.today()),h("sec",rid)))
        total += 1

    # ── SEBI Orders ──────────────────────────────────────────────────────────
    for ev in SEBI_ORDERS:
        ins_raw(conn,"SEBI_ORDERS","PRIMARY","regulatory","penalty_orders",
                ev["ticker"],ev["company"],ev["title"],ev["body"])
        total += 1

    conn.commit()
    conn.close()
    print(f"[Demo] Injected {total} events across all Regulatory sub-categories")
    return total

if __name__ == "__main__":
    inject_all()
