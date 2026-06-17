"""Credit & Debt Markets Digest — HTML report."""
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.schema import init_db

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

SEV_COLOR = {"CRITICAL":"#d93025","HIGH":"#e07b00","MEDIUM":"#1a73e8","LOW":"#5f6368"}
TYPE_ICON = {"RATING":"🏷️","CP_SPREAD":"💧","CERSAI":"🔒","DERIVATIVE":"📊","RBI_CREDIT":"🏦"}
TYPE_DESC = {
    "RATING":     "Rating action (CRISIL/ICRA/CARE) — leads equity by days–weeks",
    "CP_SPREAD":  "CP/CD spread over peer — NBFC liquidity stress early signal",
    "CERSAI":     "Charge creation/satisfaction — asset encumbrance indicator",
    "DERIVATIVE": "CCIL OTC hedging pattern — unusual corporate hedging activity",
    "RBI_CREDIT": "RBI sectoral credit — NPA leading indicator before NPLs surface",
}

def generate_credit_digest(conn, for_date=None):
    if not for_date:
        now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        for_date = now_ist.strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT signal_type, severity, ticker, company_name, reason, created_at
        FROM credit_alerts
        WHERE created_at >= date('now','-1 day')
        ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
                               WHEN 'MEDIUM' THEN 3 ELSE 4 END, signal_type
    """).fetchall()

    counts = {s: sum(1 for r in rows if r["severity"]==s)
              for s in ("CRITICAL","HIGH","MEDIUM","LOW")}

    cards = ""
    for r in [dict(x) for x in rows]:
        c = SEV_COLOR.get(r["severity"],"#333")
        icon = TYPE_ICON.get(r["signal_type"],"📌")
        name = r["company_name"] or r["ticker"] or "—"
        cards += f"""
        <div style="border-left:4px solid {c};background:#fff;padding:10px 14px;
                    margin-bottom:10px;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,.08)">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px;flex-wrap:wrap">
            <span style="font-weight:700;color:{c}">{r['severity']}</span>
            <span style="background:#f1f3f4;padding:2px 7px;border-radius:3px;font-size:11px">{icon} {r['signal_type']}</span>
            <span style="background:#e8eaf6;color:#283593;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600">{r['ticker'] or '—'}</span>
            <span style="color:#555;font-size:12px">{name}</span>
            <span style="margin-left:auto;font-size:11px;color:#999">{str(r['created_at'])[:16]}</span>
          </div>
          <div style="font-size:13px;color:#222;margin-bottom:3px">{r['reason']}</div>
          <div style="font-size:11px;color:#888;font-style:italic">{TYPE_DESC.get(r['signal_type'],'')}</div>
        </div>"""

    sr = "".join(f'<td style="text-align:center;padding:10px 18px"><div style="font-size:24px;font-weight:700;color:{SEV_COLOR[s]}">{counts[s]}</div><div style="font-size:11px;color:#666">{s}</div></td>'
                 for s in ("CRITICAL","HIGH","MEDIUM","LOW"))

    # RBI sector table
    sector_rows = conn.execute("""
        SELECT sector, credit_growth_pct, npa_ratio_pct, slippage_ratio_pct,
               stressed_assets_pct, period
        FROM rbi_credit_data ORDER BY npa_ratio_pct DESC LIMIT 6
    """).fetchall()
    sector_html = ""
    for s in [dict(x) for x in sector_rows]:
        npa_c = "#d93025" if s["npa_ratio_pct"]>=10 else ("#e07b00" if s["npa_ratio_pct"]>=7 else "#333")
        g_c   = "#d93025" if (s["credit_growth_pct"] or 0)<0 else "#2e7d32"
        sector_html += f"""<tr>
          <td style="padding:5px 10px;font-weight:600">{s['sector']}</td>
          <td style="padding:5px 10px;color:{g_c};text-align:right">{s['credit_growth_pct']:.1f}%</td>
          <td style="padding:5px 10px;color:{npa_c};text-align:right;font-weight:600">{s['npa_ratio_pct']:.1f}%</td>
          <td style="padding:5px 10px;text-align:right">{s['slippage_ratio_pct']:.1f}%</td>
          <td style="padding:5px 10px;text-align:right">{s['stressed_assets_pct']:.1f}%</td>
          <td style="padding:5px 10px;color:#777;font-size:11px">{s['period']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Credit & Debt Markets Digest — {for_date}</title></head>
<body style="font-family:Arial,sans-serif;background:#f4f6fb;padding:24px;margin:0">
<div style="max-width:800px;margin:0 auto">
  <div style="background:linear-gradient(135deg,#0d47a1,#1565c0);color:#fff;padding:20px 24px;border-radius:8px 8px 0 0">
    <h1 style="margin:0;font-size:20px">📊 Credit & Debt Markets Digest</h1>
    <p style="margin:4px 0 0;opacity:.8;font-size:13px">Indian Equity · {for_date} · {len(rows)} signals across 5 sources</p>
  </div>
  <div style="background:#fff;border-radius:0 0 8px 8px;margin-bottom:20px;box-shadow:0 2px 6px rgba(0,0,0,.1)">
    <table style="width:100%;border-collapse:collapse"><tr>{sr}</tr></table>
  </div>

  <!-- Source legend -->
  <div style="background:#e3f2fd;border:1px solid #90caf9;padding:10px 14px;border-radius:6px;font-size:12px;margin-bottom:16px;color:#555">
    🏷️ RATING — CRISIL/ICRA/CARE actions &nbsp;|&nbsp;
    💧 CP_SPREAD — NSE CP liquidity stress &nbsp;|&nbsp;
    🔒 CERSAI — Asset charge creation &nbsp;|&nbsp;
    📊 DERIVATIVE — CCIL OTC hedging patterns &nbsp;|&nbsp;
    🏦 RBI_CREDIT — Sectoral NPA / credit growth
  </div>

  <!-- Signal cards -->
  {'<p style="color:#777;text-align:center;padding:20px">No credit signals today.</p>' if not rows else cards}

  <!-- RBI Sector heatmap -->
  <div style="background:#fff;border-radius:8px;padding:16px;margin-top:20px;box-shadow:0 1px 4px rgba(0,0,0,.1)">
    <h3 style="margin:0 0 12px;font-size:14px;color:#0d47a1">🏦 RBI Sectoral Credit — Stress Dashboard</h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:#e3f2fd">
        <th style="padding:6px 10px;text-align:left">Sector</th>
        <th style="padding:6px 10px;text-align:right">Credit Growth</th>
        <th style="padding:6px 10px;text-align:right">Gross NPA</th>
        <th style="padding:6px 10px;text-align:right">Slippage</th>
        <th style="padding:6px 10px;text-align:right">Stressed</th>
        <th style="padding:6px 10px;text-align:right">Period</th>
      </tr></thead>
      <tbody>{sector_html}</tbody>
    </table>
  </div>

  <div style="font-size:11px;color:#aaa;text-align:center;margin-top:20px">
    Media Intelligence Layer · Phase 3 (Credit & Debt Markets) · {datetime.now().strftime('%Y-%m-%d %H:%M')} IST
  </div>
</div></body></html>"""

    out = OUTPUT_DIR / f"credit_digest_{for_date}.html"
    out.write_text(html, encoding="utf-8")
    return str(out)

if __name__ == "__main__":
    conn = init_db()
    p = generate_credit_digest(conn)
    print(f"Credit digest → {p}")
    conn.close()
