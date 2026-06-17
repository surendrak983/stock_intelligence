"""
digest.py — Morning digest generator + scheduler
Generates HTML email digest + runs cron-style scheduler for all pipeline jobs
"""

import json
import logging
import time
from datetime import datetime, date
from db import get_conn

logger = logging.getLogger("digest")


# ─────────────────────────────────────────────────────────────────────────────
# 1.  MORNING DIGEST (HTML report)
# ─────────────────────────────────────────────────────────────────────────────

SEVERITY_COLOR = {
    "CRITICAL": "#dc2626",
    "HIGH":     "#ea580c",
    "MEDIUM":   "#d97706",
    "LOW":      "#16a34a",
}

DIRECTION_BADGE = {
    "BULLISH":  ("▲", "#16a34a"),
    "BEARISH":  ("▼", "#dc2626"),
    "NEUTRAL":  ("◆", "#6b7280"),
    "WATCH":    ("⊙", "#d97706"),
}


def generate_html_digest(date_str: str = None) -> str:
    """Generate a full HTML morning digest for the given date."""
    today = date_str or date.today().isoformat()
    conn = get_conn()

    events = conn.execute("""
        SELECT c.*, r.source, r.source_type, r.title as raw_title,
               r.url, r.published_at
        FROM classified_events c
        JOIN raw_events r ON r.id = c.raw_event_id
        WHERE DATE(c.classified_at) >= DATE('now', '-1 day')
        ORDER BY c.severity_score DESC, c.classified_at DESC
        LIMIT 50
    """).fetchall()

    critical = [e for e in events if e["severity"] == "CRITICAL"]
    high      = [e for e in events if e["severity"] == "HIGH"]
    medium    = [e for e in events if e["severity"] == "MEDIUM"]
    low       = [e for e in events if e["severity"] == "LOW"]

    def event_row(e):
        sc = SEVERITY_COLOR.get(e["severity"], "#6b7280")
        da, dc = DIRECTION_BADGE.get(e["signal_direction"] or "NEUTRAL", ("◆","#6b7280"))
        ticker = e["ticker"] or "MARKET"
        return f"""
        <tr style="border-bottom:1px solid #f0f0f0">
          <td style="padding:8px 4px;font-weight:600;color:#1e3a5f">{ticker}</td>
          <td style="padding:8px 4px">
            <span style="background:{sc};color:white;padding:2px 8px;border-radius:12px;
                         font-size:11px;font-weight:600">{e["severity"]}</span>
          </td>
          <td style="padding:8px 4px;color:{dc};font-weight:700">{da} {e["signal_direction"] or "NEUTRAL"}</td>
          <td style="padding:8px 4px;font-size:12px;color:#374151">{e["summary"] or e["raw_title"] or ''}</td>
          <td style="padding:8px 4px;font-size:11px;color:#6b7280">{e["event_type"] or ''}</td>
          <td style="padding:8px 4px;font-size:11px;color:#6b7280">{e["source"] or ''}</td>
        </tr>"""

    all_rows = "".join(event_row(e) for e in events)
    critical_rows = "".join(event_row(e) for e in critical)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Indian Equity Regulatory Digest — {today}</title>
<style>
  body {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:#f8fafc;margin:0;padding:20px;color:#1e293b}}
  .container {{max-width:960px;margin:0 auto;background:white;border-radius:12px;
               box-shadow:0 2px 16px rgba(0,0,0,.08);overflow:hidden}}
  .header {{background:linear-gradient(135deg,#1e3a5f,#2563eb);
            color:white;padding:28px 32px}}
  .header h1 {{margin:0;font-size:22px;font-weight:700;letter-spacing:-.3px}}
  .header p  {{margin:6px 0 0;opacity:.8;font-size:13px}}
  .stats     {{display:flex;gap:16px;padding:20px 32px;background:#f8fafc;
               border-bottom:1px solid #e2e8f0}}
  .stat-box  {{flex:1;background:white;border-radius:8px;padding:14px 18px;
               box-shadow:0 1px 4px rgba(0,0,0,.05)}}
  .stat-val  {{font-size:28px;font-weight:700;line-height:1}}
  .stat-label{{font-size:12px;color:#64748b;margin-top:4px}}
  .section   {{padding:24px 32px}}
  .section h2{{font-size:15px;font-weight:700;color:#1e3a5f;margin:0 0 16px;
               border-left:4px solid #2563eb;padding-left:12px}}
  table      {{width:100%;border-collapse:collapse;font-size:13px}}
  th         {{text-align:left;padding:8px 4px;font-size:11px;color:#64748b;
               text-transform:uppercase;letter-spacing:.5px;border-bottom:2px solid #e2e8f0}}
  tr:hover   {{background:#f8fafc}}
  .footer    {{padding:20px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;
               font-size:12px;color:#94a3b8;text-align:center}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🇮🇳 Indian Equity — Regulatory Intelligence Digest</h1>
    <p>{today} · {len(events)} events processed · Generated {datetime.utcnow().strftime('%H:%M UTC')}</p>
  </div>

  <div class="stats">
    <div class="stat-box">
      <div class="stat-val" style="color:#dc2626">{len(critical)}</div>
      <div class="stat-label">CRITICAL</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:#ea580c">{len(high)}</div>
      <div class="stat-label">HIGH</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:#d97706">{len(medium)}</div>
      <div class="stat-label">MEDIUM</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:#16a34a">{len(low)}</div>
      <div class="stat-label">LOW</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:#2563eb">{len(events)}</div>
      <div class="stat-label">TOTAL EVENTS</div>
    </div>
  </div>

  {'<div class="section"><h2>🚨 CRITICAL ALERTS</h2><table><thead><tr><th>Ticker</th><th>Severity</th><th>Direction</th><th>Summary</th><th>Type</th><th>Source</th></tr></thead><tbody>' + critical_rows + '</tbody></table></div>' if critical else ''}

  <div class="section">
    <h2>📋 All Regulatory Events (Last 24h)</h2>
    <table>
      <thead>
        <tr>
          <th>Ticker</th><th>Severity</th><th>Direction</th>
          <th>Summary</th><th>Type</th><th>Source</th>
        </tr>
      </thead>
      <tbody>{all_rows}</tbody>
    </table>
  </div>

  <div class="footer">
    Regulatory Intelligence System · Indian Equity Markets · Auto-generated report<br>
    Data sources: SEBI EDGAR · NSE/BSE · MCA/ROC · RBI · NCLT · CRISIL/ICRA · News RSS
  </div>
</div>
</body>
</html>"""

    # Store in DB
    conn.execute("""
        INSERT OR REPLACE INTO digest_history
            (digest_date, content, events_count, critical_count)
        VALUES (?,?,?,?)
    """, (today, html, len(events), len(critical)))
    conn.commit()
    conn.close()
    return html


# ─────────────────────────────────────────────────────────────────────────────
# 2.  SCHEDULER (cron-style background runner)
# ─────────────────────────────────────────────────────────────────────────────

class PipelineScheduler:
    """
    Three job types mirroring the architecture diagram:
      - collect_and_classify  : every 15 min during market hours (9:00–16:00 IST)
      - overnight_scan        : every 60 min (16:00–08:00 IST)
      - morning_digest        : once daily at 07:50 IST
    """

    def __init__(self, demo_mode: bool = True, use_ai: bool = False):
        self.demo_mode = demo_mode
        self.use_ai = use_ai
        self._last_collect = 0.0
        self._last_overnight = 0.0
        self._last_digest_date = ""

    def _ist_hour(self) -> int:
        """Return current IST hour (UTC+5:30)."""
        now_utc = datetime.utcnow()
        ist_offset = 5 * 60 + 30
        total_min = now_utc.hour * 60 + now_utc.minute + ist_offset
        return (total_min // 60) % 24

    def _ist_minute(self) -> int:
        now_utc = datetime.utcnow()
        return (now_utc.minute + 30) % 60

    def run_once(self):
        """Run the collection + classification pipeline once (immediate)."""
        from collectors import run_collectors
        from classifier import classify_unprocessed
        logger.info("[Scheduler] Running pipeline once…")
        counts = run_collectors(demo_mode=self.demo_mode)
        logger.info(f"[Scheduler] Collected: {counts}")
        n = classify_unprocessed(use_ai=self.use_ai)
        logger.info(f"[Scheduler] Classified: {n}")
        return counts, n

    def run_continuous(self, max_iterations: int = None):
        """
        Blocking scheduler loop.
        Set max_iterations for testing; None = run forever.
        """
        logger.info("[Scheduler] Starting continuous pipeline…")
        iteration = 0
        while True:
            now = time.time()
            ist_h = self._ist_hour()
            ist_m = self._ist_minute()
            today = date.today().isoformat()

            # ── collect_and_classify every 15 min during market hours ──────
            market_hours = 9 <= ist_h < 16
            if market_hours and (now - self._last_collect) >= 15 * 60:
                logger.info(f"[Scheduler][{ist_h:02d}:{ist_m:02d} IST] collect_and_classify")
                self.run_once()
                self._last_collect = now

            # ── overnight_scan every 60 min off-hours ─────────────────────
            off_hours = ist_h >= 16 or ist_h < 8
            if off_hours and (now - self._last_overnight) >= 60 * 60:
                logger.info(f"[Scheduler][{ist_h:02d}:{ist_m:02d} IST] overnight_scan")
                self.run_once()
                self._last_overnight = now

            # ── morning_digest at 07:50 IST ───────────────────────────────
            if ist_h == 7 and ist_m >= 50 and self._last_digest_date != today:
                logger.info(f"[Scheduler][{ist_h:02d}:{ist_m:02d} IST] morning_digest")
                html = generate_html_digest()
                path = f"/tmp/digest_{today}.html"
                with open(path, "w") as f:
                    f.write(html)
                logger.info(f"[Scheduler] Digest saved → {path}")
                self._last_digest_date = today

            iteration += 1
            if max_iterations and iteration >= max_iterations:
                break
            time.sleep(30)   # tick every 30 s

        logger.info("[Scheduler] Stopped.")


# ─────────────────────────────────────────────────────────────────────────────
# 3.  CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    html = generate_html_digest()
    path = f"/tmp/digest_{date.today().isoformat()}.html"
    with open(path, "w") as f:
        f.write(html)
    print(f"[Digest] Saved → {path}")
