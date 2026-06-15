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

from flask import Flask, jsonify, render_template_string, request

from pipeline_metrics import compute_metrics

ROOT = Path(__file__).parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass

app = Flask(__name__)

# ─── Pipeline state (in-memory for v0.0.1) ───────────────────────────────────
_state_lock = threading.Lock()
pipeline_state = {
    "status": "idle",          # idle | running | done | error
    "phase": "",
    "step": "",
    "progress": 0,
    "log": [],
    "metrics": {},
    "results": None,
    "error": None,
}


def _load_synthetic_tables() -> list:
    path = ROOT / "synthetic_tables.json"
    if not path.exists():
        path = ROOT / "data" / "tables" / "synthetic_tables.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def log(msg: str) -> None:
    print(msg)
    with _state_lock:
        pipeline_state["log"].append(msg)


def _on_pipeline_progress(event: dict) -> None:
    """Orchestrator'dan gelen canlı ilerleme olayları."""
    with _state_lock:
        pipeline_state["progress"] = int(event.get("progress", 0))
        pipeline_state["step"] = event.get("step", "")
        pipeline_state["phase"] = event.get("phase", "")
        if event.get("metrics"):
            pipeline_state["metrics"] = event["metrics"]
        if event.get("log"):
            pipeline_state["log"].append(event["log"])


# ─── Pipeline runner (background thread) ─────────────────────────────────────
def run_pipeline_bg():
    """CLI ile aynı akış: orchestrator.run_pipeline() → final_output.json."""
    try:
        baseline_tables = _load_synthetic_tables()
        baseline_metrics = compute_metrics(baseline_tables)

        with _state_lock:
            pipeline_state["status"] = "running"
            pipeline_state["phase"] = "init"
            pipeline_state["log"] = []
            pipeline_state["results"] = None
            pipeline_state["error"] = None
            pipeline_state["metrics"] = baseline_metrics
            pipeline_state["progress"] = 0
            pipeline_state["step"] = "Pipeline başlatılıyor…"

        log(
            f"🚀 Pipeline başladı — {baseline_metrics['tables_total']} tablo, "
            f"{baseline_metrics['columns_total']} kolon (başlangıç clarity: {baseline_metrics['stat_clarity']})"
        )

        import orchestrator

        orchestrator.run_pipeline(on_progress=_on_pipeline_progress)

        out_path = ROOT / "final_output.json"
        if not out_path.exists():
            raise FileNotFoundError(f"Beklenen çıktı bulunamadı: {out_path}")

        with _state_lock:
            pipeline_state["step"] = "Sonuçlar yükleniyor…"
            pipeline_state["progress"] = 98

        with open(out_path, "r", encoding="utf-8") as f:
            final_data = json.load(f)

        loops = final_data.get("lineage_loops") or []
        final_metrics = compute_metrics(final_data.get("tables", []), loops)

        with _state_lock:
            pipeline_state["results"] = final_data
            pipeline_state["metrics"] = final_metrics
            pipeline_state["status"] = "done"
            pipeline_state["progress"] = 100
            pipeline_state["phase"] = "done"
            pipeline_state["step"] = "✅ Pipeline tamamlandı"
            pipeline_state["log"].append(
                f"🎉 Tamamlandı — Ort. clarity: {final_metrics['stat_clarity']} | "
                f"🟢 {final_metrics['stat_low']} düşük risk | "
                f"🔴 {final_metrics['stat_high']} yüksek risk"
            )

    except Exception as e:
        with _state_lock:
            pipeline_state["status"] = "error"
            pipeline_state["error"] = str(e)
            pipeline_state["phase"] = "error"
            pipeline_state["step"] = "Hata oluştu"
            pipeline_state["log"].append(f"❌ Error: {e}")


# ─── Load existing results if available ──────────────────────────────────────
def load_existing_results():
    out_path = ROOT / "final_output.json"
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                pipeline_state["results"] = data
                pipeline_state["status"] = "done"
                pipeline_state["phase"] = "done"
                pipeline_state["progress"] = 100
                pipeline_state["step"] = "Önbellekten yüklendi"
                pipeline_state["metrics"] = compute_metrics(
                    data.get("tables", []),
                    data.get("lineage_loops"),
                )
        except Exception:
            pass
    elif _load_synthetic_tables():
        pipeline_state["metrics"] = compute_metrics(_load_synthetic_tables())


# ─── API Routes ───────────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    with _state_lock:
        return jsonify(
            {
                "status": pipeline_state["status"],
                "phase": pipeline_state.get("phase", ""),
                "step": pipeline_state["step"],
                "progress": pipeline_state["progress"],
                "log": pipeline_state["log"][-30:],
                "metrics": pipeline_state.get("metrics") or {},
                "error": pipeline_state["error"],
            }
        )

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
  --bg:       #F4F6F9;
  --surface:  #FFFFFF;
  --surface2: #EEF2F7;
  --border:   #D8E0EA;
  --accent:   #0369A1;
  --accent2:  #6D28D9;
  --high:     #DC2626;
  --low:      #059669;
  --warn:     #B45309;
  --text:     #1E293B;
  --muted:    #64748B;
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

/* ── Topbar ────────────────────────────────────────────────────────── */
header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(255,255,255,0.92);
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
  color: #FFFFFF;
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
#progress-section.complete .progress-card {
  border-color: rgba(5,150,105,0.45);
  box-shadow: 0 0 0 1px rgba(5,150,105,0.12);
}
#progress-section.error-state .progress-card {
  border-color: rgba(220,38,38,0.45);
}

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
.badge-accent  { background: rgba(3,105,161,0.1); color: var(--accent); border: 1px solid rgba(3,105,161,0.25); }
.badge-high    { background: rgba(220,38,38,0.1); color: var(--high);   border: 1px solid rgba(220,38,38,0.28); }
.badge-low     { background: rgba(5,150,105,0.1);  color: var(--low);    border: 1px solid rgba(5,150,105,0.25); }
.badge-warn    { background: rgba(180,83,9,0.1);  color: var(--warn);   border: 1px solid rgba(180,83,9,0.25); }

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
  background: rgba(3,105,161,0.08);
  color: var(--accent);
  border-color: rgba(3,105,161,0.28);
}
.filter-btn.active-red {
  background: rgba(220,38,38,0.08);
  color: var(--high);
  border-color: rgba(220,38,38,0.28);
}
.filter-btn.active-green {
  background: rgba(5,150,105,0.08);
  color: var(--low);
  border-color: rgba(5,150,105,0.25);
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
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(3,105,161,0.05); }

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
.risk-high { background: rgba(220,38,38,0.1); color: var(--high); border: 1px solid rgba(220,38,38,0.35); }
.risk-low  { background: rgba(5,150,105,0.1);  color: var(--low);  border: 1px solid rgba(5,150,105,0.28); }

/* ── Clarity bar ───────────────────────────────────────────────────── */
.clarity-wrap { display: flex; align-items: center; gap: 7px; }
.clarity-track { width: 54px; height: 3px; background: var(--border); border-radius: 2px; overflow: hidden; }
.clarity-fill { height: 100%; border-radius: 2px; }
.clarity-val { font-family: var(--mono); font-size: 0.62rem; color: var(--muted); }

/* ── Issue count ───────────────────────────────────────────────────── */
.issue-count {
  background: rgba(180,83,9,0.1);
  color: var(--warn);
  border: 1px solid rgba(180,83,9,0.25);
  font-family: var(--mono); font-size: 0.58rem;
  padding: 2px 7px; border-radius: 2px; cursor: pointer;
  transition: opacity 0.12s;
}
.issue-count:hover { opacity: 0.75; }

/* ── Lineage ───────────────────────────────────────────────────────── */
.lineage-item {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 16px;
  border-bottom: 1px solid var(--border);
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
  background: rgba(15,23,42,0.35);
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
  max-width: 560px; width: 92%;
  max-height: 85vh; overflow-y: auto;
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
  background: rgba(180,83,9,0.08);
  padding: 6px 10px; border-radius: 2px;
  border-left: 2px solid var(--warn);
}

.doc-pills { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
.doc-pill {
  font-family: var(--mono); font-size: 0.58rem; font-weight: 600;
  padding: 2px 8px; border-radius: 2px;
}
.doc-pill.ok { background: rgba(5,150,105,0.12); color: #059669; }
.doc-pill.miss { background: rgba(100,116,139,0.1); color: var(--muted); }

.coverage-badge {
  display: inline-block; font-family: var(--mono); font-size: 0.58rem;
  padding: 2px 8px; border-radius: 2px; margin-top: 6px;
}
.coverage-with { background: rgba(3,105,161,0.1); color: var(--accent); }
.coverage-none { background: rgba(100,116,139,0.1); color: var(--muted); }

.compare-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.compare-box {
  background: var(--surface2); padding: 10px 12px; border-radius: 3px;
  font-size: 0.74rem; line-height: 1.6; min-height: 48px;
}
.compare-box.before { border-left: 2px solid var(--muted); }
.compare-box.after  { border-left: 2px solid var(--accent); }
.compare-label {
  font-family: var(--mono); font-size: 0.55rem; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted); margin-bottom: 4px;
}
.compare-missing { color: var(--muted); font-style: italic; font-size: 0.72rem; }

.risk-reason {
  font-size: 0.7rem; color: var(--text); line-height: 1.5;
  padding: 5px 10px; background: var(--surface2); border-radius: 2px;
  border-left: 2px solid var(--border);
}
.risk-reason.high { border-left-color: var(--high); }
.risk-reason.low  { border-left-color: #059669; }

.popup-feedback {
  font-size: 0.72rem; color: var(--muted); line-height: 1.55;
  background: var(--surface2); padding: 8px 10px; border-radius: 3px;
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
.schema-CORE_BANKING { background: rgba(3,105,161,0.1); color: var(--accent); }
.schema-CREDIT       { background: rgba(220,38,38,0.1); color: var(--high); }
.schema-CRM          { background: rgba(109,40,217,0.1); color: var(--accent2); }
.schema-RISK         { background: rgba(180,83,9,0.1); color: var(--warn); }
.schema-OTHER        { background: rgba(100,116,139,0.12); color: var(--muted); }

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
    <div class="popup-section">Bağlam Dokümanları (Pipeline Öncesi)</div>
    <div class="doc-pills" id="popupDocs"></div>
    <div id="popupCoverage"></div>
    <div class="popup-section">Risk Değerlendirmesi</div>
    <div id="popupRiskReasons"></div>
    <div class="popup-section">Açıklama Karşılaştırması</div>
    <div class="compare-grid">
      <div>
        <div class="compare-label">Önce (Ham)</div>
        <div class="compare-box before" id="popupBefore"></div>
      </div>
      <div>
        <div class="compare-label">Sonra (Pipeline)</div>
        <div class="compare-box after" id="popupAfter"></div>
      </div>
    </div>
    <div class="popup-section" id="feedbackTitle" style="display:none">Critic Geri Bildirimi</div>
    <div class="popup-feedback" id="popupFeedback" style="display:none"></div>
    <div class="popup-section" id="issueTitle" style="display:none">Issues Detected</div>
    <div class="popup-issues" id="popupIssues"></div>
  </div>
</div>

<script>
// ─── State ────────────────────────────────────────────────────────────────────
let allColumns = [];
let currentFilter = 'all';
let pollTimer = null;
let lastPipelineStatus = 'idle';
let lineageJobs = [];

function applyMetrics(m) {
  if (!m || !Object.keys(m).length) return;
  if (m.stat_high !== undefined) document.getElementById('statHigh').textContent = m.stat_high;
  if (m.stat_low !== undefined) document.getElementById('statLow').textContent = m.stat_low;
  if (m.stat_clarity !== undefined) document.getElementById('statClarity').textContent = m.stat_clarity;
  if (m.stat_tables !== undefined) document.getElementById('statTables').textContent = m.stat_tables;
  if (m.stat_loops !== undefined) document.getElementById('statLoops').textContent = m.stat_loops;
}

// ─── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  await loadResults();
  await loadLineage();
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    if (d.metrics) applyMetrics(d.metrics);
    updateStatus(d);
  } catch(e) {}
  startPolling();
}

// ─── Pipeline ─────────────────────────────────────────────────────────────────
async function runPipeline() {
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  const progSec = document.getElementById('progress-section');
  progSec.classList.add('visible');
  progSec.classList.remove('complete', 'error-state');

  try {
    const res = await fetch('/api/run', { method: 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.error || 'Pipeline zaten çalışıyor');
      btn.disabled = false;
      return;
    }
    schedulePoll(400);
  } catch(e) {
    console.error(e);
    btn.disabled = false;
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollOnce, 1200);
}

function schedulePoll(ms) {
  pollOnce();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollOnce, ms);
}

async function pollOnce() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    updateStatus(d);

    if (d.status === 'running' && lastPipelineStatus !== 'running') {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(pollOnce, 600);
    }

    if (d.status === 'done' && lastPipelineStatus === 'running') {
      await loadResults();
      await loadLineage();
    }
    lastPipelineStatus = d.status;
  } catch(e) {}
}

function updateStatus(d) {
  const dot = document.getElementById('statusDot');
  const lbl = document.getElementById('statusLabel');
  const btn = document.getElementById('runBtn');
  const progSec = document.getElementById('progress-section');

  dot.className = 'status-dot ' + d.status;
  lbl.textContent = d.status === 'done' ? 'TAMAMLANDI' : d.status.toUpperCase();

  const pct = Math.min(100, Math.max(0, d.progress || 0));
  document.getElementById('progressStep').textContent = d.step || '—';
  document.getElementById('progressPct').textContent = pct + '%';
  document.getElementById('progressFill').style.width = pct + '%';

  if (d.metrics) applyMetrics(d.metrics);

  const log = document.getElementById('logOutput');
  log.innerHTML = (d.log || []).map(l => {
    const cls = l.includes('✅') || l.includes('🎉') || l.includes('Tamamlandı') ? 'log-ok'
              : l.includes('❌') ? 'log-err' : 'log-info';
    return `<div class="${cls}">${l}</div>`;
  }).join('');
  log.scrollTop = log.scrollHeight;

  if (d.status === 'running') {
    btn.disabled = true;
    progSec.classList.add('visible');
    progSec.classList.remove('complete', 'error-state');
  }

  if (d.status === 'done') {
    btn.disabled = false;
    progSec.classList.add('visible', 'complete');
    progSec.classList.remove('error-state');
  }

  if (d.status === 'idle') {
    btn.disabled = false;
  }

  if (d.status === 'error') {
    btn.disabled = false;
    progSec.classList.add('visible', 'error-state');
    progSec.classList.remove('complete');
    document.getElementById('progressStep').textContent = '❌ ' + (d.error || 'Hata');
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

function consolidateIssues(col) {
  const raw = [];
  if (col.validation_issue) raw.push('VALUE MISMATCH: ' + col.validation_issue);
  if (col.distinct_count && col.distinct_count < 100 && !col.has_lookup)
    raw.push('LOOKUP GAP: ' + col.distinct_count + ' distinct values, no LKP table');
  if (col.issues) raw.push(...col.issues);

  let hasValueMismatch = false;
  let valueDetail = '';
  let hasLookupGap = false;
  const descriptionNotes = [];
  const other = [];

  const valueRe = /value mismatch|validation|documented values|db contains|uyumsuz|tutarsız|belirsiz değer|validation hatası|mismatch/i;
  const lookupRe = /lookup|lkp|low cardinality|kardinalite|distinct.*tablo/i;
  const descRe = /eksik açıklama|missing|vague|english|belirsiz açıklama|incomplete|wrong/i;

  for (const item of raw) {
    const s = String(item).trim();
    if (!s) continue;
    if (valueRe.test(s)) {
      hasValueMismatch = true;
      const detail = s.replace(/^VALUE MISMATCH:\s*/i, '').trim();
      if (detail.length > valueDetail.length) valueDetail = detail;
    } else if (lookupRe.test(s)) {
      hasLookupGap = true;
    } else if (descRe.test(s)) {
      if (!descriptionNotes.includes(s)) descriptionNotes.push(s);
    } else if (!other.includes(s)) {
      other.push(s);
    }
  }

  if (col.distinct_count && col.distinct_count < 100 && !col.has_lookup)
    hasLookupGap = true;
  if (col.validation_issue) {
    hasValueMismatch = true;
    if (col.validation_issue.length > valueDetail.length) valueDetail = col.validation_issue;
  }

  const out = [];
  if (hasValueMismatch) {
    out.push('VALUE MISMATCH: ' + (valueDetail || 'Dokümantasyon ile üretim verisi uyuşmuyor'));
  }
  if (hasLookupGap) {
    const d = col.distinct_count;
    const kv = col.known_values
      ? ' Bilinen değerler: ' + JSON.stringify(col.known_values) + '.'
      : '';
    out.push('LOOKUP GAP: ' + (d != null ? d + ' distinct değer' : 'Düşük kardinalite') +
      ', lookup tablosu tanımlı değil.' + kv);
  }
  if (descriptionNotes.length) {
    out.push('AÇIKLAMA: ' + descriptionNotes.join('; '));
  }
  other.forEach(o => out.push(o));
  return out;
}

function renderResults(data) {
  const tables = data.tables || [];
  const riskReport = data.risk_report;

  // Build column list
  allColumns = [];
  tables.forEach(t => {
    (t.columns || []).forEach(col => {
      const issues = consolidateIssues(col);

      const risk = col.risk_level || (col.description_quality === 'missing' ? 'HIGH_RISK' : 'LOW_RISK');
      const clarity = col.clarity_score !== undefined ? col.clarity_score : clarityHeuristic(col);

      allColumns.push({
        table: t.table_name,
        schema: t.schema || '',
        col: col.column_name,
        desc: col.description || '',
        origDesc: col.original_description !== undefined ? col.original_description : col.description,
        quality: col.description_quality || '',
        risk,
        clarity,
        issues,
        feedback: col.feedback || '',
        riskReasons: col.risk_reasons || [],
        hasFrd: t.has_functional_doc || false,
        hasToa: t.has_toa_doc || false,
        hasDdl: t.has_ddl || false,
        contextLabels: t.context_labels || null,
        coverage: (t.context_labels && t.context_labels.coverage)
          || ((t.has_functional_doc || t.has_toa_doc || t.has_ddl) ? 'with_docs' : 'no_docs'),
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
    const cc = col.clarity >= 70 ? '#059669' : col.clarity >= 40 ? '#B45309' : '#DC2626';
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
    complete: '#059669', generated: '#0369A1',
    incomplete: '#B45309', english: '#6D28D9',
    missing: '#DC2626', wrong: '#DC2626', vague: '#EA580C'
  };

  const el = document.getElementById('qualityBreakdown');
  el.innerHTML = Object.entries(types).filter(([,v]) => v > 0).map(([k,v]) => {
    const c = colors[k] || '#64748B';
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
    lineageJobs = data.etl_lineage || [];

    const loops = lineageJobs.filter(j => j.loop_risk).length;
    document.getElementById('loopBadge').textContent =
      loops > 0 ? `⚠ ${loops} Loop` : '✓ No Loops';
    document.getElementById('loopBadge').className =
      loops > 0 ? 'badge badge-high' : 'badge badge-low';
    document.getElementById('statLoops').textContent = loops;

    document.getElementById('lineageList').innerHTML = lineageJobs.map(j => {
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
function hasEtlLineage(schema, table) {
  return lineageJobs.some(j =>
    (j.source.schema === schema && j.source.table === table) ||
    (j.target.schema === schema && j.target.table === table)
  );
}

function computeRiskReasons(col) {
  if (col.riskReasons && col.riskReasons.length) return col.riskReasons;
  const reasons = [];
  const q = col.quality;
  const ql = {
    missing: 'Açıklama eksik (missing)',
    wrong: 'Yanlış veya tutarsız açıklama (wrong)',
    vague: 'Belirsiz açıklama (vague)',
    english: 'İngilizce açıklama — Türkçe şema bekleniyor',
    incomplete: 'Eksik açıklama (incomplete)',
  };
  if (ql[q] && q !== 'generated') reasons.push(ql[q]);
  // issues Risk bölümünde ayrı gösterildiği için buraya eklenmez
  if (!reasons.length && col.risk === 'LOW_RISK')
    reasons.push('Açıklama kalitesi ve metadata göstergeleri yeterli');
  if (!reasons.length && col.risk === 'HIGH_RISK')
    reasons.push('Yüksek risk — metadata kalite göstergeleri yetersiz');
  return reasons;
}

function showPopup(table, colName) {
  const col = allColumns.find(c => c.table === table && c.col === colName);
  if (!col) return;

  const riskCls = col.risk === 'HIGH_RISK' ? 'risk-high' : 'risk-low';
  const riskLbl = col.risk === 'HIGH_RISK' ? '🔴 HIGH RISK' : '🟢 LOW RISK';

  document.getElementById('popupPill').innerHTML =
    `<span class="risk-pill ${riskCls}">${riskLbl}</span>`;
  document.getElementById('popupCol').textContent = col.col;
  document.getElementById('popupTable').textContent = col.schema + '.' + col.table;

  const hasEtl = hasEtlLineage(col.schema, col.table);
  const labels = col.contextLabels || {};
  const frdOk = labels.frd !== undefined ? labels.frd : col.hasFrd;
  const toaOk = labels.toa !== undefined ? labels.toa : col.hasToa;
  const ddlOk = labels.ddl !== undefined ? labels.ddl : col.hasDdl;

  document.getElementById('popupDocs').innerHTML = [
    frdOk ? '<span class="doc-pill ok">FRD ✅</span>' : '<span class="doc-pill miss">FRD ❌</span>',
    toaOk ? '<span class="doc-pill ok">TOA ✅</span>' : '<span class="doc-pill miss">TOA ❌</span>',
    ddlOk ? '<span class="doc-pill ok">DDL ✅</span>' : '<span class="doc-pill miss">DDL ❌</span>',
    hasEtl ? '<span class="doc-pill ok">ETL ✅</span>' : '<span class="doc-pill miss">ETL ❌</span>',
  ].join('');

  const cov = col.coverage || (frdOk || toaOk || ddlOk ? 'with_docs' : 'no_docs');
  document.getElementById('popupCoverage').innerHTML =
    cov === 'with_docs'
      ? '<span class="coverage-badge coverage-with">📄 Bağlam dokümanı mevcut — zenginleştirme bağlam enjeksiyonu ile yapıldı</span>'
      : '<span class="coverage-badge coverage-none">📭 Bağlam dokümanı yok — yalnızca metadata ile zenginleştirme</span>';

  const reasons = computeRiskReasons(col);
  const rCls = col.risk === 'HIGH_RISK' ? 'high' : 'low';
  document.getElementById('popupRiskReasons').innerHTML = reasons.map(r =>
    `<div class="risk-reason ${rCls}">${r}</div>`).join('');

  const beforeEl = document.getElementById('popupBefore');
  const afterEl = document.getElementById('popupAfter');
  if (col.origDesc !== undefined && col.origDesc !== null) {
    beforeEl.innerHTML = col.origDesc
      ? col.origDesc
      : '<span class="compare-missing">(açıklama yoktu)</span>';
  } else if (col.quality === 'generated') {
    beforeEl.innerHTML = '<span class="compare-missing">(orijinal açıklama kaydedilmemiş)</span>';
  } else {
    beforeEl.innerHTML = col.desc
      ? col.desc
      : '<span class="compare-missing">(pipeline henüz çalıştırılmadı)</span>';
  }
  if (col.quality === 'generated' && col.desc) {
    afterEl.innerHTML = col.desc;
  } else if (col.quality === 'generated') {
    afterEl.innerHTML = '<span class="compare-missing">(üretilemedi)</span>';
  } else if (col.desc) {
    afterEl.innerHTML = col.desc + '<br><span class="compare-missing">(pipeline bu kolonu değiştirmedi)</span>';
  } else {
    afterEl.innerHTML = '<span class="compare-missing">(açıklama yok)</span>';
  }

  const fbkEl = document.getElementById('popupFeedback');
  const fbkTitle = document.getElementById('feedbackTitle');
  if (col.feedback) {
    fbkTitle.style.display = 'block';
    fbkEl.style.display = 'block';
    fbkEl.textContent = col.feedback;
  } else {
    fbkTitle.style.display = 'none';
    fbkEl.style.display = 'none';
  }

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
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    print("\n🚀 Metadata Intelligence Platform v0.0.1")
    print(f"   Open: http://127.0.0.1:{port}\n")
    app.run(debug=debug, host="0.0.0.0", port=port)
