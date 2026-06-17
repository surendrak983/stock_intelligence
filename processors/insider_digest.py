"""
Insider Signals Digest — generates HTML report for the morning digest.
Integrated into the same 8 AM delivery as Phase 1 media digest.
"""
import json, sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.schema import init_db

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

SEV_COLOR  = {"CRITICAL":"#d93025","HIGH":"#e07b00","MEDIUM":"#1a73e8","LOW":"#5f6368"}
TYPE_ICON  = {"INSIDER_TRADE":"💹","PLEDGE":"⛓️","QIB":"🏦","RPT":"🔗","DIRECTOR":"👤","AGM":"🗳️"}

def generate_insider_digest(conn, for_date=None):
    if for_date is None:
        now_ist = datetime.now(timezone.utc)+timedelta(hours=5,minutes=30)
        for_date = now_ist.strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT ia.signal_type, ia.severity, ia.ticker, ia.reason, ia.created_at
        FROM insider_alerts ia
        WHERE ia.created_at >= date('now','-1 day')
        ORDER BY CASE ia.severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
                                  WHEN 'MEDIUM' THEN 3 ELSE 4 END,
                 ia.ticker
    """).fetchall()

    counts = {s: sum(1 for r in rows if r["severity"]==s)
              for s in ("CRITICAL","HIGH","MEDIUM","LOW")}

    cards = ""
    for r in [dict(x) for x in rows]:
        c = SEV_COLOR.get(r["severity"],"#333")
        icon = TYPE_ICON.get(r["signal_type"],"📌")
        cards += f"""
        <div style="border-left:4px solid {c};background:#fff;padding:10px 14px;
                    margin-bottom:10px;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,.08)">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span style="font-weight:700;color:{c}">{r['severity']}</span>
            <span style="background:#f1f3f4;padding:2px 6px;border-radius:3px;font-size:11px">{icon} {r['signal_type']}</span>
            <span style="background:#e8eaf6;color:#283593;padding:2px 6px;border-radius:3px;font-size:11px;font-weight:600">{r['ticker'] or '—'}</span>
            <span style="margin-left:auto;font-size:11px;color:#999">{str(r['created_at'])[:16]}</span>
          </div>
          <div style="font-size:13px;color:#333">{r['reason']}</div>
        </div>"""

    summary_row = "".join(f'<td style="text-align:center;padding:8px 16px"><div style="font-size:22px;font-weight:700;color:{SEV_COLOR[s]}">{counts[s]}</div><div style="font-size:11px;color:#555">{s}</div></td>'
                          for s in ("CRITICAL","HIGH","MEDIUM","LOW"))

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Insider Signals Digest — {for_date}</title></head>
<body style="font-family:Arial,sans-serif;background:#f4f6fb;padding:24px;margin:0">
<div style="max-width:760px;margin:0 auto">
  <div style="background:linear-gradient(135deg,#1b5e20,#2e7d32);color:#fff;padding:20px 24px;border-radius:8px 8px 0 0">
    <h1 style="margin:0;font-size:20px">🔍 Insider & Ownership Signals Digest</h1>
    <p style="margin:4px 0 0;opacity:.8;font-size:13px">Indian Equity · {for_date} · {len(rows)} signals</p>
  </div>
  <div style="background:#fff;border-radius:0 0 8px 8px;margin-bottom:20px;box-shadow:0 2px 6px rgba(0,0,0,.1)">
    <table style="width:100%;border-collapse:collapse"><tr>{summary_row}</tr></table>
  </div>
  <div style="background:#fffde7;border:1px solid #f9a825;padding:10px 14px;border-radius:6px;font-size:12px;margin-bottom:16px;color:#555">
    <strong>Signal types:</strong>
    💹 INSIDER_TRADE — SEBI PIT/UPSI disclosures &nbsp;|&nbsp;
    ⛓️ PLEDGE — Promoter pledge stress &nbsp;|&nbsp;
    🏦 QIB — Institutional conviction &nbsp;|&nbsp;
    🔗 RPT — Related party risk &nbsp;|&nbsp;
    👤 DIRECTOR — MCA governance flags &nbsp;|&nbsp;
    🗳️ AGM — Minority dissent
  </div>
  {'<p style="color:#777;text-align:center">No insider signals for this date.</p>' if not rows else cards}
  <div style="font-size:11px;color:#aaa;text-align:center;margin-top:20px">
    Media Intelligence Layer · Phase 2 (Insider Signals) · {datetime.now().strftime('%Y-%m-%d %H:%M')} IST
  </div>
</div></body></html>"""

    out = OUTPUT_DIR / f"insider_digest_{for_date}.html"
    out.write_text(html, encoding="utf-8")
    return str(out)

if __name__ == "__main__":
    conn = init_db()
    p = generate_insider_digest(conn)
    print(f"Insider digest → {p}")
    conn.close()
