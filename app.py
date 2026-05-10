"""
Metadata Intelligence Platform — Web UI
========================================
Flask-based web interface for the metadata enrichment pipeline.
Version: v0.0.1

Run (PowerShell):
    pip install -r requirements.txt
    # Anahtar: proje kökünde .env (OPENAI_API_KEY=...) veya ortam değişkeni
    python app.py

Tarayıcı: http://127.0.0.1:5000 — "Run Pipeline" tam orchestrator akışını çalıştırır.
"""

import json
import os
import threading
from pathlib import Path
from flask import Flask, jsonify, render_template_string, request, send_from_directory

ROOT = Path(__file__).parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

app = Flask(__name__)

# ─── Pipeline state (in-memory for v0.0.1) ───────────────────────────────────
pipeline_state = {
    "status": "idle",          # idle | running | done | error
    "step": "",
    "progress": 0,
    "log": [],
    "results": None,
    "error": None,
}

def log(msg):
    print(msg)
    pipeline_state["log"].append(msg)

# ─── Pipeline runner (background thread) ─────────────────────────────────────
def run_pipeline_bg():
    """CLI ile aynı akış: orchestrator.run_pipeline() → final_output.json."""
    try:
        pipeline_state["status"] = "running"
        pipeline_state["log"] = []
        pipeline_state["results"] = None
        pipeline_state["error"] = None

        pipeline_state["step"] = "Orchestrator (Generator → Critic → Re-gen → Lineage → Risk → Clarity)"
        pipeline_state["progress"] = 15
        log("🚀 orchestrator.run_pipeline() başlıyor…")

        import orchestrator

        orchestrator.run_pipeline()

        out_path = ROOT / "final_output.json"
        if not out_path.exists():
            raise FileNotFoundError(f"Beklenen çıktı bulunamadı: {out_path}")

        pipeline_state["progress"] = 95
        pipeline_state["step"] = "Sonuçlar yükleniyor"
        with open(out_path, "r", encoding="utf-8") as f:
            pipeline_state["results"] = json.load(f)

        pipeline_state["status"] = "done"
        pipeline_state["progress"] = 100
        pipeline_state["step"] = "Tamamlandı"
        log("🎉 Pipeline tamamlandı — final_output.json okundu.")

    except Exception as e:
        pipeline_state["status"] = "error"
        pipeline_state["error"] = str(e)
        pipeline_state["step"] = "Error"
        log(f"❌ Error: {e}")


# ─── Load existing results if available ──────────────────────────────────────
def load_existing_results():
    out_path = ROOT / "final_output.json"
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                pipeline_state["results"] = json.load(f)
                pipeline_state["status"] = "done"
                pipeline_state["step"] = "Loaded from cache"
        except Exception:
            pass


# ─── API Routes ───────────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    return jsonify({
        "status": pipeline_state["status"],
        "step": pipeline_state["step"],
        "progress": pipeline_state["progress"],
        "log": pipeline_state["log"][-20:],  # last 20 lines
        "error": pipeline_state["error"],
    })

@app.route("/api/run", methods=["POST"])
def api_run():
    if pipeline_state["status"] == "running":
        return jsonify({"error": "Pipeline already running"}), 400
    t = threading.Thread(target=run_pipeline_bg, daemon=True)
    t.start()
    return jsonify({"ok": True})

@app.route("/api/results")
def api_results():
    if not pipeline_state["results"]:
        tables_path = ROOT / "synthetic_tables.json"
        if not tables_path.exists():
            tables_path = ROOT / "data" / "tables" / "synthetic_tables.json"
        if tables_path.exists():
            with open(tables_path, "r", encoding="utf-8") as f:
                tables = json.load(f)
            return jsonify({"tables": tables, "preview": True})
        return jsonify({"error": "No results yet"}), 404
    return jsonify(pipeline_state["results"])

@app.route("/api/lineage")
def api_lineage():
    lineage_path = ROOT / "lineage.json"
    if not lineage_path.exists():
        lineage_path = ROOT / "data" / "etl" / "lineage.json"
    if lineage_path.exists():
        with open(lineage_path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "No lineage data"}), 404


# ─── Main UI ─────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Metadata Intelligence Platform v0.0.1</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet"/>
<style>
/* ── Reset & Variables ─────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:       #08090C;
  --surface:  #0F1117;
  --surface2: #161820;
  --border:   #1E2130;
  --accent:   #00E5FF;
  --accent2:  #7B61FF;
  --high:     #FF3B5C;
  --low:      #00D68F;
  --warn:     #FFB547;
  --text:     #E4E6F0;
  --muted:    #5A607A;
  --mono:     'Space Mono', monospace;
  --sans:     'DM Sans', sans-serif;
  --r:        4px;
}

html { scroll-behavior: smooth; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  min-height: 100vh;
  overflow-x: hidden;
}

/* ── Scanline overlay ──────────────────────────────────────────────── */
body::before {
  content: '';
  position: fixed; inset: 0;
  background: repeating-linear-gradient(
    0deg, transparent, transparent 2px,
    rgba(0,229,255,0.012) 2px, rgba(0,229,255,0.012) 4px
  );
  pointer-events: none; z-index: 9999;
}

/* ── Topbar ────────────────────────────────────────────────────────── */
header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(8,9,12,0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: 0 28px;
  height: 56px;
  display: flex; align-items: center; justify-content: space-between;
}

.logo {
  display: flex; align-items: center; gap: 10px;
}

.logo-mark {
  width: 28px; height: 28px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  clip-path: polygon(50% 0%, 100% 38%, 82% 100%, 18% 100%, 0% 38%);
}

.logo-text {
  font-family: var(--mono);
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--accent);
}

.logo-version {
  font-family: var(--mono);
  font-size: 0.6rem;
  color: var(--muted);
  padding: 2px 6px;
  border: 1px solid var(--border);
  border-radius: 2px;
  margin-left: 4px;
}

.header-right { display: flex; align-items: center; gap: 12px; }

.status-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--muted);
  transition: background 0.3s;
}
.status-dot.running { background: var(--warn); animation: pulse 1s infinite; }
.status-dot.done    { background: var(--low); }
.status-dot.error   { background: var(--high); }

@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }

.status-label {
  font-family: var(--mono);
  font-size: 0.62rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

/* ── Run Button ────────────────────────────────────────────────────── */
.run-btn {
  font-family: var(--mono);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 8px 18px;
  background: var(--accent);
  color: var(--bg);
  border: none;
  border-radius: var(--r);
  cursor: pointer;
  transition: all 0.15s;
  position: relative;
  overflow: hidden;
}
.run-btn::after {
  content: '';
  position: absolute; inset: 0;
  background: rgba(255,255,255,0);
  transition: background 0.15s;
}
.run-btn:hover::after { background: rgba(255,255,255,0.15); }
.run-btn:active { transform: scale(0.97); }
.run-btn:disabled {
  background: var(--border);
  color: var(--muted);
  cursor: not-allowed;
}

/* ── Layout ────────────────────────────────────────────────────────── */
.wrap { max-width: 1440px; margin: 0 auto; padding: 24px 28px; }

/* ── Progress Bar ──────────────────────────────────────────────────── */
#progress-section {
  display: none;
  margin-bottom: 24px;
}
#progress-section.visible { display: block; }

.progress-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 18px 22px;
}

.progress-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 12px;
}

.progress-step {
  font-family: var(--mono);
  font-size: 0.7rem;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.progress-pct {
  font-family: var(--mono);
  font-size: 0.7rem;
  color: var(--muted);
}

.progress-track {
  height: 3px;
  background: var(--border);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 14px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  border-radius: 2px;
  transition: width 0.5s ease;
  width: 0%;
}

.log-output {
  font-family: var(--mono);
  font-size: 0.65rem;
  color: var(--muted);
  max-height: 120px;
  overflow-y: auto;
  line-height: 1.8;
}

.log-output .log-ok   { color: var(--low); }
.log-output .log-err  { color: var(--high); }
.log-output .log-info { color: var(--accent); }

/* ── Stats row ─────────────────────────────────────────────────────── */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 14px;
  margin-bottom: 24px;
}

.stat {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 16px 18px;
  position: relative;
  overflow: hidden;
}

.stat::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
}
.stat.c-accent::before  { background: var(--accent); }
.stat.c-high::before    { background: var(--high); }
.stat.c-low::before     { background: var(--low); }
.stat.c-warn::before    { background: var(--warn); }
.stat.c-accent2::before { background: var(--accent2); }

.stat-val {
  font-family: var(--mono);
  font-size: 1.8rem;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 4px;
}
.c-accent  .stat-val { color: var(--accent); }
.c-high    .stat-val { color: var(--high); }
.c-low     .stat-val { color: var(--low); }
.c-warn    .stat-val { color: var(--warn); }
.c-accent2 .stat-val { color: var(--accent2); }

.stat-lbl {
  font-size: 0.65rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 600;
}

/* ── Main grid ─────────────────────────────────────────────────────── */
.main-grid {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 18px;
}
@media (max-width: 900px) { .main-grid { grid-template-columns: 1fr; } }

/* ── Panel ─────────────────────────────────────────────────────────── */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r);
  overflow: hidden;
  margin-bottom: 18px;
}

.panel-head {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface2);
  display: flex; align-items: center; justify-content: space-between;
}

.panel-title {
  font-family: var(--mono);
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--accent);
  font-weight: 700;
}

.badge {
  font-family: var(--mono);
  font-size: 0.58rem;
  padding: 2px 8px;
  border-radius: 2px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.badge-accent  { background: rgba(0,229,255,0.12); color: var(--accent); border: 1px solid rgba(0,229,255,0.25); }
.badge-high    { background: rgba(255,59,92,0.12); color: var(--high);   border: 1px solid rgba(255,59,92,0.3); }
.badge-low     { background: rgba(0,214,143,0.1);  color: var(--low);    border: 1px solid rgba(0,214,143,0.25); }
.badge-warn    { background: rgba(255,181,71,0.1);  color: var(--warn);   border: 1px solid rgba(255,181,71,0.25); }

/* ── Filter bar ────────────────────────────────────────────────────── */
.filter-bar {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  display: flex; gap: 6px; flex-wrap: wrap;
}

.filter-btn {
  font-family: var(--mono);
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  padding: 4px 12px;
  border-radius: 2px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: all 0.12s;
}
.filter-btn:hover, .filter-btn.active {
  background: rgba(0,229,255,0.08);
  color: var(--accent);
  border-color: rgba(0,229,255,0.3);
}
.filter-btn.active-red {
  background: rgba(255,59,92,0.1);
  color: var(--high);
  border-color: rgba(255,59,92,0.3);
}
.filter-btn.active-green {
  background: rgba(0,214,143,0.08);
  color: var(--low);
  border-color: rgba(0,214,143,0.25);
}

/* ── Table ─────────────────────────────────────────────────────────── */
.tbl-wrap { overflow-x: auto; }

table { width: 100%; border-collapse: collapse; font-size: 0.72rem; }

th {
  font-family: var(--mono);
  font-size: 0.58rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  font-weight: 700;
  padding: 8px 14px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  background: var(--surface2);
  white-space: nowrap;
}

td {
  padding: 9px 14px;
  border-bottom: 1px solid rgba(30,33,48,0.7);
  vertical-align: middle;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(0,229,255,0.025); }

.col-name { font-family: var(--mono); font-size: 0.68rem; color: var(--accent); font-weight: 700; }
.tbl-name { font-family: var(--mono); font-size: 0.6rem; color: var(--muted); }
.desc-text { color: var(--text); max-width: 340px; line-height: 1.5; }
.desc-missing { color: var(--muted); font-style: italic; }

/* ── Risk pill ─────────────────────────────────────────────────────── */
.risk-pill {
  display: inline-flex; align-items: center; gap: 4px;
  font-family: var(--mono); font-size: 0.58rem; font-weight: 700;
  letter-spacing: 0.06em; padding: 3px 8px; border-radius: 2px;
  white-space: nowrap; cursor: pointer; transition: opacity 0.12s;
}
.risk-pill:hover { opacity: 0.75; }
.risk-high { background: rgba(255,59,92,0.15); color: var(--high); border: 1px solid rgba(255,59,92,0.35); }
.risk-low  { background: rgba(0,214,143,0.1);  color: var(--low);  border: 1px solid rgba(0,214,143,0.3); }

/* ── Clarity bar ───────────────────────────────────────────────────── */
.clarity-wrap { display: flex; align-items: center; gap: 7px; }
.clarity-track { width: 54px; height: 3px; background: var(--border); border-radius: 2px; overflow: hidden; }
.clarity-fill { height: 100%; border-radius: 2px; }
.clarity-val { font-family: var(--mono); font-size: 0.62rem; color: var(--muted); }

/* ── Issue count ───────────────────────────────────────────────────── */
.issue-count {
  background: rgba(255,181,71,0.12);
  color: var(--warn);
  border: 1px solid rgba(255,181,71,0.25);
  font-family: var(--mono); font-size: 0.58rem;
  padding: 2px 7px; border-radius: 2px; cursor: pointer;
  transition: opacity 0.12s;
}
.issue-count:hover { opacity: 0.75; }

/* ── Lineage ───────────────────────────────────────────────────────── */
.lineage-item {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 16px;
  border-bottom: 1px solid rgba(30,33,48,0.5);
  font-family: var(--mono); font-size: 0.68rem;
}
.lineage-item:last-child { border-bottom: none; }
.l-src { color: var(--accent); }
.l-arr { color: var(--muted); }
.l-tgt { color: var(--accent2); }
.l-loop { margin-left: auto; color: var(--high); font-size: 0.58rem; }

/* ── Popup ─────────────────────────────────────────────────────────── */
.overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.75);
  z-index: 200;
  display: flex; align-items: center; justify-content: center;
  opacity: 0; pointer-events: none;
  transition: opacity 0.18s;
  backdrop-filter: blur(4px);
}
.overlay.open { opacity: 1; pointer-events: all; }

.popup {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 24px 28px;
  max-width: 500px; width: 90%;
  position: relative;
  transform: translateY(8px);
  transition: transform 0.18s;
}
.overlay.open .popup { transform: translateY(0); }

.popup-close {
  position: absolute; top: 12px; right: 16px;
  background: none; border: none;
  color: var(--muted); cursor: pointer; font-size: 1.1rem;
}

.popup-risk-head { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.popup-col { font-family: var(--mono); font-size: 0.82rem; color: var(--accent); }
.popup-table { font-size: 0.68rem; color: var(--muted); margin-top: 2px; }

.popup-section {
  font-family: var(--mono); font-size: 0.6rem; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--muted);
  margin-bottom: 6px; margin-top: 14px;
}
.popup-desc {
  font-size: 0.78rem; color: var(--text); line-height: 1.65;
  background: var(--surface2); padding: 10px 12px; border-radius: 3px;
  border-left: 2px solid var(--accent);
}
.popup-issues { display: flex; flex-direction: column; gap: 5px; }
.popup-issue {
  font-size: 0.7rem; color: var(--warn);
  background: rgba(255,181,71,0.06);
  padding: 6px 10px; border-radius: 2px;
  border-left: 2px solid var(--warn);
}

/* ── Empty state ───────────────────────────────────────────────────── */
.empty-state {
  padding: 48px 24px; text-align: center;
}
.empty-title { font-family: var(--mono); font-size: 0.8rem; color: var(--muted); margin-bottom: 8px; }
.empty-sub { font-size: 0.76rem; color: var(--muted); opacity: 0.6; }

/* ── Schema pill ───────────────────────────────────────────────────── */
.schema-pill {
  font-family: var(--mono); font-size: 0.55rem; font-weight: 700;
  padding: 1px 5px; border-radius: 2px;
  display: inline-block; margin-right: 4px;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.schema-CORE_BANKING { background: rgba(0,229,255,0.12); color: var(--accent); }
.schema-CREDIT       { background: rgba(255,59,92,0.12); color: var(--high); }
.schema-CRM          { background: rgba(123,97,255,0.12); color: var(--accent2); }
.schema-RISK         { background: rgba(255,181,71,0.12); color: var(--warn); }
.schema-OTHER        { background: rgba(90,96,122,0.2); color: var(--muted); }

/* ── Scrollbar ─────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--muted); }
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-mark"></div>
    <span class="logo-text">MIP</span>
    <span class="logo-version">v0.0.1</span>
  </div>
  <div class="header-right">
    <div class="status-dot" id="statusDot"></div>
    <span class="status-label" id="statusLabel">Idle</span>
    <button class="run-btn" id="runBtn" onclick="runPipeline()">▶ Run Pipeline</button>
  </div>
</header>

<div class="wrap">

  <!-- Progress -->
  <div id="progress-section">
    <div class="progress-card">
      <div class="progress-header">
        <span class="progress-step" id="progressStep">Initializing...</span>
        <span class="progress-pct" id="progressPct">0%</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill" id="progressFill"></div>
      </div>
      <div class="log-output" id="logOutput"></div>
    </div>
  </div>

  <!-- Stats -->
  <div class="stats" id="statsRow">
    <div class="stat c-high">  <div class="stat-val" id="statHigh">—</div>  <div class="stat-lbl">High Risk Cols</div></div>
    <div class="stat c-low">   <div class="stat-val" id="statLow">—</div>   <div class="stat-lbl">Low Risk Cols</div></div>
    <div class="stat c-accent"><div class="stat-val" id="statTables">—</div><div class="stat-lbl">Tables</div></div>
    <div class="stat c-warn">  <div class="stat-val" id="statLoops">—</div> <div class="stat-lbl">Lineage Loops</div></div>
    <div class="stat c-accent2"><div class="stat-val" id="statClarity">—</div><div class="stat-lbl">Avg Clarity</div></div>
  </div>

  <!-- Main -->
  <div class="main-grid">
    <div>
      <!-- Column Risk Matrix -->
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">// Column Risk Matrix</span>
          <span class="badge badge-accent" id="colCount">Loading...</span>
        </div>
        <div class="filter-bar">
          <button class="filter-btn active" onclick="filterCols('all',this)">All</button>
          <button class="filter-btn" onclick="filterCols('HIGH_RISK',this)">🔴 High Risk</button>
          <button class="filter-btn" onclick="filterCols('LOW_RISK',this)">🟢 Low Risk</button>
        </div>
        <div class="tbl-wrap">
          <table>
            <thead><tr>
              <th>Table</th><th>Column</th><th>Description</th>
              <th>Risk</th><th>Clarity</th><th>Issues</th>
            </tr></thead>
            <tbody id="colTbody"></tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Sidebar -->
    <div>
      <!-- Lineage -->
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">// ETL Lineage</span>
          <span class="badge badge-warn" id="loopBadge">Loading</span>
        </div>
        <div id="lineageList"></div>
      </div>

      <!-- Column Quality Summary -->
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">// Quality Breakdown</span>
        </div>
        <div id="qualityBreakdown" style="padding:16px;"></div>
      </div>
    </div>
  </div>

</div><!-- /wrap -->

<!-- Popup -->
<div class="overlay" id="overlay" onclick="closePopup(event)">
  <div class="popup">
    <button class="popup-close" onclick="closePopup()">✕</button>
    <div class="popup-risk-head">
      <div id="popupPill"></div>
      <div>
        <div class="popup-col" id="popupCol"></div>
        <div class="popup-table" id="popupTable"></div>
      </div>
    </div>
    <div class="popup-section">Description</div>
    <div class="popup-desc" id="popupDesc"></div>
    <div class="popup-section" id="issueTitle" style="display:none">Issues Detected</div>
    <div class="popup-issues" id="popupIssues"></div>
  </div>
</div>

<script>
// ─── State ────────────────────────────────────────────────────────────────────
let allColumns = [];
let currentFilter = 'all';

// ─── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  await loadResults();
  await loadLineage();
  pollStatus();
}

// ─── Pipeline ─────────────────────────────────────────────────────────────────
async function runPipeline() {
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  document.getElementById('progress-section').classList.add('visible');

  try {
    await fetch('/api/run', { method: 'POST' });
  } catch(e) {
    console.error(e);
  }
}

function pollStatus() {
  setInterval(async () => {
    try {
      const r = await fetch('/api/status');
      const d = await r.json();
      updateStatus(d);

      if (d.status === 'done') {
        await loadResults();
        await loadLineage();
      }
    } catch(e) {}
  }, 1500);
}

function updateStatus(d) {
  const dot = document.getElementById('statusDot');
  const lbl = document.getElementById('statusLabel');
  const btn = document.getElementById('runBtn');

  dot.className = 'status-dot ' + d.status;
  lbl.textContent = d.status.toUpperCase();

  if (d.status === 'running') {
    btn.disabled = true;
    document.getElementById('progressStep').textContent = d.step;
    document.getElementById('progressPct').textContent = d.progress + '%';
    document.getElementById('progressFill').style.width = d.progress + '%';

    const log = document.getElementById('logOutput');
    log.innerHTML = (d.log || []).map(l => {
      const cls = l.startsWith('✅') || l.startsWith('🎉') ? 'log-ok'
                : l.startsWith('❌') ? 'log-err' : 'log-info';
      return `<div class="${cls}">${l}</div>`;
    }).join('');
    log.scrollTop = log.scrollHeight;
  }

  if (d.status === 'done' || d.status === 'idle') {
    btn.disabled = false;
  }

  if (d.status === 'error') {
    btn.disabled = false;
    document.getElementById('progressStep').textContent = '❌ ' + (d.error || 'Error');
  }
}

// ─── Load Results ─────────────────────────────────────────────────────────────
async function loadResults() {
  try {
    const r = await fetch('/api/results');
    if (!r.ok) return;
    const data = await r.json();
    renderResults(data);
  } catch(e) {}
}

function renderResults(data) {
  const tables = data.tables || [];
  const riskReport = data.risk_report;

  // Build column list
  allColumns = [];
  tables.forEach(t => {
    (t.columns || []).forEach(col => {
      const issues = [];
      if (col.validation_issue) issues.push('VALUE MISMATCH: ' + col.validation_issue);
      if (col.distinct_count && col.distinct_count < 100 && !col.has_lookup)
        issues.push('LOOKUP GAP: ' + col.distinct_count + ' distinct values, no LKP table');
      if (col.issues) issues.push(...col.issues);

      const risk = col.risk_level || (col.description_quality === 'missing' ? 'HIGH_RISK' : 'LOW_RISK');
      const clarity = col.clarity_score !== undefined ? col.clarity_score : clarityHeuristic(col);

      allColumns.push({
        table: t.table_name,
        schema: t.schema || '',
        col: col.column_name,
        desc: col.description || '',
        quality: col.description_quality || '',
        risk,
        clarity,
        issues,
      });
    });
  });

  // Stats
  const high = allColumns.filter(c => c.risk === 'HIGH_RISK').length;
  const low  = allColumns.filter(c => c.risk === 'LOW_RISK').length;
  const avgClarity = allColumns.length
    ? Math.round(allColumns.reduce((s,c) => s + c.clarity, 0) / allColumns.length)
    : 0;
  const loops = data.lineage_loops ? data.lineage_loops.length : 0;

  document.getElementById('statHigh').textContent = high;
  document.getElementById('statLow').textContent = low;
  document.getElementById('statTables').textContent = tables.length;
  document.getElementById('statLoops').textContent = loops;
  document.getElementById('statClarity').textContent = avgClarity;
  document.getElementById('colCount').textContent = allColumns.length + ' columns';

  renderColTable(currentFilter);
  renderQuality();
}

function clarityHeuristic(col) {
  const d = col.description || '';
  if (!d) return 0;
  if (d.length < 10) return 15;
  if (d.length < 30) return 35;
  if (d.split(' ').length <= 3) return 30;
  return 65;
}

// ─── Column Table ─────────────────────────────────────────────────────────────
function renderColTable(filter) {
  currentFilter = filter;
  const rows = filter === 'all' ? allColumns
    : allColumns.filter(c => c.risk === filter);

  if (!rows.length) {
    document.getElementById('colTbody').innerHTML =
      `<tr><td colspan="6"><div class="empty-state">
        <div class="empty-title">// No data yet</div>
        <div class="empty-sub">Run the pipeline to generate results</div>
      </div></td></tr>`;
    return;
  }

  document.getElementById('colTbody').innerHTML = rows.map(col => {
    const riskCls = col.risk === 'HIGH_RISK' ? 'risk-high' : 'risk-low';
    const riskLbl = col.risk === 'HIGH_RISK' ? '🔴 HIGH' : '🟢 LOW';
    const cc = col.clarity >= 70 ? '#00D68F' : col.clarity >= 40 ? '#FFB547' : '#FF3B5C';
    const descHtml = col.desc
      ? `<span class="desc-text">${col.desc.length > 75 ? col.desc.slice(0,75)+'…' : col.desc}</span>`
      : `<span class="desc-missing">— missing —</span>`;
    const issueHtml = col.issues.length
      ? `<span class="issue-count" onclick="showPopup('${col.table}','${col.col}')">⚠ ${col.issues.length}</span>`
      : `<span style="color:var(--muted);font-size:.65rem">—</span>`;
    const schemaCls = 'schema-' + (col.schema || 'OTHER');

    return `<tr>
      <td>
        <span class="schema-pill ${schemaCls}">${col.schema || '—'}</span><br>
        <span class="tbl-name">${col.table}</span>
      </td>
      <td><span class="col-name">${col.col}</span></td>
      <td>${descHtml}</td>
      <td><span class="risk-pill ${riskCls}" onclick="showPopup('${col.table}','${col.col}')">${riskLbl}</span></td>
      <td>
        <div class="clarity-wrap">
          <div class="clarity-track"><div class="clarity-fill" style="width:${col.clarity}%;background:${cc}"></div></div>
          <span class="clarity-val">${col.clarity}</span>
        </div>
      </td>
      <td>${issueHtml}</td>
    </tr>`;
  }).join('');
}

function filterCols(f, btn) {
  document.querySelectorAll('.filter-btn').forEach(b => b.className = 'filter-btn');
  if (f === 'all')       btn.className = 'filter-btn active';
  else if (f === 'HIGH_RISK') btn.className = 'filter-btn active-red';
  else                   btn.className = 'filter-btn active-green';
  renderColTable(f);
}

// ─── Quality Breakdown ────────────────────────────────────────────────────────
function renderQuality() {
  const types = { complete:0, incomplete:0, missing:0, wrong:0, english:0, vague:0, generated:0 };
  allColumns.forEach(c => { if (types[c.quality] !== undefined) types[c.quality]++; });

  const colors = {
    complete: '#00D68F', generated: '#00E5FF',
    incomplete: '#FFB547', english: '#7B61FF',
    missing: '#FF3B5C', wrong: '#FF3B5C', vague: '#FF7D54'
  };

  const el = document.getElementById('qualityBreakdown');
  el.innerHTML = Object.entries(types).filter(([,v]) => v > 0).map(([k,v]) => {
    const c = colors[k] || '#5A607A';
    const pct = allColumns.length ? Math.round(v / allColumns.length * 100) : 0;
    return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:9px">
      <div style="width:8px;height:8px;border-radius:50%;background:${c};flex-shrink:0"></div>
      <span style="font-family:var(--mono);font-size:.65rem;color:var(--muted);text-transform:uppercase;flex:1">${k}</span>
      <div style="width:80px;height:3px;background:var(--border);border-radius:2px;overflow:hidden">
        <div style="width:${pct}%;height:100%;background:${c};border-radius:2px"></div>
      </div>
      <span style="font-family:var(--mono);font-size:.65rem;color:${c};min-width:20px;text-align:right">${v}</span>
    </div>`;
  }).join('') || '<div style="color:var(--muted);font-size:.7rem;font-family:var(--mono)">No data yet</div>';
}

// ─── Lineage ──────────────────────────────────────────────────────────────────
async function loadLineage() {
  try {
    const r = await fetch('/api/lineage');
    if (!r.ok) return;
    const data = await r.json();
    const jobs = data.etl_lineage || [];

    const loops = jobs.filter(j => j.loop_risk).length;
    document.getElementById('loopBadge').textContent =
      loops > 0 ? `⚠ ${loops} Loop` : '✓ No Loops';
    document.getElementById('loopBadge').className =
      loops > 0 ? 'badge badge-high' : 'badge badge-low';
    document.getElementById('statLoops').textContent = loops;

    document.getElementById('lineageList').innerHTML = jobs.map(j => {
      const src = j.source.schema + '.' + j.source.table;
      const tgt = j.target.schema + '.' + j.target.table;
      return `<div class="lineage-item">
        <span class="l-src">${j.source.table}</span>
        <span class="l-arr">→</span>
        <span class="l-tgt">${j.target.table}</span>
        ${j.loop_risk ? '<span class="l-loop">⚠ LOOP</span>' : ''}
      </div>`;
    }).join('');
  } catch(e) {}
}

// ─── Popup ────────────────────────────────────────────────────────────────────
function showPopup(table, colName) {
  const col = allColumns.find(c => c.table === table && c.col === colName);
  if (!col) return;

  const riskCls = col.risk === 'HIGH_RISK' ? 'risk-high' : 'risk-low';
  const riskLbl = col.risk === 'HIGH_RISK' ? '🔴 HIGH RISK' : '🟢 LOW RISK';

  document.getElementById('popupPill').innerHTML =
    `<span class="risk-pill ${riskCls}">${riskLbl}</span>`;
  document.getElementById('popupCol').textContent = col.col;
  document.getElementById('popupTable').textContent = col.schema + '.' + col.table;
  document.getElementById('popupDesc').textContent = col.desc || '(No description)';

  const issueEl = document.getElementById('popupIssues');
  const issueTitle = document.getElementById('issueTitle');
  if (col.issues.length) {
    issueTitle.style.display = 'block';
    issueEl.innerHTML = col.issues.map(i =>
      `<div class="popup-issue">⚠ ${i}</div>`).join('');
  } else {
    issueTitle.style.display = 'none';
    issueEl.innerHTML = '';
  }
  document.getElementById('overlay').classList.add('open');
}

function closePopup(e) {
  if (!e || e.target === document.getElementById('overlay') || e.target.classList.contains('popup-close'))
    document.getElementById('overlay').classList.remove('open');
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closePopup({ target: document.getElementById('overlay') }); });

// ─── Boot ─────────────────────────────────────────────────────────────────────
init();
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)


if __name__ == "__main__":
    load_existing_results()
    print("\n🚀 Metadata Intelligence Platform v0.0.1")
    print("   Open: http://localhost:5000\n")
    app.run(debug=True, port=5000)
