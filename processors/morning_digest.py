"""
Layer 3 — Output: Morning Digest
Generates an HTML email report of the last 24-hr events, ranked by severity.
Mirrors the '8 AM morning digest' node in the architecture.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("morning_digest")

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

SEVERITY_COLOR = {
    "CRITICAL": "#d93025",
    "HIGH":     "#e07b00",
    "MEDIUM":   "#1a73e8",
    "LOW":      "#5f6368",
}

TIER_BADGE = {
    "Primary":   ("#1b5e20", "#e8f5e9"),
    "Secondary": ("#e65100", "#fff3e0"),
    "Signal":    ("#4a148c", "#f3e5f5"),
}


def _badge(label: str, fg: str, bg: str) -> str:
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 7px;'
        f'border-radius:4px;font-size:11px;font-weight:600">{label}</span>'
    )


def generate_digest(conn: sqlite3.Connection, for_date: str | None = None) -> str:
    """
    Build HTML digest for `for_date` (YYYY-MM-DD).  Defaults to today (IST).
    Returns the HTML string and also saves it to outputs/.
    """
    if for_date is None:
        # IST = UTC+5:30
        now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        for_date = now_ist.strftime("%Y-%m-%d")

    since = f"{for_date} 00:00:00"
    until = f"{for_date} 23:59:59"

    rows = conn.execute(
        """
        SELECT
            e.id, e.title, e.summary, e.url, e.source_name, e.source_tier,
            e.tickers, e.event_type, e.published_at, e.raw_sentiment,
            a.severity, a.ticker, a.reason
        FROM alerts a
        JOIN events e ON a.event_id = e.id
        WHERE e.collected_at BETWEEN ? AND ?
        ORDER BY
            CASE a.severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH'     THEN 2
                WHEN 'MEDIUM'   THEN 3
                ELSE 4
            END,
            e.published_at DESC
        """,
        (since, until),
    ).fetchall()

    # De-duplicate by event id (multiple ticker rows)
    seen, items = set(), []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"])
            items.append(dict(r))

    counts = {s: sum(1 for i in items if i["severity"] == s)
              for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}

    # ── HTML ────────────────────────────────────────────────────────────────
    cards_html = ""
    for item in items:
        sev   = item["severity"]
        color = SEVERITY_COLOR.get(sev, "#333")
        tier  = item["source_tier"]
        tfg, tbg = TIER_BADGE.get(tier, ("#333", "#eee"))

        tickers = json.loads(item["tickers"] or "[]")
        ticker_chips = "".join(
            f'<span style="background:#e8eaf6;color:#283593;padding:1px 6px;'
            f'border-radius:3px;font-size:11px;margin-right:4px">{t}</span>'
            for t in tickers
        )

        sent  = item["raw_sentiment"] or 0.0
        sent_color = "#2e7d32" if sent > 0.1 else ("#c62828" if sent < -0.1 else "#555")
        sent_label = "▲ Positive" if sent > 0.1 else ("▼ Negative" if sent < -0.1 else "● Neutral")

        pub = (item["published_at"] or "")[:16].replace("T", " ")

        cards_html += f"""
        <div style="border-left:4px solid {color};background:#fff;
                    padding:12px 16px;margin-bottom:12px;border-radius:4px;
                    box-shadow:0 1px 3px rgba(0,0,0,.08)">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px">
            <span style="font-weight:700;color:{color};font-size:13px">{sev}</span>
            {_badge(tier, tfg, tbg)}
            {_badge(item['event_type'].upper(), '#37474f', '#eceff1')}
            {ticker_chips}
            <span style="margin-left:auto;font-size:11px;color:#777">{pub}</span>
          </div>
          <div style="font-weight:600;font-size:14px;color:#111;margin-bottom:4px">
            <a href="{item['url'] or '#'}" style="color:#111;text-decoration:none">
              {item['title']}
            </a>
          </div>
          <div style="font-size:12px;color:#555;margin-bottom:6px">
            {item['summary'][:300] if item['summary'] else ''}…
          </div>
          <div style="font-size:11px;color:#888">
            Source: <strong>{item['source_name']}</strong> &nbsp;|&nbsp;
            Sentiment: <span style="color:{sent_color}">{sent_label}</span> &nbsp;|&nbsp;
            Rule: {item['reason'] or '—'}
          </div>
        </div>"""

    summary_row = "".join(
        f'<td style="text-align:center;padding:8px 16px">'
        f'<div style="font-size:24px;font-weight:700;color:{SEVERITY_COLOR[s]}">{counts[s]}</div>'
        f'<div style="font-size:11px;color:#555">{s}</div></td>'
        for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Media Intelligence Digest — {for_date}</title>
</head>
<body style="font-family:Arial,sans-serif;background:#f4f6fb;padding:24px;margin:0">
  <div style="max-width:760px;margin:0 auto">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1a237e,#283593);
                color:#fff;padding:20px 24px;border-radius:8px 8px 0 0">
      <h1 style="margin:0;font-size:20px">📰 Media Intelligence Digest</h1>
      <p style="margin:4px 0 0;opacity:.8;font-size:13px">
        Indian Equity Market · {for_date} · {len(items)} events
      </p>
    </div>

    <!-- Summary counts -->
    <div style="background:#fff;border-radius:0 0 8px 8px;
                margin-bottom:20px;box-shadow:0 2px 6px rgba(0,0,0,.1)">
      <table style="width:100%;border-collapse:collapse">
        <tr>{summary_row}</tr>
      </table>
    </div>

    <!-- Event cards -->
    {'<p style="color:#777;text-align:center">No events collected for this date.</p>'
     if not items else cards_html}

    <!-- Footer -->
    <div style="font-size:11px;color:#aaa;text-align:center;margin-top:24px">
      Generated by Media Intelligence Layer · Phase 1 (Media Tab) ·
      {datetime.now().strftime('%Y-%m-%d %H:%M')} IST
    </div>
  </div>
</body>
</html>"""

    # Save
    out_path = OUTPUT_DIR / f"digest_{for_date}.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info("[digest] saved → %s  (%d events)", out_path, len(items))

    # Log to digest_history
    conn.execute(
        """INSERT INTO digest_history(digest_date, html_report, item_count)
           VALUES (?,?,?)""",
        (for_date, html, len(items)),
    )
    conn.commit()
    return str(out_path)


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from db.schema import init_db
    conn = init_db()
    path = generate_digest(conn)
    print(f"Digest → {path}")
    conn.close()
