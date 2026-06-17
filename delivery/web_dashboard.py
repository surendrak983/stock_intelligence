"""
delivery/web_dashboard.py — Flask live-feed dashboard at localhost:5000
Run standalone:  python delivery/web_dashboard.py
Or called from main.py:  python main.py dashboard
"""
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (DASHBOARD_HOST, DASHBOARD_PORT, DASHBOARD_DEBUG,
                    MEDIA_DB_PATH, REGULATORY_DB_PATH)
from db import get_media_conn

try:
    from flask import Flask, jsonify, render_template_string, request
    FLASK_OK = True
except ImportError:
    FLASK_OK = False

app = Flask(__name__) if FLASK_OK else None

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stock Intelligence — Live Dashboard</title>
<style>
  :root{--bg:#0f1117;--card:#1a1d27;--border:#2a2d3a;--text:#e2e8f0;--muted:#64748b;
        --c:#ef4444;--h:#f97316;--m:#3b82f6;--l:#22c55e;--accent:#6366f1}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:-apple-system,sans-serif;font-size:14px}
  header{background:var(--card);border-bottom:1px solid var(--border);
         padding:14px 24px;display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:10}
  header h1{font-size:18px;font-weight:700;color:#fff}
  .live-dot{width:8px;height:8px;border-radius:50%;background:#22c55e;
             animation:pulse 1.5s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
  .main{display:grid;grid-template-columns:220px 1fr;min-height:100vh}
  .sidebar{background:var(--card);border-right:1px solid var(--border);padding:16px}
  .sidebar h3{font-size:11px;text-transform:uppercase;letter-spacing:.8px;
               color:var(--muted);margin-bottom:10px}
  .stat{background:var(--bg);border:1px solid var(--border);border-radius:8px;
         padding:12px;margin-bottom:8px;text-align:center}
  .stat-val{font-size:28px;font-weight:700}
  .stat-label{font-size:10px;color:var(--muted);margin-top:2px;text-transform:uppercase}
  .c{color:var(--c)}.h{color:var(--h)}.m{color:var(--m)}.l{color:var(--l)}
  .content{padding:20px}
  .filters{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
  .pill{padding:5px 14px;border-radius:20px;border:1px solid var(--border);
         background:var(--card);color:var(--muted);cursor:pointer;font-size:12px;transition:.15s}
  .pill.active{background:var(--accent);color:#fff;border-color:var(--accent)}
  #feed{display:flex;flex-direction:column;gap:8px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:8px;
         padding:14px 16px;transition:.15s}
  .card:hover{border-color:#4a4d5a}
  .card-top{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}
  .badge{font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px}
  .badge-CRITICAL{background:#7f1d1d;color:#fca5a5}
  .badge-HIGH{background:#7c2d12;color:#fdba74}
  .badge-MEDIUM{background:#1e3a5f;color:#93c5fd}
  .badge-LOW{background:#14532d;color:#86efac}
  .badge-src{background:#1e1b4b;color:#a5b4fc;font-weight:400}
  .ticker-chip{background:#1e293b;color:#94a3b8;padding:2px 7px;
                border-radius:4px;font-size:11px;font-family:monospace}
  .card-title{font-size:13px;font-weight:600;color:#f1f5f9;margin-bottom:4px}
  .card-summary{font-size:12px;color:var(--muted);line-height:1.5}
  .card-meta{font-size:10px;color:#4b5563;margin-top:6px}
  .ts{margin-left:auto;font-size:10px;color:var(--muted)}
  .empty{text-align:center;color:var(--muted);padding:60px;font-size:13px}
  .refresh-bar{position:fixed;bottom:0;left:0;right:0;background:var(--card);
                border-top:1px solid var(--border);padding:8px 24px;
                font-size:11px;color:var(--muted);display:flex;gap:16px;align-items:center}
  a{color:#818cf8;text-decoration:none}a:hover{text-decoration:underline}
  .tab-row{display:flex;gap:4px;margin-bottom:16px}
  .tab{padding:6px 16px;border-radius:6px;cursor:pointer;font-size:12px;
        border:1px solid var(--border);background:var(--card);color:var(--muted)}
  .tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
</style>
</head>
<body>
<header>
  <span class="live-dot"></span>
  <h1>🇮🇳 Stock Intelligence — Live Dashboard</h1>
  <span style="margin-left:auto;font-size:12px;color:var(--muted)" id="clock"></span>
</header>

<div class="main">
  <div class="sidebar">
    <h3>Last 24h</h3>
    <div class="stat"><div class="stat-val c" id="cnt-c">—</div><div class="stat-label">CRITICAL</div></div>
    <div class="stat"><div class="stat-val h" id="cnt-h">—</div><div class="stat-label">HIGH</div></div>
    <div class="stat"><div class="stat-val m" id="cnt-m">—</div><div class="stat-label">MEDIUM</div></div>
    <div class="stat"><div class="stat-val l" id="cnt-l">—</div><div class="stat-label">LOW</div></div>
    <hr style="border-color:var(--border);margin:16px 0">
    <h3>Watchlist</h3>
    <div id="watchlist" style="font-size:12px;line-height:2;color:var(--muted)">Loading…</div>
  </div>

  <div class="content">
    <div class="tab-row">
      <div class="tab active" onclick="switchTab('media',this)">📰 Media</div>
      <div class="tab" onclick="switchTab('insider',this)">🔒 Insider</div>
      <div class="tab" onclick="switchTab('credit',this)">💳 Credit</div>
      <div class="tab" onclick="switchTab('history',this)">📋 History</div>
    </div>

    <div class="filters">
      <span class="pill active" data-f="ALL" onclick="setFilter(this)">All</span>
      <span class="pill" data-f="CRITICAL" onclick="setFilter(this)">🚨 Critical</span>
      <span class="pill" data-f="HIGH" onclick="setFilter(this)">⚠️ High</span>
      <span class="pill" data-f="MEDIUM" onclick="setFilter(this)">📌 Medium</span>
    </div>

    <div id="feed"><div class="empty">Loading…</div></div>
  </div>
</div>

<div class="refresh-bar">
  <span>Auto-refresh: 60s</span>
  <span id="last-refresh"></span>
  <span style="margin-left:auto">
    <a href="/api/alerts">JSON API</a> &nbsp;|&nbsp;
    <a href="/api/digest/latest">Latest Digest</a>
  </span>
</div>

<script>
let currentTab='media', currentFilter='ALL', allData=[];

function switchTab(tab, el){
  currentTab=tab;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  fetchData();
}

function setFilter(el){
  currentFilter=el.dataset.f;
  document.querySelectorAll('.pill').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');
  renderFeed(allData);
}

function badge(cls,txt){return `<span class="badge badge-${cls}">${txt}</span>`}
function chip(t){return `<span class="ticker-chip">${t}</span>`}

function renderCard(item){
  const tickers=(item.tickers||[]).map(chip).join('');
  const url=item.url?`<a href="${item.url}" target="_blank">↗</a>`:'';
  return `<div class="card">
    <div class="card-top">
      ${badge(item.severity,item.severity)}
      <span class="badge badge-src">${item.source||item.signal_type||''}</span>
      ${tickers}
      <span class="ts">${(item.published_at||item.created_at||'').slice(0,16).replace('T',' ')}</span>
    </div>
    <div class="card-title">${item.title||item.reason||''} ${url}</div>
    <div class="card-summary">${(item.summary||item.company_name||'').slice(0,280)}</div>
    <div class="card-meta">Type: ${item.event_type||item.signal_type||'—'} &nbsp;|&nbsp; Score: ${item.severity_score||'—'}</div>
  </div>`;
}

function renderFeed(data){
  allData=data;
  const filtered=currentFilter==='ALL'?data:data.filter(d=>d.severity===currentFilter);
  const feed=document.getElementById('feed');
  if(!filtered.length){feed.innerHTML='<div class="empty">No events matching filter.</div>';return;}
  feed.innerHTML=filtered.map(renderCard).join('');
}

async function fetchData(){
  const url=`/api/${currentTab}?limit=80`;
  try{
    const r=await fetch(url); const d=await r.json();
    renderFeed(d.items||d||[]);
    if(d.counts){
      document.getElementById('cnt-c').textContent=d.counts.CRITICAL||0;
      document.getElementById('cnt-h').textContent=d.counts.HIGH||0;
      document.getElementById('cnt-m').textContent=d.counts.MEDIUM||0;
      document.getElementById('cnt-l').textContent=d.counts.LOW||0;
    }
    document.getElementById('last-refresh').textContent='Refreshed: '+new Date().toLocaleTimeString();
  }catch(e){console.error(e);}
}

async function fetchWatchlist(){
  try{
    const r=await fetch('/api/watchlist'); const d=await r.json();
    document.getElementById('watchlist').innerHTML=
      (d||[]).slice(0,15).map(t=>`<div>${t}</div>`).join('');
  }catch(e){}
}

function updateClock(){
  document.getElementById('clock').textContent=
    new Date().toLocaleString('en-IN',{timeZone:'Asia/Kolkata',
      hour:'2-digit',minute:'2-digit',second:'2-digit',
      day:'2-digit',month:'short'}) + ' IST';
}

setInterval(updateClock,1000);
setInterval(fetchData,60000);
fetchData(); fetchWatchlist(); updateClock();
</script>
</body>
</html>"""


if FLASK_OK:
    @app.route("/")
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/alerts")
    def api_alerts():
        conn = get_media_conn()
        limit = int(request.args.get("limit", 50))
        rows = conn.execute("""
            SELECT e.title, e.summary, e.url, e.source_name as source,
                   e.event_type, e.published_at, e.tickers, e.severity_score,
                   a.severity, a.ticker, a.reason, a.created_at
            FROM alerts a JOIN events e ON a.event_id = e.id
            ORDER BY CASE a.severity
                WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
                WHEN 'MEDIUM' THEN 3 ELSE 4 END,
                e.published_at DESC LIMIT ?
        """, (limit,)).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["tickers"] = json.loads(d.get("tickers") or "[]")
            items.append(d)
        counts = {s: sum(1 for i in items if i["severity"] == s)
                  for s in ("CRITICAL","HIGH","MEDIUM","LOW")}
        conn.close()
        return jsonify({"items": items, "counts": counts})

    @app.route("/api/media")
    def api_media():
        return api_alerts()

    @app.route("/api/insider")
    def api_insider():
        conn = get_media_conn()
        limit = int(request.args.get("limit", 50))
        rows = conn.execute("""
            SELECT ia.severity, ia.ticker, ia.signal_type, ia.reason,
                   ia.created_at, ia.source_table
            FROM insider_alerts ia
            ORDER BY CASE ia.severity
                WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
                WHEN 'MEDIUM' THEN 3 ELSE 4 END,
                ia.created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        items = [dict(r) for r in rows]
        counts = {s: sum(1 for i in items if i["severity"] == s)
                  for s in ("CRITICAL","HIGH","MEDIUM","LOW")}
        conn.close()
        return jsonify({"items": items, "counts": counts})

    @app.route("/api/credit")
    def api_credit():
        conn = get_media_conn()
        limit = int(request.args.get("limit", 50))
        rows = conn.execute("""
            SELECT ca.severity, ca.ticker, ca.company_name, ca.signal_type,
                   ca.reason, ca.created_at
            FROM credit_alerts ca
            ORDER BY CASE ca.severity
                WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2
                WHEN 'MEDIUM' THEN 3 ELSE 4 END,
                ca.created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        items = [dict(r) for r in rows]
        counts = {s: sum(1 for i in items if i["severity"] == s)
                  for s in ("CRITICAL","HIGH","MEDIUM","LOW")}
        conn.close()
        return jsonify({"items": items, "counts": counts})

    @app.route("/api/history")
    def api_history():
        conn = get_media_conn()
        rows = conn.execute("""
            SELECT digest_date, item_count, sent_at FROM digest_history
            ORDER BY sent_at DESC LIMIT 30
        """).fetchall()
        conn.close()
        items = [dict(r) for r in rows]
        return jsonify({"items": items, "counts": {}})

    @app.route("/api/digest/latest")
    def api_digest_latest():
        conn = get_media_conn()
        row = conn.execute(
            "SELECT html_report, digest_date FROM digest_history ORDER BY sent_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row or not row["html_report"]:
            return "No digest found yet.", 404
        from flask import Response
        return Response(row["html_report"], content_type="text/html")

    @app.route("/api/watchlist")
    def api_watchlist():
        conn = get_media_conn()
        rows = conn.execute(
            "SELECT ticker FROM watchlist_config WHERE active=1 AND ticker IS NOT NULL"
        ).fetchall()
        conn.close()
        return jsonify([r["ticker"] for r in rows])


def run_dashboard():
    if not FLASK_OK:
        print("[Dashboard] Flask not installed. Run: pip install flask")
        return
    print(f"[Dashboard] Starting at http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=DASHBOARD_DEBUG, use_reloader=False)


if __name__ == "__main__":
    run_dashboard()
