"""
Metadata Intelligence Platform — Web UI  v2.0
==============================================
Flask backend + inline HTML/JS dashboard.

Yenilikler (v2.0):
  - 0-100 sürekli risk skoru (binary HIGH/LOW kaldırıldı)
  - Bankacılık sektörü odaklı Clarity Scorer (eşik: 80)
  - Before → After açıklama karşılaştırması popup'ta
  - FRD / TOA / DDL kaynak durumu göstergesi
  - Pipeline terminal çıktısı UI'da canlı gösterim
  - Risk dağılım bar chart (oransal, 3 bant)
  - Tüm yeni agent/scorer güncellemeleriyle uyumlu

Çalıştırmak için:
    pip install flask
    export GEMINI_API_KEY=your_key
    python app.py  →  http://localhost:5000
"""

import json, os, sys, threading
from pathlib import Path
from flask import Flask, jsonify, render_template_string

ROOT = Path(__file__).parent
app  = Flask(__name__)

pipeline_state = {
    "status": "idle", "step": "", "progress": 0,
    "log": [], "results": None, "error": None,
}

def log(msg):
    print(msg)
    pipeline_state["log"].append(msg)

def run_pipeline_bg():
    try:
        pipeline_state.update({"status":"running","log":[],"results":None,"error":None})
        sys.path.insert(0, str(ROOT/"agents"))
        sys.path.insert(0, str(ROOT/"scripts"))

        pipeline_state.update({"step":"Loading tables","progress":5})
        from generator_agent import load_json, run_generator
        tables = load_json(ROOT/"data"/"tables"/"synthetic_tables.json")
        log(f"✅ Loaded {len(tables)} tables, {sum(len(t.get('columns',[])) for t in tables)} columns")

        pipeline_state.update({"step":"Generator Agent — context-aware enrichment","progress":15})
        log("🤖 Generator Agent: injecting DDL / FRD / TOA context per column...")
        enriched = run_generator(tables)
        log("✅ Generator complete — column-name fallback applied for null entries")

        pipeline_state.update({"step":"Critic Agent — banking sector evaluation","progress":35})
        from critic_agent import run_critic
        log("🔍 Critic Agent: 6-dim scoring (domain, value range, reference, business rule, language, detail)...")
        critic_results = run_critic(enriched)
        log("✅ Critic complete — threshold 80/100")

        critic_map = {r["table_name"]: r for r in critic_results}
        for table in enriched:
            tcrit = critic_map.get(table["table_name"], {})
            col_evals = {e["column_name"]: e for e in tcrit.get("column_evaluations", [])}
            for col in table.get("columns", []):
                ev = col_evals.get(col["column_name"], {})
                col["critic_score"]       = ev.get("overall_score")
                col["needs_regeneration"] = ev.get("needs_regeneration", False)
                col["issues"]             = ev.get("issues", [])
                col["feedback"]           = ev.get("feedback", "")
                col.setdefault("original_description", col.get("description"))

        pipeline_state.update({"step":"Re-generation loop","progress":55})
        for attempt in range(2):
            regen_needed = [
                dict(t, columns=[c for c in t.get("columns",[]) if c.get("needs_regeneration")])
                for t in enriched
                if any(c.get("needs_regeneration") for c in t.get("columns",[]))
            ]
            if not regen_needed:
                log(f"✅ No re-generation needed after attempt {attempt+1}"); break
            n = sum(len(t["columns"]) for t in regen_needed)
            log(f"🔄 Re-generation attempt {attempt+1}: {n} columns below threshold")
            regen_enriched = run_generator(regen_needed)
            run_critic(regen_enriched)
            regen_map = {t["table_name"]: t for t in regen_enriched}
            for i, table in enumerate(enriched):
                if table["table_name"] in regen_map:
                    rc_map = {c["column_name"]: c for c in regen_map[table["table_name"]]["columns"]}
                    for j, col in enumerate(enriched[i]["columns"]):
                        if col["column_name"] in rc_map:
                            enriched[i]["columns"][j] = rc_map[col["column_name"]]

        pipeline_state.update({"step":"Clarity Scorer — banking sector (threshold 80)","progress":68})
        from clarity_scorer import score_all, CLARITY_THRESHOLD
        log(f"📊 Clarity Scorer: bankacılık yeterlilik skoru (eşik: {CLARITY_THRESHOLD}/100)...")
        clarity = score_all(enriched)
        log("✅ Clarity scoring complete")

        pipeline_state.update({"step":"Risk Classifier — 0-100 continuous score","progress":80})
        from risk_classifier import classify_all_risks
        log("⚡ Risk Classifier: 0-100 continuous score (≥60 High, 30-59 Mid, <30 Low)...")
        risk_report = classify_all_risks(enriched)
        s = risk_report["summary"]
        log(f"✅ Risk done — 🔴 High: {s.get('yuksek_risk_count','?')}  🟡 Mid: {s.get('orta_risk_count','?')}  🟢 Low: {s.get('dusuk_risk_count','?')}")

        pipeline_state.update({"step":"Lineage Crawler — DFS loop detection","progress":90})
        from lineage_crawler import build_lineage_graph
        log("🔗 Crawling ETL lineage...")
        graph, loops = build_lineage_graph(str(ROOT/"data"/"etl"/"lineage.json"))
        log(f"✅ Lineage: {len(graph)} nodes, {len(loops)} loop(s)")
        for lp in loops: log(f"   ⚠ LOOP: {lp}")

        pipeline_state.update({"step":"Saving","progress":97})
        final = {
            "tables": enriched,
            "risk_report": risk_report,
            "clarity_scores": clarity,
            "lineage_graph": {k:v for k,v in graph.items()},
            "lineage_loops": loops,
            "config": {"clarity_threshold": CLARITY_THRESHOLD, "regeneration_threshold": 80},
        }
        out = ROOT/"data"/"tables"/"final_output.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(final, ensure_ascii=False, indent=2), "utf-8")
        pipeline_state.update({"results":final,"status":"done","progress":100,"step":"Complete"})
        log("🎉 Pipeline complete!")

    except Exception as e:
        import traceback
        pipeline_state.update({"status":"error","error":str(e),"step":"Error"})
        log(f"❌ Error: {e}")
        log(traceback.format_exc())

def load_existing_results():
    p = ROOT/"data"/"tables"/"final_output.json"
    if p.exists():
        try:
            pipeline_state.update({"results":json.loads(p.read_text("utf-8")),"status":"done","step":"Loaded from cache"})
        except Exception: pass

# ── Risk & Clarity injection ──────────────────────────────────────────────────
# Penalty map for description_quality → base risk contribution
_QUALITY_PENALTY = {"missing":40,"wrong":35,"english":25,"vague":20,"incomplete":15,"complete":0,"generated":0}
_BANKING_TERMS = ["hesap","kredi","müşteri","şube","bakiye","faiz","vade","iban","döviz",
                  "segment","risk","npl","kobi","teminat","limit","lkp","lookup","referans",
                  "kod","tarih","tutar","açılış","valör","durum","tip","sınıf","grup",
                  "birincil anahtar","fk","pk","tablosundan","tablosunun","banka"]
_ENGLISH_IND = ["the ","is a","this ","account","status","code ","date ","number","active","closed"]

def _compute_risk_score(col: dict) -> int:
    score = 0
    q = col.get("description_quality","")
    score += _QUALITY_PENALTY.get(q, 10)
    if col.get("validation_issue"): score += 25
    distinct = col.get("distinct_count")
    if distinct is not None and int(distinct) < 100 and not col.get("has_lookup",False): score += 20
    if q == "english": score += 10
    if col.get("risk_level") == "HIGH_RISK" and score < 60: score = max(score, 62)
    return min(100, score)

def _compute_clarity_score(col: dict) -> int:
    desc = (col.get("description") or "").strip()
    if not desc: return 0
    if len(desc) < 10: return 10
    words = desc.split()
    if len(words) <= 2: return 20
    d = desc.lower()
    # English penalty
    en_count = sum(1 for e in _ENGLISH_IND if e in d)
    if en_count >= 3: return 25
    # Banking context bonus
    bank_hits = sum(1 for t in _BANKING_TERMS if t in d)
    base = 45
    if bank_hits >= 3: base = 72
    elif bank_hits >= 1: base = 55
    if col.get("has_lookup") and ("lkp" in d or "lookup" in d or "tablosundan" in d): base += 12
    if col.get("fk_table") and (col["fk_table"].lower() in d or "birincil anahtar" in d): base += 8
    if col.get("validation_issue"): base -= 15
    if len(desc) > 100: base += 8
    # Column-name-only check
    col_norm = col.get("column_name","").lower().replace("_"," ")
    if col_norm in d and len(words) <= 4: base -= 30
    return max(0, min(100, base))

def enrich_tables(data: dict) -> dict:
    """
    Inject risk_score and clarity_score into every column if missing.
    Works on both final_output.json and raw synthetic_tables.json.
    Also injects original_description if missing (first-run scenario).
    """
    import copy
    data = copy.deepcopy(data)
    tables = data.get("tables", [])

    # Build a risk_report summary if not present
    all_risk = []
    for table in tables:
        for col in table.get("columns", []):
            # original_description fallback
            if "original_description" not in col:
                col["original_description"] = col.get("description")

            # risk_score
            if col.get("risk_score") is None:
                col["risk_score"] = _compute_risk_score(col)

            # clarity_score
            if col.get("clarity_score") is None:
                col["clarity_score"] = _compute_clarity_score(col)

            # risk_band from score
            rs = col["risk_score"]
            col["risk_band"] = "YÜKSEK" if rs >= 60 else "ORTA" if rs >= 30 else "DÜŞÜK"

            # issues list
            if not col.get("issues"):
                issues = []
                if col.get("validation_issue"): issues.append("VALUE MISMATCH: " + col["validation_issue"])
                d = col.get("distinct_count")
                if d and int(d) < 100 and not col.get("has_lookup",False):
                    issues.append(f"LOOKUP GAP: {d} distinct values, no LKP table defined")
                if col.get("description_quality") == "english":
                    issues.append("Language inconsistency: Turkish schema with English description")
                if col.get("description_quality") == "wrong":
                    issues.append("Factual mismatch detected in description")
                col["issues"] = issues

            all_risk.append(col["risk_score"])

    # Rebuild risk_report summary if absent or stale
    n = len(all_risk)
    if n:
        hi  = sum(1 for s in all_risk if s >= 60)
        mid = sum(1 for s in all_risk if 30 <= s < 60)
        lo  = sum(1 for s in all_risk if s < 30)
        avg = round(sum(all_risk) / n, 1)
        data["risk_report"] = data.get("risk_report") or {}
        data["risk_report"]["summary"] = {
            "total_columns":     n,
            "avg_risk_score":    avg,
            "yuksek_risk_count": hi,
            "orta_risk_count":   mid,
            "dusuk_risk_count":  lo,
            "yuksek_risk_pct":   round(hi/n*100, 1),
            "orta_risk_pct":     round(mid/n*100, 1),
            "dusuk_risk_pct":    round(lo/n*100, 1),
        }
        # clarity summary
        clarities = [col.get("clarity_score",0) for t in tables for col in t.get("columns",[])]
        below = sum(1 for c in clarities if c < 80)
        data.setdefault("clarity_scores", {})["__summary__"] = {
            "total_columns":  n,
            "average_score":  round(sum(clarities)/n, 1) if clarities else 0,
            "below_threshold": below,
            "risk_ratio_pct":  round(below/n*100, 1) if n else 0,
            "threshold": 80,
        }
        data["config"] = data.get("config") or {"clarity_threshold": 80, "regeneration_threshold": 80}

    return data

@app.route("/api/status")
def api_status():
    return jsonify({k:pipeline_state[k] for k in ("status","step","progress","error")} | {"log":pipeline_state["log"][-30:]})

@app.route("/api/run", methods=["POST"])
def api_run():
    if pipeline_state["status"] == "running":
        return jsonify({"error":"Already running"}), 400
    threading.Thread(target=run_pipeline_bg, daemon=True).start()
    return jsonify({"ok":True})

@app.route("/api/results")
def api_results():
    raw = None
    if pipeline_state["results"]:
        raw = pipeline_state["results"]
    else:
        # Try final_output.json first, then synthetic_tables.json as preview
        p1 = ROOT/"data"/"tables"/"final_output.json"
        p2 = ROOT/"data"/"tables"/"synthetic_tables.json"
        if p1.exists():
            try: raw = json.loads(p1.read_text("utf-8"))
            except Exception: pass
        if raw is None and p2.exists():
            try: raw = {"tables": json.loads(p2.read_text("utf-8")), "preview": True}
            except Exception: pass
    if raw is None:
        return jsonify({"error":"No results — run the pipeline first"}), 404
    return jsonify(enrich_tables(raw))

@app.route("/api/lineage")
def api_lineage():
    p = ROOT/"data"/"etl"/"lineage.json"
    return jsonify(json.loads(p.read_text("utf-8"))) if p.exists() else (jsonify({"error":"No lineage"}),404)


HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Metadata Intelligence Platform — Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap" rel="stylesheet"/>
<style>
:root {
  --bg: #060a12;
  --surface: #0d1524;
  --surface2: #121d2e;
  --surface3: #172236;
  --border: #1e2f48;
  --accent: #00d4ff;
  --accent2: #7c3aed;
  --high: #ff4757;
  --mid: #ffa502;
  --low: #2ed573;
  --text: #dde6f0;
  --muted: #5a7296;
  --mono: 'IBM Plex Mono', monospace;
  --sans: 'IBM Plex Sans', sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  min-height: 100vh;
  overflow-x: hidden;
}
body::before {
  content: '';
  position: fixed; inset: 0;
  background-image:
    linear-gradient(rgba(0,212,255,.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,212,255,.025) 1px, transparent 1px);
  background-size: 44px 44px;
  pointer-events: none; z-index: 0;
}

.wrap { position: relative; z-index: 1; max-width: 1480px; margin: 0 auto; padding: 22px 28px; }

/* ── Header ─────────────────────────────────────────────────────────────── */
header {
  display: flex; align-items: flex-start; justify-content: space-between;
  border-bottom: 1px solid var(--border); padding-bottom: 18px; margin-bottom: 24px;
  gap: 20px; flex-wrap: wrap;
}
.logo h1 { font-size: 1.35rem; font-weight: 700; color: var(--accent); letter-spacing: -.02em; }
.logo h1 span { color: var(--text); }
.logo p { font-family: var(--mono); font-size: .65rem; color: var(--muted); margin-top: 3px; }
.status-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 4px; }
.badge {
  font-family: var(--mono); font-size: .6rem; padding: 3px 9px; border-radius: 2px;
  font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
}
.bg  { background: rgba(46,213,115,.12);  color: var(--low);    border: 1px solid rgba(46,213,115,.25); }
.br  { background: rgba(255,71,87,.12);   color: var(--high);   border: 1px solid rgba(255,71,87,.25); }
.bb  { background: rgba(0,212,255,.1);    color: var(--accent); border: 1px solid rgba(0,212,255,.2); }
.bw  { background: rgba(255,165,2,.1);    color: var(--mid);    border: 1px solid rgba(255,165,2,.2); }

/* ── Stats ───────────────────────────────────────────────────────────────── */
.stats {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px; margin-bottom: 24px;
}
.stat-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 4px;
  padding: 16px 18px; position: relative; overflow: hidden;
}
.stat-card::before { content:''; position:absolute; top:0; left:0; right:0; height:2px; }
.sc-red::before    { background: var(--high); }
.sc-mid::before    { background: var(--mid); }
.sc-green::before  { background: var(--low); }
.sc-blue::before   { background: var(--accent); }
.sc-purple::before { background: var(--accent2); }
.stat-num { font-family: var(--mono); font-size: 2rem; font-weight: 600; line-height:1; margin-bottom:5px; }
.sc-red    .stat-num { color: var(--high); }
.sc-mid    .stat-num { color: var(--mid); }
.sc-green  .stat-num { color: var(--low); }
.sc-blue   .stat-num { color: var(--accent); }
.sc-purple .stat-num { color: var(--accent2); }
.stat-label { font-size: .68rem; color: var(--muted); text-transform: uppercase; letter-spacing: .07em; font-weight: 600; }
.stat-sub   { font-family: var(--mono); font-size: .6rem; color: var(--muted); margin-top: 4px; }

/* ── Risk bar ─────────────────────────────────────────────────────────────── */
.risk-bar-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 18px 22px; margin-bottom: 24px; }
.risk-bar-title { font-family: var(--mono); font-size: .7rem; text-transform: uppercase; letter-spacing: .1em; color: var(--accent); margin-bottom: 14px; }
.risk-bar-track { display: flex; height: 12px; border-radius: 3px; overflow: hidden; gap: 2px; }
.rbt-high   { background: var(--high); transition: width .8s ease; }
.rbt-mid    { background: var(--mid);  transition: width .8s ease; }
.rbt-low    { background: var(--low);  transition: width .8s ease; }
.risk-legend { display: flex; gap: 22px; margin-top: 10px; flex-wrap: wrap; }
.rl-item { display: flex; align-items: center; gap: 6px; font-size: .72rem; }
.rl-dot  { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

/* ── Main grid ───────────────────────────────────────────────────────────── */
.main-grid { display: grid; grid-template-columns: 1fr 320px; gap: 20px; align-items: start; }
@media (max-width: 960px) { .main-grid { grid-template-columns: 1fr; } }

/* ── Panel ───────────────────────────────────────────────────────────────── */
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 4px; overflow: hidden; margin-bottom: 18px; }
.panel-header {
  padding: 11px 16px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
  background: var(--surface2);
}
.panel-title { font-family: var(--mono); font-size: .68rem; text-transform: uppercase; letter-spacing: .1em; color: var(--accent); font-weight: 600; }

/* ── Filter bar ──────────────────────────────────────────────────────────── */
.filter-bar { display: flex; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.fbtn {
  font-family: var(--mono); font-size: .6rem; font-weight: 600; padding: 4px 12px;
  border: 1px solid var(--border); border-radius: 2px; cursor: pointer;
  background: transparent; color: var(--muted); letter-spacing: .06em; text-transform: uppercase;
  transition: all .15s;
}
.fbtn:hover { color: var(--text); border-color: var(--accent); }
.fbtn.fa { color: var(--accent); border-color: var(--accent); background: rgba(0,212,255,.08); }
.fbtn.fr { color: var(--high);   border-color: var(--high);   background: rgba(255,71,87,.08); }
.fbtn.fm { color: var(--mid);    border-color: var(--mid);    background: rgba(255,165,2,.08); }
.fbtn.fg { color: var(--low);    border-color: var(--low);    background: rgba(46,213,115,.08); }

/* ── Column table ─────────────────────────────────────────────────────────── */
.tbl-wrap { overflow-x: auto; }
.col-table { width: 100%; border-collapse: collapse; }
.col-table th {
  font-family: var(--mono); font-size: .58rem; text-transform: uppercase; letter-spacing: .08em;
  color: var(--muted); font-weight: 600; padding: 8px 14px; text-align: left;
  border-bottom: 1px solid var(--border); background: var(--surface2); white-space: nowrap;
}
.col-table td { padding: 9px 14px; font-size: .76rem; border-bottom: 1px solid rgba(30,47,72,.5); vertical-align: middle; }
.col-table tr:last-child td { border-bottom: none; }
.col-table tr:hover td { background: rgba(0,212,255,.025); }
.col-table tr.risk-high td:first-child { border-left: 2px solid var(--high); }
.col-table tr.risk-mid  td:first-child { border-left: 2px solid var(--mid); }
.col-table tr.risk-low  td:first-child { border-left: 2px solid var(--low); }

.col-name { font-family: var(--mono); font-size: .68rem; color: var(--accent); cursor: pointer; }
.col-name:hover { text-decoration: underline; }
.tbl-label { font-family: var(--mono); font-size: .6rem; color: var(--muted); }
.desc-text { font-size: .74rem; color: var(--text); }
.desc-miss { font-family: var(--mono); font-size: .65rem; color: var(--high); }

/* Score bar */
.sbar { display: flex; align-items: center; gap: 8px; }
.sbar-track { flex: 1; max-width: 80px; height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; }
.sbar-fill  { height: 100%; border-radius: 3px; transition: width .6s ease; }
.sbar-val   { font-family: var(--mono); font-size: .62rem; min-width: 28px; }

/* Risk pill */
.rpill {
  font-family: var(--mono); font-size: .58rem; font-weight: 700; padding: 2px 7px;
  border-radius: 2px; white-space: nowrap; cursor: pointer;
}
.rp-high   { background: rgba(255,71,87,.15);  color: var(--high);   border: 1px solid rgba(255,71,87,.35); }
.rp-mid    { background: rgba(255,165,2,.15);  color: var(--mid);    border: 1px solid rgba(255,165,2,.35); }
.rp-low    { background: rgba(46,213,115,.12); color: var(--low);    border: 1px solid rgba(46,213,115,.3); }
.issue-btn { cursor: pointer; font-family: var(--mono); font-size: .6rem; color: var(--mid); padding: 2px 5px; border: 1px solid rgba(255,165,2,.3); border-radius: 2px; }
.issue-btn:hover { background: rgba(255,165,2,.1); }

/* ── Terminal log panel ──────────────────────────────────────────────────── */
.term-wrap { max-height: 340px; overflow-y: auto; }
.term-log {
  font-family: var(--mono); font-size: .62rem; line-height: 1.7;
  padding: 14px 16px; color: var(--muted);
}
.tl-info   { color: var(--accent); }
.tl-ok     { color: var(--low); }
.tl-warn   { color: var(--mid); }
.tl-err    { color: var(--high); }
.tl-table  { color: #a78bfa; font-weight: 600; }
.tl-col    { color: var(--text); }
.tl-ded    { color: var(--high); }
.tl-bon    { color: var(--low); }
.tl-sep    { color: var(--border); }

/* ── Lineage ─────────────────────────────────────────────────────────────── */
.lin-node { display: flex; align-items: center; gap: 8px; padding: 8px 16px; border-bottom: 1px solid rgba(30,47,72,.4); font-size: .73rem; }
.lin-src, .lin-tgt { font-family: var(--mono); font-size: .65rem; color: var(--text); }
.lin-arr { color: var(--muted); }
.lin-loop { font-family: var(--mono); font-size: .55rem; font-weight: 700; padding: 1px 5px; background: rgba(255,165,2,.15); color: var(--mid); border: 1px solid rgba(255,165,2,.3); border-radius: 2px; margin-left: auto; }

/* ── Daily report ────────────────────────────────────────────────────────── */
.daily-card { padding: 12px 16px; border-bottom: 1px solid rgba(30,47,72,.4); }
.daily-card:last-child { border-bottom: none; }
.daily-name { font-family: var(--mono); font-size: .62rem; color: var(--accent); margin-bottom: 7px; }
.daily-act  { display: flex; gap: 7px; font-size: .72rem; margin-bottom: 4px; line-height: 1.5; }
.daily-icon { flex-shrink: 0; width: 16px; }

/* Doc status pills */
.doc-pills { display: flex; gap: 6px; flex-wrap: wrap; }
.doc-pill { font-family: var(--mono); font-size: .55rem; padding: 2px 7px; border-radius: 2px; font-weight: 600; }
.dp-ok { background: rgba(46,213,115,.1); color: var(--low); border: 1px solid rgba(46,213,115,.25); }
.dp-miss { background: rgba(255,71,87,.1); color: var(--high); border: 1px solid rgba(255,71,87,.25); }

/* ── POPUP ───────────────────────────────────────────────────────────────── */
.popup-ov {
  position: fixed; inset: 0; background: rgba(0,0,0,.7); z-index: 1000;
  display: none; align-items: center; justify-content: center; padding: 20px;
  backdrop-filter: blur(4px);
}
.popup-ov.active { display: flex; }
.popup-box {
  background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
  padding: 28px 30px; max-width: 640px; width: 100%; position: relative;
  box-shadow: 0 24px 80px rgba(0,0,0,.7);
  max-height: 90vh; overflow-y: auto;
}
.popup-close {
  position: absolute; top: 14px; right: 16px; background: none; border: none;
  color: var(--muted); font-size: 1rem; cursor: pointer; font-family: var(--mono);
}
.popup-close:hover { color: var(--high); }
.popup-header { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 20px; }
.popup-meta { flex: 1; }
.popup-colname  { font-family: var(--mono); font-size: 1rem; font-weight: 600; color: var(--accent); }
.popup-tblname  { font-family: var(--mono); font-size: .65rem; color: var(--muted); margin-top: 3px; }
.popup-score-big { font-family: var(--mono); font-size: 1.8rem; font-weight: 700; line-height:1; }

.popup-sec-title {
  font-family: var(--mono); font-size: .6rem; text-transform: uppercase; letter-spacing: .1em;
  color: var(--muted); margin: 16px 0 7px; border-top: 1px solid var(--border); padding-top: 14px;
}
.popup-sec-title:first-of-type { margin-top: 0; border-top: none; padding-top: 0; }

/* Before / After comparison */
.compare-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 540px) { .compare-grid { grid-template-columns: 1fr; } }
.compare-box { background: var(--surface3); border: 1px solid var(--border); border-radius: 4px; padding: 12px 14px; }
.compare-label { font-family: var(--mono); font-size: .55rem; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 7px; }
.cl-before { color: var(--high); }
.cl-after  { color: var(--low); }
.compare-text { font-size: .75rem; line-height: 1.6; color: var(--text); }
.compare-missing { font-family: var(--mono); font-size: .68rem; color: var(--muted); font-style: italic; }

.score-breakdown { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.sb-item { background: var(--surface3); border-radius: 3px; padding: 8px 10px; }
.sb-label { font-family: var(--mono); font-size: .55rem; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
.sb-val   { font-family: var(--mono); font-size: .85rem; font-weight: 600; margin-top: 2px; }

.popup-issues { display: flex; flex-direction: column; gap: 6px; }
.pi-item { display: flex; gap: 8px; font-size: .73rem; line-height: 1.5; }
.pi-icon { flex-shrink: 0; font-family: var(--mono); font-size: .65rem; color: var(--mid); }

.popup-factors { display: flex; flex-direction: column; gap: 5px; }
.pf-item { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; font-size: .7rem; }
.pf-label { color: var(--text); flex: 1; line-height: 1.4; }
.pf-pts-ded { font-family: var(--mono); font-size: .62rem; color: var(--high); white-space: nowrap; }
.pf-pts-bon { font-family: var(--mono); font-size: .62rem; color: var(--low); white-space: nowrap; }

.doc-avail { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }

/* Scrollbar */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--surface); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>
<div class="wrap">

<!-- Header -->
<header>
  <div class="logo">
    <h1>Metadata <span>Intelligence</span> Platform</h1>
    <p>// Bankacılık Metadata Kalitesi & Risk Analizi — v2.0</p>
  </div>
  <div class="status-bar">
    <span class="badge bb">Pipeline: Active</span>
    <span class="badge bg" id="pipeline-status">✓ Critic Pass</span>
    <span class="badge bw" id="loop-badge">⚠ 1 Loop</span>
  </div>
</header>

<!-- Stats -->
<div class="stats">
  <div class="stat-card sc-red">
    <div class="stat-num" id="stat-high">0</div>
    <div class="stat-label">Yüksek Risk</div>
    <div class="stat-sub" id="stat-high-pct">—</div>
  </div>
  <div class="stat-card sc-mid">
    <div class="stat-num" id="stat-mid">0</div>
    <div class="stat-label">Orta Risk</div>
    <div class="stat-sub" id="stat-mid-pct">—</div>
  </div>
  <div class="stat-card sc-green">
    <div class="stat-num" id="stat-low">0</div>
    <div class="stat-label">Düşük Risk</div>
    <div class="stat-sub" id="stat-low-pct">—</div>
  </div>
  <div class="stat-card sc-blue">
    <div class="stat-num" id="stat-avg-clarity">—</div>
    <div class="stat-label">Avg Clarity</div>
    <div class="stat-sub">Bankacılık skoru /100</div>
  </div>
  <div class="stat-card sc-purple">
    <div class="stat-num" id="stat-loops">1</div>
    <div class="stat-label">Lineage Loop</div>
    <div class="stat-sub">CRM ↔ RISK döngüsü</div>
  </div>
</div>

<!-- Risk dağılım bar -->
<div class="risk-bar-wrap">
  <div class="risk-bar-title">// Risk Dağılımı (Kolon Bazlı Oran)</div>
  <div class="risk-bar-track">
    <div class="rbt-high" id="rb-high" style="width:0%"></div>
    <div class="rbt-mid"  id="rb-mid"  style="width:0%"></div>
    <div class="rbt-low"  id="rb-low"  style="width:0%"></div>
  </div>
  <div class="risk-legend">
    <div class="rl-item"><div class="rl-dot" style="background:var(--high)"></div><span id="rl-high-label">Yüksek —</span></div>
    <div class="rl-item"><div class="rl-dot" style="background:var(--mid)"></div><span id="rl-mid-label">Orta —</span></div>
    <div class="rl-item"><div class="rl-dot" style="background:var(--low)"></div><span id="rl-low-label">Düşük —</span></div>
  </div>
</div>

<!-- Main grid -->
<div class="main-grid">
  <div>

    <!-- Column table -->
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">// Kolon Değerlendirme Tablosu</span>
        <span class="badge bb" id="col-count-badge">— kolon</span>
      </div>
      <div class="filter-bar">
        <button class="fbtn fa" onclick="filterTable('all',this)">Tümü</button>
        <button class="fbtn fr" onclick="filterTable('high',this)">🔴 Yüksek</button>
        <button class="fbtn fm" onclick="filterTable('mid',this)">🟡 Orta</button>
        <button class="fbtn fg" onclick="filterTable('low',this)">🟢 Düşük</button>
      </div>
      <div class="tbl-wrap">
        <table class="col-table">
          <thead>
            <tr>
              <th>Tablo</th>
              <th>Kolon</th>
              <th>Açıklama (son hal)</th>
              <th>Risk Skoru</th>
              <th>Clarity</th>
              <th>Sorunlar</th>
            </tr>
          </thead>
          <tbody id="colTbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Terminal log -->
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">// Pipeline Terminal Çıktısı</span>
        <span class="badge bb">Simüle Edilmiş</span>
      </div>
      <div class="term-wrap">
        <div class="term-log" id="termLog"></div>
      </div>
    </div>

  </div>

  <!-- Right sidebar -->
  <div>

    <!-- Lineage -->
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">// ETL Lineage</span>
        <span class="badge bw">⚠ Loop</span>
      </div>
      <div id="lineageContainer"></div>
    </div>

    <!-- Daily report -->
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">// Günlük Rapor</span>
        <span class="badge bg">UI Verified</span>
      </div>
      <div id="dailyContainer"></div>
    </div>

  </div>
</div>
</div><!-- /wrap -->

<!-- ════════════════════ POPUP ════════════════════ -->
<div class="popup-ov" id="popup" onclick="closePopup(event)">
<div class="popup-box">
  <button class="popup-close" onclick="closePopup()">✕</button>

  <div class="popup-header">
    <div class="popup-meta">
      <div class="popup-colname" id="pp-colname"></div>
      <div class="popup-tblname" id="pp-tblname"></div>
      <div style="margin-top:8px" id="pp-doc-avail"></div>
    </div>
    <div>
      <div class="popup-score-big" id="pp-score-big"></div>
      <div style="font-family:var(--mono);font-size:.6rem;color:var(--muted);margin-top:3px">risk skoru /100</div>
    </div>
  </div>

  <!-- Before / After -->
  <div class="popup-sec-title">Açıklama — İlk Hal → Son Hal</div>
  <div class="compare-grid">
    <div class="compare-box">
      <div class="compare-label cl-before">◀ Önceki (ham)</div>
      <div id="pp-before"></div>
    </div>
    <div class="compare-box">
      <div class="compare-label cl-after">▶ Üretilen (son)</div>
      <div id="pp-after"></div>
    </div>
  </div>

  <!-- Score breakdown -->
  <div class="popup-sec-title">Clarity Skoru Kırılımı</div>
  <div class="score-breakdown" id="pp-breakdown"></div>

  <!-- Deductions / Bonuses -->
  <div id="pp-factors-section">
    <div class="popup-sec-title">Puan Detayı</div>
    <div class="popup-factors" id="pp-factors"></div>
  </div>

  <!-- Issues -->
  <div id="pp-issues-section">
    <div class="popup-sec-title">Tespit Edilen Sorunlar</div>
    <div class="popup-issues" id="pp-issues"></div>
  </div>

  <!-- Feedback -->
  <div id="pp-feedback-section">
    <div class="popup-sec-title">Critic Önerisi</div>
    <div id="pp-feedback" style="font-size:.76rem;line-height:1.6;color:var(--text);background:var(--surface3);padding:10px 12px;border-radius:3px;border:1px solid var(--border);"></div>
  </div>

</div>
</div>

<script>
// ═══════════════════════════════════════════════════════
// DATA — Güncellenmiş skor bazlı veri modeli
// ═══════════════════════════════════════════════════════
const COLUMNS = [
  {
    table: "CORE_BANKING.XXX_HESAP", col: "HESAP_NO",
    original_desc: "Hesap numarasıdır.",
    desc: "CORE_BANKING.XXX_HESAP tablosundaki hesabın benzersiz IBAN formatındaki tanımlayıcısıdır. 26 karakter olup TR + 2 kontrol hanesi + 4 banka kodu + 16 hesap numarasından oluşur.",
    risk_score: 12, clarity: 88,
    issues: [],
    feedback: "İş kuralı ve format bilgisi eklenmiş. Yeterli.",
    deductions: [], bonuses: [["Bankacılık terminolojisi kullanılmış", 5], ["FK referans tablosu açıklamada belirtilmiş", 8]],
    breakdown: {domain: 25, value_range: 20, reference: 15, business_rule: 15, language: 10, detail: 8},
    has_frd: true, has_toa: true, has_ddl: true,
    quality: "incomplete"
  },
  {
    table: "CORE_BANKING.XXX_HESAP", col: "ACILIS_TARIHI",
    original_desc: "Açılış tarihidir.",
    desc: "Ticari veya bireysel hesabın resmi açılış tarihidir. Valörlü açılan hesaplarda bu tarih fiziksel açılış değil valör tarihini yansıtır; gerçek açılış için VALOR_TARIHI kolonuna bakılmalıdır.",
    risk_score: 18, clarity: 86,
    issues: [],
    feedback: "Valör ilişkisi ve iş kuralı yansıtılmış. İyi.",
    deductions: [], bonuses: [["Tablo bağlamı dahil edilmiş", 5], ["Bankacılık terminolojisi kullanılmış", 5]],
    breakdown: {domain: 22, value_range: 18, reference: 14, business_rule: 18, language: 10, detail: 9},
    has_frd: true, has_toa: true, has_ddl: true,
    quality: "incomplete"
  },
  {
    table: "CORE_BANKING.XXX_HESAP", col: "VALOR_TARIHI",
    original_desc: "Valör tarihidir.",
    desc: "Valörlü açılan hesaplarda geçerli olan valör tarihidir. Standart hesaplarda bu kolon dolu olmayabilir. ACILIS_TARIHI'nden küçük olamaz; aksi durum validasyon hatası sayılır.",
    risk_score: 15, clarity: 84,
    issues: [],
    feedback: "ACILIS_TARIHI ilişkisi ve validasyon kısıtı eklenmiş.",
    deductions: [], bonuses: [["Bankacılık terminolojisi kullanılmış", 5]],
    breakdown: {domain: 20, value_range: 18, reference: 12, business_rule: 20, language: 10, detail: 9},
    has_frd: true, has_toa: true, has_ddl: true,
    quality: "incomplete"
  },
  {
    table: "CORE_BANKING.XXX_HESAP", col: "HESAP_TIP_KOD",
    original_desc: "Hesap tipi.",
    desc: "LKP_HESAP_TIP tablosundan gelen hesap tipi kodudur. Değerler: 1=Vadesiz, 2=Vadeli, 3=Döviz, 4=Altın, 5=Yatırım.",
    risk_score: 10, clarity: 91,
    issues: [],
    feedback: "Tüm enum değerleri ve lookup referansı mevcut.",
    deductions: [], bonuses: [["Lookup tablosuna doğru atıf yapılmış", 10], ["Tüm olası değerler dokümante edilmiş", 10]],
    breakdown: {domain: 24, value_range: 20, reference: 15, business_rule: 18, language: 10, detail: 9},
    has_frd: true, has_toa: true, has_ddl: true,
    quality: "incomplete"
  },
  {
    table: "CORE_BANKING.XXX_HESAP", col: "HESAP_DURUM_KOD",
    original_desc: "Account status code.",
    desc: "Hesabın durum bilgisini taşır. Bilinen değerler: 0=Aktif, 1=Pasif, 2=Kapalı. ⚠ LKP tablosu tanımlanmamıştır; veritabanında belgelenmemiş '3' değeri de tespit edilmiştir.",
    risk_score: 72, clarity: 55,
    issues: [
      "Türkçe şemada İngilizce orijinal açıklama",
      "Value mismatch: belgelenen [0,1,2] ama DB'de 3 değeri de mevcut",
      "Düşük kardinalite (3 distinct) — LKP tablosu yok"
    ],
    feedback: "Validation hatası ve LKP eksikliği giderilmeli. Değer 3 için iş kuralı netleştirilmeli.",
    deductions: [["Türkçe şemada İngilizce açıklama", 25], ["Validation hatası var", 15], ["LKP tablosu yok", 20]],
    bonuses: [["Bilinen değerler enumere edilmiş", 10]],
    breakdown: {domain: 12, value_range: 10, reference: 5, business_rule: 8, language: 5, detail: 7},
    has_frd: true, has_toa: true, has_ddl: true,
    quality: "english"
  },
  {
    table: "CORE_BANKING.XXX_HESAP", col: "MUSTERI_NO",
    original_desc: "Müşteri numarasıdır. XXX_MUSTERI tablosunun birincil anahtarıdır.",
    desc: "Müşteri numarasıdır. XXX_MUSTERI tablosunun birincil anahtarıdır.",
    risk_score: 8, clarity: 87,
    issues: [],
    feedback: "FK ilişkisi açık belirtilmiş. Yeterli.",
    deductions: [], bonuses: [["FK referans tablosu açıklamada belirtilmiş", 8]],
    breakdown: {domain: 22, value_range: 20, reference: 15, business_rule: 16, language: 10, detail: 9},
    has_frd: true, has_toa: true, has_ddl: true,
    quality: "complete"
  },
  {
    table: "CORE_BANKING.XXX_HESAP", col: "SUBE_KOD",
    original_desc: null,
    desc: "LKP_SUBE tablosundan gelen şube kodudur. FK kısıtı veri modelinde tanımlanmamış olsa da referans ilişkisi mevcuttur. 87 distinct şube değeri içerir.",
    risk_score: 55, clarity: 62,
    issues: [
      "Orijinal açıklama tamamen eksikti",
      "FK kısıtı modelde tanımlı değil — LKP_SUBE referansı çözülmeli"
    ],
    feedback: "Fallback kolon adından üretildi. FK eksikliği bilgisi eklendi.",
    deductions: [["FK ilişkisi var ama modelde kısıt yok", 10], ["Kritik bankacılık kolonu için açıklama zayıf kaldı", 15]],
    bonuses: [["Lookup tablosuna doğru atıf yapılmış", 10]],
    breakdown: {domain: 16, value_range: 14, reference: 10, business_rule: 12, language: 10, detail: 7},
    has_frd: true, has_toa: true, has_ddl: true,
    quality: "missing"
  },
  {
    table: "CREDIT.KRD_MUS_KREDI", col: "KRD_NO",
    original_desc: "Kredi numarasıdır.",
    desc: "CREDIT.KRD_MUS_KREDI tablosundaki kredinin benzersiz tanımlayıcısıdır. Tablonun birincil anahtarıdır, ISLEM_TARIHI ile birlikte bileşik PK oluşturur.",
    risk_score: 42, clarity: 67,
    issues: ["FRD dokümanı mevcut değil", "TOA dokümanı mevcut değil"],
    feedback: "Dokümansız üretim — DDL'den çıkarım yapıldı. FRD hazırlanmalı.",
    deductions: [["Kritik bankacılık kolonu için açıklama kısa", 15], ["Bankacılık bağlamı zayıf", 10]],
    bonuses: [["Bankacılık terminolojisi kullanılmış", 5]],
    breakdown: {domain: 14, value_range: 15, reference: 10, business_rule: 10, language: 10, detail: 8},
    has_frd: false, has_toa: false, has_ddl: true,
    quality: "incomplete"
  },
  {
    table: "CREDIT.KRD_MUS_KREDI", col: "KRD_MUS_KOBI_TIP",
    original_desc: "KOBI TIPININ TUTULACAGI ALAN.",
    desc: "TMMOB tarafından belirlenen müşteri KOBİ tipi kodudur. Değerler: 1=Mikro, 2=Küçük, 3=Orta, 4=Büyük. LKP tablosu henüz tanımlanmamıştır.",
    risk_score: 58, clarity: 63,
    issues: ["LKP tablosu tanımlanmamış (4 distinct değer)", "FRD mevcut değil"],
    feedback: "Enum değerleri açıklama içine eklendi. LKP tanımlanmalı.",
    deductions: [["Düşük kardinalite — LKP yok", 20], ["FRD yokken domain bağlamı zayıf kaldı", 10]],
    bonuses: [["Tüm olası değerler dokümante edilmiş", 10]],
    breakdown: {domain: 16, value_range: 13, reference: 5, business_rule: 12, language: 10, detail: 7},
    has_frd: false, has_toa: false, has_ddl: true,
    quality: "vague"
  },
  {
    table: "CREDIT.KRD_MUS_KREDI", col: "INT_SHK_A_30GCK_ADT_LM",
    original_desc: "Akbank Hariç Kredi Kartı Açık Son 60 gün",
    desc: "Akbank hariç kredi kartı açık bakiyesinin son 30 gün ortalamasıdır. ⚠ Orijinal açıklamada '60 gün' yazıyor ancak kolon adı (30GCK) 30 günü ifade eder — kritik mismatch.",
    risk_score: 82, clarity: 32,
    issues: [
      "KRİTİK MISMATCH: Kolon adı 30GCK (30 gün) ama orijinal açıklama '60 gün' diyor",
      "FRD ve TOA dokümanı mevcut değil — kaynak doğrulaması yapılamadı"
    ],
    feedback: "Açıklama düzeltildi (30 gün) ama kaynak olmadan kesinleştirilemez. İş birimi doğrulaması şart.",
    deductions: [["Açıklamada '60 gün' — KRİTİK MISMATCH", 25], ["Bankacılık bağlamı zayıf", 20], ["FRD yokken doğrulama imkânsız", 15]],
    bonuses: [],
    breakdown: {domain: 8, value_range: 12, reference: 5, business_rule: 4, language: 8, detail: 5},
    has_frd: false, has_toa: false, has_ddl: true,
    quality: "wrong"
  },
  {
    table: "CREDIT.KRD_MUS_KREDI", col: "KRD_TUTAR",
    original_desc: "Kredi tutarı. Müşteriye kullandırılan kredi miktarını TL cinsinden ifade eder.",
    desc: "Kredi tutarı. Müşteriye kullandırılan kredi miktarını TL cinsinden ifade eder.",
    risk_score: 14, clarity: 82,
    issues: [],
    feedback: "Para birimi ve bağlam açık. Yeterli.",
    deductions: [], bonuses: [["Bankacılık terminolojisi kullanılmış", 5]],
    breakdown: {domain: 20, value_range: 18, reference: 12, business_rule: 14, language: 10, detail: 8},
    has_frd: false, has_toa: false, has_ddl: true,
    quality: "complete"
  },
  {
    table: "CREDIT.KRD_MUS_KREDI", col: "KRD_DURUM",
    original_desc: "Credit status. 0=Active, 1=Closed, 2=NPL",
    desc: "Kredi durumu kodudur. Değerler: 0=Aktif, 1=Kapalı, 2=NPL (Takipteki Kredi). LKP tablosu tanımlanmamıştır.",
    risk_score: 65, clarity: 58,
    issues: ["Türkçe şemada İngilizce orijinal açıklama", "LKP tablosu yok (3 distinct)"],
    feedback: "Dil düzeltildi ve değerler Türkçeleştirildi. LKP tanımlanmalı.",
    deductions: [["İngilizce açıklama", 25], ["LKP tablosu yok", 20]],
    bonuses: [["Tüm olası değerler dokümante edilmiş", 10]],
    breakdown: {domain: 14, value_range: 14, reference: 5, business_rule: 10, language: 8, detail: 7},
    has_frd: false, has_toa: false, has_ddl: true,
    quality: "english"
  },
  {
    table: "CRM.MUS_SEGMENTASYON", col: "MUSTERI_NO",
    original_desc: "Müşteri kimlik numarasıdır.",
    desc: "Müşteri kimlik numarasıdır.",
    risk_score: 18, clarity: 75,
    issues: [],
    feedback: "Açıklama yeterli ancak tablo bağlamı eklenebilir.",
    deductions: [["Kritik kolon için bağlam eksik", 10]],
    bonuses: [],
    breakdown: {domain: 18, value_range: 18, reference: 12, business_rule: 14, language: 10, detail: 8},
    has_frd: true, has_toa: false, has_ddl: false,
    quality: "complete"
  },
  {
    table: "CRM.MUS_SEGMENTASYON", col: "SEGMENT_KOD",
    original_desc: null,
    desc: "CRM.MUS_SEGMENTASYON tablosundaki müşteri segmentini belirten koddur. LKP_SEGMENT tablosundan gelir.",
    risk_score: 48, clarity: 65,
    issues: ["Orijinal açıklama eksikti", "TOA dokümanı mevcut değil", "DDL mevcut değil"],
    feedback: "Lookup atfı eklendi. LKP_SEGMENT değerleri açıklamaya henüz eklenemedi — metadata yoktu.",
    deductions: [["Lookup değerleri açıklamada yok", 10], ["TOA ve DDL yokken bağlam sınırlı kaldı", 15]],
    bonuses: [["Lookup tablosuna doğru atıf yapılmış", 10]],
    breakdown: {domain: 16, value_range: 10, reference: 13, business_rule: 12, language: 10, detail: 7},
    has_frd: true, has_toa: false, has_ddl: false,
    quality: "missing"
  },
  {
    table: "CRM.MUS_SEGMENTASYON", col: "GELIR_GRUBU",
    original_desc: "Gelir grubu kodu.",
    desc: "Müşterinin gelir grubunu gösteren koddur. Değerler: 1=Düşük, 2=Alt-Orta, 3=Orta, 4=Üst-Orta, 5=Yüksek. LKP tablosu tanımlı değildir.",
    risk_score: 52, clarity: 61,
    issues: ["LKP tablosu yok (5 distinct değer)", "TOA mevcut değil"],
    feedback: "Enum değerleri tahminle dolduruldu. FRD'den doğrulanmalı.",
    deductions: [["Düşük kardinalite — LKP yok", 20], ["Metadata notlarındaki kural yansıtılmamış", 8]],
    bonuses: [["Tüm olası değerler dokümante edilmiş", 10]],
    breakdown: {domain: 14, value_range: 13, reference: 5, business_rule: 12, language: 10, detail: 7},
    has_frd: true, has_toa: false, has_ddl: false,
    quality: "incomplete"
  },
  {
    table: "RISK.RISK_IZLEME", col: "MUSTERI_NO",
    original_desc: "Müşteri kimlik numarası.",
    desc: "Müşteri kimlik numarası.",
    risk_score: 10, clarity: 80,
    issues: [],
    feedback: "Yeterli.",
    deductions: [], bonuses: [],
    breakdown: {domain: 20, value_range: 18, reference: 12, business_rule: 14, language: 10, detail: 8},
    has_frd: true, has_toa: true, has_ddl: true,
    quality: "complete"
  },
  {
    table: "RISK.RISK_IZLEME", col: "RISK_SKOR",
    original_desc: "0-100 arası risk skoru. Yüksek değer yüksek riski ifade eder.",
    desc: "0-100 arası risk skoru. Yüksek değer yüksek riski ifade eder.",
    risk_score: 8, clarity: 92,
    issues: [],
    feedback: "Değer aralığı ve yorum açık. Mükemmel.",
    deductions: [], bonuses: [["Bankacılık terminolojisi kullanılmış", 5], ["Tüm olası değerler dokümante edilmiş", 10]],
    breakdown: {domain: 23, value_range: 20, reference: 14, business_rule: 20, language: 10, detail: 10},
    has_frd: true, has_toa: true, has_ddl: true,
    quality: "complete"
  },
  {
    table: "RISK.RISK_IZLEME", col: "RISK_SINIF",
    original_desc: "Risk sınıfı.",
    desc: "Müşterinin risk sınıfını belirtir. Değerler: LOW=Düşük Risk, MEDIUM=Orta Risk, HIGH=Yüksek Risk. LKP tablosu tanımlı değildir.",
    risk_score: 45, clarity: 68,
    issues: ["LKP tablosu yok (3 distinct değer)"],
    feedback: "Değerler Türkçe karşılıklarıyla eklendi. LKP tanımlanmalı.",
    deductions: [["Düşük kardinalite — LKP yok", 20]],
    bonuses: [["Tüm olası değerler dokümante edilmiş", 10]],
    breakdown: {domain: 18, value_range: 14, reference: 5, business_rule: 16, language: 10, detail: 7},
    has_frd: true, has_toa: true, has_ddl: true,
    quality: "incomplete"
  },
];

const LINEAGE = [
  { src:"CORE_BANKING.XXX_HESAP",  tgt:"RISK.RISK_IZLEME",       loop:false },
  { src:"CREDIT.KRD_MUS_KREDI",    tgt:"RISK.RISK_IZLEME",       loop:false },
  { src:"RISK.RISK_IZLEME",        tgt:"CRM.MUS_SEGMENTASYON",   loop:true  },
  { src:"CRM.MUS_SEGMENTASYON",    tgt:"RISK.RISK_IZLEME",       loop:true  },
  { src:"CORE_BANKING.XXX_HESAP",  tgt:"CRM.MUS_SEGMENTASYON",   loop:false },
];

const DAILY = [
  {
    name: "Ali K.",
    did:["Generator agent — kolon adından fallback, TOA/FRD kural çıkarımı eklendi",
         "Lookup enum değerleri açıklamaya otomatik ekleme tamamlandı"],
    couldnt:["KRD_MUS_KREDI tablosu FRD'si henüz yok — dokümansız üretim sınırlı"],
    next:["FRD şablonu hazırlanacak","Ortak LKP eksiklik raporu çıkarılacak"]
  },
  {
    name: "Büşra T.",
    did:["Risk skoru 0-100 bazlı sisteme geçildi (HIGH/LOW etiket kaldırıldı)",
         "Bankacılık odaklı clarity scorer tamamlandı — eşik 80"],
    couldnt:["HESAP_DURUM_KOD '3' değeri iş birimiyle henüz netleştirilmedi"],
    next:["Cardinality checker — partitioned tablo optimizasyonu","Validation catch rate güncelleme"]
  },
  {
    name: "Cem Y.",
    did:["Dashboard — ilk hal/son hal karşılaştırması popup'a eklendi",
         "Terminal çıktısı UI'a entegre edildi","Risk dağılım bar chart güncellendi"],
    couldnt:["INT_SHK mismatch kaynağı DB'den doğrulanamadı"],
    next:["Ablation study güncellenecek","UI screenshot alınacak"]
  },
];

// ═══════════════════════════════════════════════════════
// RENDER
// ═══════════════════════════════════════════════════════

function scoreColor(s) {
  if (s >= 60) return 'var(--high)';
  if (s >= 30) return 'var(--mid)';
  return 'var(--low)';
}
function clarityColor(c) {
  if (c >= 80) return 'var(--low)';
  if (c >= 50) return 'var(--mid)';
  return 'var(--high)';
}
function riskBand(s) {
  if (s >= 60) return { label: 'YÜKSEK', cls: 'rp-high', rowCls: 'risk-high' };
  if (s >= 30) return { label: 'ORTA',   cls: 'rp-mid',  rowCls: 'risk-mid'  };
  return             { label: 'DÜŞÜK',  cls: 'rp-low',  rowCls: 'risk-low'  };
}

function renderTable(filter = 'all') {
  const tbody = document.getElementById('colTbody');
  let filtered = filter === 'all' ? COLUMNS
    : filter === 'high' ? COLUMNS.filter(c => c.risk_score >= 60)
    : filter === 'mid'  ? COLUMNS.filter(c => c.risk_score >= 30 && c.risk_score < 60)
    : COLUMNS.filter(c => c.risk_score < 30);

  tbody.innerHTML = filtered.map(col => {
    const rb  = riskBand(col.risk_score);
    const cc  = clarityColor(col.clarity);
    const descHtml = col.desc
      ? `<span class="desc-text">${col.desc.length > 75 ? col.desc.slice(0,75) + '…' : col.desc}</span>`
      : `<span class="desc-miss">— eksik —</span>`;
    const issBtn = col.issues.length
      ? `<span class="issue-btn" onclick="showPopup('${col.table}','${col.col}')">⚠ ${col.issues.length}</span>`
      : `<span style="color:var(--muted);font-size:.65rem">—</span>`;

    return `<tr class="${rb.rowCls}">
      <td><span class="tbl-label">${col.table}</span></td>
      <td><span class="col-name" onclick="showPopup('${col.table}','${col.col}')">${col.col}</span></td>
      <td>${descHtml}</td>
      <td>
        <span class="rpill ${rb.cls}" onclick="showPopup('${col.table}','${col.col}')">
          ${col.risk_score}/100
        </span>
        <span style="font-family:var(--mono);font-size:.55rem;color:var(--muted);margin-left:5px">${rb.label}</span>
      </td>
      <td>
        <div class="sbar">
          <div class="sbar-track"><div class="sbar-fill" style="width:${col.clarity}%;background:${cc}"></div></div>
          <span class="sbar-val" style="color:${cc}">${col.clarity}</span>
        </div>
      </td>
      <td>${issBtn}</td>
    </tr>`;
  }).join('');
}

function filterTable(f, btn) {
  document.querySelectorAll('.fbtn').forEach(b => b.className = 'fbtn');
  const map = { all: 'fa', high: 'fr', mid: 'fm', low: 'fg' };
  btn.classList.add(map[f]);
  renderTable(f);
}

// ── Lineage ────────────────────────────────────────────────────────────────
function renderLineage() {
  document.getElementById('lineageContainer').innerHTML = LINEAGE.map(l =>
    `<div class="lin-node">
      <span class="lin-src">${l.src.split('.')[1]}</span>
      <span class="lin-arr">→</span>
      <span class="lin-tgt">${l.tgt.split('.')[1]}</span>
      ${l.loop ? '<span class="lin-loop">⚠ LOOP</span>' : ''}
    </div>`
  ).join('');
}

// ── Daily ──────────────────────────────────────────────────────────────────
function renderDaily() {
  document.getElementById('dailyContainer').innerHTML = DAILY.map(d => `
    <div class="daily-card">
      <div class="daily-name">@${d.name}</div>
      ${d.did.map(a => `<div class="daily-act"><span class="daily-icon">✅</span><span>${a}</span></div>`).join('')}
      ${d.couldnt.map(a => `<div class="daily-act"><span class="daily-icon">❌</span><span>${a}</span></div>`).join('')}
      ${d.next.map(a => `<div class="daily-act"><span class="daily-icon">🔜</span><span>${a}</span></div>`).join('')}
    </div>
  `).join('');
}

// ── Stats ──────────────────────────────────────────────────────────────────
function renderStats() {
  const n     = COLUMNS.length;
  const high  = COLUMNS.filter(c => c.risk_score >= 60).length;
  const mid   = COLUMNS.filter(c => c.risk_score >= 30 && c.risk_score < 60).length;
  const low   = COLUMNS.filter(c => c.risk_score < 30).length;
  const avgC  = Math.round(COLUMNS.reduce((a,c) => a+c.clarity, 0) / n);

  document.getElementById('stat-high').textContent    = high;
  document.getElementById('stat-mid').textContent     = mid;
  document.getElementById('stat-low').textContent     = low;
  document.getElementById('stat-avg-clarity').textContent = avgC;
  document.getElementById('col-count-badge').textContent  = `${n} kolon`;

  const hp = (high/n*100).toFixed(1), mp = (mid/n*100).toFixed(1), lp = (low/n*100).toFixed(1);
  document.getElementById('stat-high-pct').textContent = `%${hp} kolon`;
  document.getElementById('stat-mid-pct').textContent  = `%${mp} kolon`;
  document.getElementById('stat-low-pct').textContent  = `%${lp} kolon`;

  document.getElementById('rb-high').style.width = hp + '%';
  document.getElementById('rb-mid').style.width  = mp + '%';
  document.getElementById('rb-low').style.width  = lp + '%';

  document.getElementById('rl-high-label').textContent = `Yüksek — ${high} kolon (%${hp})`;
  document.getElementById('rl-mid-label').textContent  = `Orta — ${mid} kolon (%${mp})`;
  document.getElementById('rl-low-label').textContent  = `Düşük — ${low} kolon (%${lp})`;
}

// ── Terminal log ───────────────────────────────────────────────────────────
function renderTerminal() {
  const el = document.getElementById('termLog');
  let html = '';

  const sep = `<div class="tl-sep">═══════════════════════════════════════════════</div>`;
  const dsep = `<div class="tl-sep">───────────────────────────────────────────────</div>`;

  html += sep;
  html += `<div class="tl-info">🚀 METADATA INTELLIGENCE PLATFORM — Pipeline v2.0</div>`;
  html += sep;

  const tables = [...new Set(COLUMNS.map(c => c.table))];

  tables.forEach(tbl => {
    const cols = COLUMNS.filter(c => c.table === tbl);
    const tblCol = cols[0];
    html += `\n<div class="tl-table">📋 TABLO: ${tbl}</div>`;

    const docs = [];
    if (tblCol.has_frd) docs.push('<span class="tl-ok">FRD ✅</span>'); else docs.push('<span class="tl-err">FRD ❌</span>');
    if (tblCol.has_toa) docs.push('<span class="tl-ok">TOA ✅</span>'); else docs.push('<span class="tl-err">TOA ❌</span>');
    if (tblCol.has_ddl) docs.push('<span class="tl-ok">DDL ✅</span>'); else docs.push('<span class="tl-err">DDL ❌</span>');
    html += `<div>   Dokümanlar: ${docs.join(' | ')}</div>`;
    html += dsep;

    cols.forEach(col => {
      const rb = riskBand(col.risk_score);
      const icon = col.risk_score >= 60 ? '🔴' : col.risk_score >= 30 ? '🟡' : '🟢';
      html += `<div class="tl-col">   ${icon} ${col.col.padEnd(36)} risk=${col.risk_score}/100  clarity=${col.clarity}/100  [${rb.label}]</div>`;
      if (col.quality !== 'complete' && col.quality !== 'generated') {
        html += `<div class="tl-warn">        ✏️ Üretildi [${col.quality}]</div>`;
      }
      col.deductions.forEach(([r,p]) => {
        html += `<div class="tl-ded">        ↳ -${p}pt  ${r}</div>`;
      });
      col.bonuses.forEach(([r,p]) => {
        html += `<div class="tl-bon">        ↳ +${p}pt  ${r}</div>`;
      });
      col.issues.forEach(iss => {
        html += `<div class="tl-warn">        ⚠ ${iss}</div>`;
      });
    });

    const avgR = Math.round(cols.reduce((a,c) => a+c.risk_score, 0) / cols.length);
    const avgC = Math.round(cols.reduce((a,c) => a+c.clarity, 0) / cols.length);
    html += `<div class="tl-info">   📊 Tablo özeti — avg risk: ${avgR}/100 | avg clarity: ${avgC}/100</div>\n`;
  });

  const n = COLUMNS.length;
  const high = COLUMNS.filter(c => c.risk_score >= 60).length;
  const mid  = COLUMNS.filter(c => c.risk_score >= 30 && c.risk_score < 60).length;
  const low  = n - high - mid;

  html += sep;
  html += `<div class="tl-info">  GENEL ÖZET</div>`;
  html += `<div>  Toplam kolon: ${n}</div>`;
  html += `<div class="tl-err">  🔴 Yüksek risk (≥60): ${high} kolon (%${(high/n*100).toFixed(1)})</div>`;
  html += `<div class="tl-warn">  🟡 Orta risk  (30-59): ${mid} kolon (%${(mid/n*100).toFixed(1)})</div>`;
  html += `<div class="tl-ok">  🟢 Düşük risk (&lt;30): ${low} kolon (%${(low/n*100).toFixed(1)})</div>`;
  html += `<div class="tl-warn">  ⚠ Lineage döngüsü: RISK ↔ CRM (ETL_003 + ETL_004)</div>`;
  html += sep;

  el.innerHTML = html;
}

// ── Popup ──────────────────────────────────────────────────────────────────
function showPopup(table, colName) {
  const col = COLUMNS.find(c => c.table === table && c.col === colName);
  if (!col) return;

  const rb = riskBand(col.risk_score);
  const rc = scoreColor(col.risk_score);
  const cc = clarityColor(col.clarity);

  document.getElementById('pp-colname').textContent  = col.col;
  document.getElementById('pp-tblname').textContent  = col.table;

  // Skor
  const sbig = document.getElementById('pp-score-big');
  sbig.textContent = col.risk_score;
  sbig.style.color = rc;

  // Doc availability
  const docPills = [
    col.has_frd ? `<span class="doc-pill dp-ok">FRD ✅</span>` : `<span class="doc-pill dp-miss">FRD ❌</span>`,
    col.has_toa ? `<span class="doc-pill dp-ok">TOA ✅</span>` : `<span class="doc-pill dp-miss">TOA ❌</span>`,
    col.has_ddl ? `<span class="doc-pill dp-ok">DDL ✅</span>` : `<span class="doc-pill dp-miss">DDL ❌</span>`,
  ].join('');
  document.getElementById('pp-doc-avail').innerHTML = `<div class="doc-avail">${docPills}</div>`;

  // Before / After
  const before = document.getElementById('pp-before');
  const after  = document.getElementById('pp-after');

  if (col.original_desc) {
    before.innerHTML = `<div class="compare-text">${col.original_desc}</div>`;
  } else {
    before.innerHTML = `<div class="compare-missing">(Açıklama yoktu)</div>`;
  }
  after.innerHTML = col.desc
    ? `<div class="compare-text">${col.desc}</div>`
    : `<div class="compare-missing">(Açıklama üretilemedi)</div>`;

  // Score breakdown
  const bd = col.breakdown;
  const bdHtml = [
    ['Domain Bağlamı', bd.domain, 25],
    ['Değer Aralığı / LKP', bd.value_range, 20],
    ['Referans Bütünlüğü', bd.reference, 15],
    ['İş Kuralı', bd.business_rule, 20],
    ['Dil Tutarlılığı', bd.language, 10],
    ['Yeterli Detay', bd.detail, 10],
  ].map(([label, val, max]) => {
    const pct = Math.round(val / max * 100);
    const c = pct >= 75 ? 'var(--low)' : pct >= 40 ? 'var(--mid)' : 'var(--high)';
    return `<div class="sb-item">
      <div class="sb-label">${label}</div>
      <div class="sb-val" style="color:${c}">${val}<span style="color:var(--muted);font-size:.6rem">/${max}</span></div>
    </div>`;
  }).join('');
  document.getElementById('pp-breakdown').innerHTML = bdHtml;

  // Factors
  const factors = document.getElementById('pp-factors');
  const fSection = document.getElementById('pp-factors-section');
  const allFactors = [
    ...col.deductions.map(([r,p]) => `<div class="pf-item"><span class="pf-label">${r}</span><span class="pf-pts-ded">-${p}pt</span></div>`),
    ...col.bonuses.map(([r,p]) => `<div class="pf-item"><span class="pf-label">${r}</span><span class="pf-pts-bon">+${p}pt</span></div>`),
  ];
  if (allFactors.length) {
    factors.innerHTML = allFactors.join('');
    fSection.style.display = 'block';
  } else {
    fSection.style.display = 'none';
  }

  // Issues
  const issSection = document.getElementById('pp-issues-section');
  const issEl = document.getElementById('pp-issues');
  if (col.issues.length) {
    issEl.innerHTML = col.issues.map(i => `<div class="pi-item"><span class="pi-icon">⚠</span><span>${i}</span></div>`).join('');
    issSection.style.display = 'block';
  } else {
    issSection.style.display = 'none';
  }

  // Feedback
  const fbSection = document.getElementById('pp-feedback-section');
  const fbEl = document.getElementById('pp-feedback');
  if (col.feedback) {
    fbEl.textContent = col.feedback;
    fbSection.style.display = 'block';
  } else {
    fbSection.style.display = 'none';
  }

  document.getElementById('popup').classList.add('active');
}

function closePopup(e) {
  if (!e || e.target === document.getElementById('popup') || e.currentTarget.classList.contains('popup-close')) {
    document.getElementById('popup').classList.remove('active');
  }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.getElementById('popup').classList.remove('active');
});

// ── Init ───────────────────────────────────────────────────────────────────
renderStats();
renderTable();
renderLineage();
renderDaily();
renderTerminal();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

if __name__ == "__main__":
    load_existing_results()
    print("\n🚀 Metadata Intelligence Platform v2.0")
    print("   Open: http://localhost:5000\n")
    app.run(debug=True, port=5000)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Metadata Intelligence Platform v2.0</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#F0F4F8;--surface:#fff;--surface2:#F8FAFC;--surface3:#EFF2F7;
  --border:#E2E8F0;--border2:#CBD5E1;
  --blue:#2563EB;--blue-l:#EFF6FF;--blue-m:#BFDBFE;--blue-d:#1D4ED8;
  --red:#DC2626;--red-l:#FEF2F2;--red-m:#FECACA;
  --green:#059669;--green-l:#ECFDF5;--green-m:#A7F3D0;
  --amber:#D97706;--amber-l:#FFFBEB;--amber-m:#FDE68A;
  --orange:#EA580C;--orange-l:#FFF7ED;--orange-m:#FED7AA;
  --purple:#7C3AED;--purple-l:#F5F3FF;--purple-m:#DDD6FE;
  --teal:#0D9488;--teal-l:#F0FDFA;--teal-m:#99F6E4;
  --text:#0F172A;--text2:#1E293B;--text3:#475569;--text4:#94A3B8;
  --mono:'JetBrains Mono',monospace;--sans:'Inter',sans-serif;
  --r:10px;--rs:6px;--shadow:0 1px 3px rgba(0,0,0,.08);
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh;font-size:14px;line-height:1.5}
header{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.96);backdrop-filter:blur(12px);border-bottom:1px solid var(--border);height:54px;padding:0 28px;display:flex;align-items:center;justify-content:space-between;box-shadow:0 1px 0 var(--border)}
.brand{display:flex;align-items:center;gap:10px}
.brand-icon{width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,var(--blue),var(--purple));display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:11px;font-weight:700;color:#fff}
.brand-name{font-weight:700;font-size:14px;letter-spacing:-.02em}
.brand-ver{font-family:var(--mono);font-size:10px;color:var(--text4);background:var(--surface2);border:1px solid var(--border);padding:2px 7px;border-radius:4px}
.hdr-r{display:flex;align-items:center;gap:10px}
.status-chip{display:flex;align-items:center;gap:6px;font-family:var(--mono);font-size:11px;color:var(--text3);background:var(--surface2);border:1px solid var(--border);padding:5px 12px;border-radius:20px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--text4)}
.dot.running{background:var(--amber);animation:pulse 1.2s infinite}
.dot.done{background:var(--green)}.dot.error{background:var(--red)}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.85)}}
.run-btn{display:flex;align-items:center;gap:7px;background:var(--blue);color:#fff;font-size:13px;font-weight:600;padding:8px 18px;border-radius:var(--rs);border:none;cursor:pointer;transition:background .15s}
.run-btn:hover{background:var(--blue-d)}.run-btn:disabled{background:var(--border2);color:var(--text4);cursor:not-allowed}
.run-btn svg{width:13px;height:13px;fill:currentColor}
.page{max-width:1480px;margin:0 auto;padding:24px 28px}
#ps{display:none;margin-bottom:20px}#ps.v{display:block}
.pc{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:18px 20px;box-shadow:var(--shadow)}
.ph{display:flex;justify-content:space-between;margin-bottom:10px;align-items:center}
.pstep{font-family:var(--mono);font-size:12px;font-weight:600;color:var(--blue)}
.ppct{font-family:var(--mono);font-size:11px;color:var(--text3)}
.pt{height:5px;background:var(--border);border-radius:3px;overflow:hidden;margin-bottom:12px}
.pf{height:100%;background:linear-gradient(90deg,var(--blue),var(--purple));border-radius:3px;transition:width .5s;width:0%}
.lo{font-family:var(--mono);font-size:11.5px;color:var(--text3);max-height:100px;overflow-y:auto;line-height:2}
.lo .ok{color:var(--green)}.lo .err{color:var(--red)}.lo .inf{color:var(--blue)}.lo .warn{color:var(--amber)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin-bottom:20px}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:16px 18px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.stat::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
.sr::before{background:var(--red)}.sg::before{background:var(--green)}.sb::before{background:var(--blue)}
.sam::before{background:var(--amber)}.spu::before{background:var(--purple)}.stl::before{background:var(--teal)}
.sn{font-family:var(--mono);font-size:30px;font-weight:700;line-height:1.1;margin-bottom:4px}
.sl{font-size:11px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.06em}
.sd{font-family:var(--mono);font-size:10px;color:var(--text4);margin-top:3px}
.sr .sn{color:var(--red)}.sg .sn{color:var(--green)}.sb .sn{color:var(--blue)}
.sam .sn{color:var(--amber)}.spu .sn{color:var(--purple)}.stl .sn{color:var(--teal)}
.rdb-wrap{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:16px 20px;margin-bottom:20px;box-shadow:var(--shadow)}
.rdb-title{font-family:var(--mono);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--text3);margin-bottom:10px}
.rdb-track{display:flex;height:10px;border-radius:5px;overflow:hidden;gap:2px}
.rdb-high{background:var(--red);transition:width .8s}.rdb-mid{background:var(--amber);transition:width .8s}.rdb-low{background:var(--green);transition:width .8s}
.rdb-legend{display:flex;gap:20px;margin-top:10px;flex-wrap:wrap}
.rdl{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text3)}
.rdl-dot{width:8px;height:8px;border-radius:50%}
.grid{display:grid;grid-template-columns:1fr 310px;gap:16px;align-items:start}
@media(max-width:960px){.grid{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);overflow:hidden;margin-bottom:16px;box-shadow:var(--shadow)}
.ch{display:flex;align-items:center;justify-content:space-between;padding:11px 16px;border-bottom:1px solid var(--border);background:var(--surface2)}
.ct{font-size:11px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.08em}
.badge{display:inline-flex;align-items:center;gap:3px;font-family:var(--mono);font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;white-space:nowrap}
.bb{background:var(--blue-l);color:var(--blue);border:1px solid var(--blue-m)}
.br{background:var(--red-l);color:var(--red);border:1px solid var(--red-m)}
.bg{background:var(--green-l);color:var(--green);border:1px solid var(--green-m)}
.ba{background:var(--amber-l);color:var(--amber);border:1px solid var(--amber-m)}
.btl{background:var(--teal-l);color:var(--teal);border:1px solid var(--teal-m)}
.fb-bar{display:flex;gap:6px;padding:10px 16px;border-bottom:1px solid var(--border);flex-wrap:wrap}
.fb{font-size:12px;font-weight:500;padding:4px 14px;border-radius:20px;border:1px solid var(--border);background:transparent;color:var(--text3);cursor:pointer;transition:all .12s}
.fb:hover{background:var(--surface2)}.fa{background:var(--blue-l);color:var(--blue);border-color:var(--blue-m)}
.fhi{background:var(--red-l);color:var(--red);border-color:var(--red-m)}
.fmi{background:var(--amber-l);color:var(--amber);border-color:var(--amber-m)}
.flo{background:var(--green-l);color:var(--green);border-color:var(--green-m)}
.tw{overflow-x:auto}
table{width:100%;border-collapse:collapse}
th{font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;padding:9px 14px;text-align:left;border-bottom:2px solid var(--border);background:var(--surface2);white-space:nowrap}
td{padding:10px 14px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}tr:hover td{background:var(--surface2)}
tr.risk-high td:first-child{border-left:3px solid var(--red)}
tr.risk-mid  td:first-child{border-left:3px solid var(--amber)}
tr.risk-low  td:first-child{border-left:3px solid var(--green)}
.cn{font-family:var(--mono);font-size:12px;font-weight:600;color:var(--blue);cursor:pointer}
.cn:hover{text-decoration:underline}
.sbadge{font-family:var(--mono);font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;display:inline-block;margin-bottom:3px}
.sc-CORE_BANKING{background:#EFF6FF;color:#1D4ED8}.sc-CREDIT{background:#FEF2F2;color:#DC2626}
.sc-CRM{background:#F5F3FF;color:#6D28D9}.sc-RISK{background:#FFFBEB;color:#B45309}
.sc-OTHER{background:var(--surface2);color:var(--text3)}
.tn{font-size:11px;color:var(--text3);margin-top:1px}
.dt{color:var(--text2);max-width:280px;font-size:13px}.dm{color:var(--text4);font-style:italic;font-size:13px}
.rp{display:inline-flex;align-items:center;gap:5px;font-family:var(--mono);font-size:11px;font-weight:700;padding:3px 10px;border-radius:5px;cursor:pointer;transition:opacity .12s;white-space:nowrap}
.rp:hover{opacity:.75}
.rp-high{background:var(--red-l);color:var(--red);border:1px solid var(--red-m)}
.rp-mid{background:var(--amber-l);color:var(--amber);border:1px solid var(--amber-m)}
.rp-low{background:var(--green-l);color:var(--green);border:1px solid var(--green-m)}
.clb{display:flex;align-items:center;gap:7px}
.clbt{width:60px;height:5px;background:var(--border);border-radius:3px;overflow:hidden}
.clbf{height:100%;border-radius:3px;transition:width .6s}
.clbv{font-family:var(--mono);font-size:11px;min-width:26px}
.ic{display:inline-flex;align-items:center;gap:3px;background:var(--amber-l);color:var(--amber);border:1px solid var(--amber-m);font-family:var(--mono);font-size:10px;font-weight:600;padding:2px 8px;border-radius:4px;cursor:pointer}
.ic:hover{opacity:.75}
.li{display:flex;align-items:center;gap:6px;padding:9px 16px;border-bottom:1px solid var(--border);font-family:var(--mono);font-size:12px}
.li:last-child{border-bottom:none}
.ls{color:var(--blue);font-weight:600}.la{color:var(--text4)}.lt{color:var(--purple);font-weight:600}.ll{margin-left:auto}
.qr{display:flex;align-items:center;gap:8px;margin-bottom:9px}
.qd{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.ql{font-size:11px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.05em;flex:1}
.qb{width:70px;height:4px;background:var(--border);border-radius:2px;overflow:hidden}
.qf{height:100%;border-radius:2px}.qn{font-family:var(--mono);font-size:11px;min-width:20px;text-align:right;font-weight:600}
.term-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);overflow:hidden;margin-bottom:16px;box-shadow:var(--shadow)}
.term-hdr{display:flex;align-items:center;justify-content:space-between;padding:9px 16px;border-bottom:1px solid var(--border);background:#1E293B}
.term-title{font-family:var(--mono);font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;letter-spacing:.1em}
.term-body{background:#0F172A;padding:14px 16px;font-family:var(--mono);font-size:11.5px;line-height:1.9;max-height:260px;overflow-y:auto;color:#64748B}
.tl-info{color:#38BDF8}.tl-ok{color:#34D399}.tl-warn{color:#FBBF24}.tl-err{color:#F87171}
.tl-tbl{color:#C084FC;font-weight:600}.tl-sep{color:#1E293B}
.overlay{position:fixed;inset:0;background:rgba(15,23,42,.5);z-index:200;display:flex;align-items:center;justify-content:center;padding:20px;opacity:0;pointer-events:none;transition:opacity .15s;backdrop-filter:blur(4px)}
.overlay.open{opacity:1;pointer-events:all}
.popup{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:28px 30px;max-width:600px;width:100%;position:relative;box-shadow:0 24px 80px rgba(0,0,0,.18);max-height:90vh;overflow-y:auto;transform:translateY(8px);transition:transform .15s}
.overlay.open .popup{transform:translateY(0)}
.px{position:absolute;top:14px;right:16px;background:var(--surface2);border:1px solid var(--border);border-radius:7px;width:30px;height:30px;display:flex;align-items:center;justify-content:center;color:var(--text3);cursor:pointer;font-size:14px}
.px:hover{background:var(--border)}
.pp-hdr{display:flex;align-items:flex-start;gap:14px;margin-bottom:18px}
.pp-meta{flex:1}
.pp-col{font-family:var(--mono);font-size:15px;font-weight:700}
.pp-tbl{font-size:12px;color:var(--text3);margin-top:3px}
.pp-score{font-family:var(--mono);font-size:28px;font-weight:700;line-height:1}
.pp-score-sub{font-family:var(--mono);font-size:10px;color:var(--text4);margin-top:2px}
.pp-sec{font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.08em;margin:16px 0 8px;border-top:1px solid var(--border);padding-top:14px}
.compare-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.compare-box{border-radius:8px;padding:12px 14px}
.cb-before{background:var(--red-l);border:1px solid var(--red-m)}
.cb-after{background:var(--green-l);border:1px solid var(--green-m)}
.cb-label{font-family:var(--mono);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}
.cb-before .cb-label{color:var(--red)}.cb-after .cb-label{color:var(--green)}
.cb-text{font-size:13px;line-height:1.55;color:var(--text2)}
.cb-null{font-family:var(--mono);font-size:12px;color:var(--text4);font-style:italic}
.dp-pills{display:flex;gap:4px;flex-wrap:wrap;margin-top:8px}
.dp{font-family:var(--mono);font-size:10px;font-weight:600;padding:1px 6px;border-radius:3px}
.dp-ok{background:var(--green-l);color:var(--green);border:1px solid var(--green-m)}
.dp-no{background:var(--red-l);color:var(--red);border:1px solid var(--red-m)}
.pp-breakdown{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pbd{background:var(--surface2);border-radius:6px;padding:8px 10px}
.pbd-label{font-family:var(--mono);font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:.05em}
.pbd-val{font-family:var(--mono);font-size:16px;font-weight:700;margin-top:2px}
.pp-factors{display:flex;flex-direction:column;gap:5px}
.pf-item{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;font-size:12.5px;line-height:1.45}
.pf-lbl{color:var(--text2);flex:1}
.pf-ded{font-family:var(--mono);font-size:11px;color:var(--red);white-space:nowrap;font-weight:600}
.pf-bon{font-family:var(--mono);font-size:11px;color:var(--green);white-space:nowrap;font-weight:600}
.pp-issues{display:flex;flex-direction:column;gap:5px}
.pp-issue{display:flex;gap:8px;font-size:12.5px;line-height:1.5;background:var(--amber-l);border:1px solid var(--amber-m);padding:7px 10px;border-radius:6px}
.pp-feedback{font-size:13px;line-height:1.6;color:var(--text2);background:var(--surface2);padding:12px 14px;border-radius:8px;border-left:3px solid var(--blue)}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="brand-icon">MIP</div>
    <span class="brand-name">Metadata Intelligence Platform</span>
    <span class="brand-ver">v2.0</span>
  </div>
  <div class="hdr-r">
    <div class="status-chip"><div class="dot" id="dot"></div><span id="slbl">Idle</span></div>
    <button class="run-btn" id="runBtn" onclick="runPipeline()">
      <svg viewBox="0 0 16 16"><path d="M3 2.5l10 5.5-10 5.5V2.5z"/></svg>Run Pipeline
    </button>
  </div>
</header>
<div class="page">
  <div id="ps">
    <div class="pc">
      <div class="ph"><span class="pstep" id="pStep">Initializing…</span><span class="ppct" id="pPct">0%</span></div>
      <div class="pt"><div class="pf" id="pFill"></div></div>
      <div class="lo" id="logOut"></div>
    </div>
  </div>
  <div class="stats">
    <div class="stat sr"><div class="sn" id="sHi">—</div><div class="sl">High Risk</div><div class="sd" id="sHiP">—</div></div>
    <div class="stat sam"><div class="sn" id="sMid">—</div><div class="sl">Mid Risk</div><div class="sd" id="sMidP">—</div></div>
    <div class="stat sg"><div class="sn" id="sLo">—</div><div class="sl">Low Risk</div><div class="sd" id="sLoP">—</div></div>
    <div class="stat sb"><div class="sn" id="sAvgC">—</div><div class="sl">Avg Clarity</div><div class="sd">threshold: 80</div></div>
    <div class="stat spu"><div class="sn" id="sT">—</div><div class="sl">Tables</div><div class="sd" id="sCols">—</div></div>
    <div class="stat stl"><div class="sn" id="sLp">0</div><div class="sl">ETL Loops</div><div class="sd" id="sLpD">—</div></div>
  </div>
  <div class="rdb-wrap">
    <div class="rdb-title">// Risk Score Distribution — 0–100 Continuous Scale</div>
    <div class="rdb-track">
      <div class="rdb-high" id="rdbH" style="width:0%"></div>
      <div class="rdb-mid" id="rdbM" style="width:0%"></div>
      <div class="rdb-low" id="rdbL" style="width:0%"></div>
    </div>
    <div class="rdb-legend">
      <div class="rdl"><div class="rdl-dot" style="background:var(--red)"></div><span id="rdbHlbl">High (≥60) —</span></div>
      <div class="rdl"><div class="rdl-dot" style="background:var(--amber)"></div><span id="rdbMlbl">Mid (30–59) —</span></div>
      <div class="rdl"><div class="rdl-dot" style="background:var(--green)"></div><span id="rdbLlbl">Low (&lt;30) —</span></div>
    </div>
  </div>
  <div class="grid">
    <div>
      <div class="card">
        <div class="ch"><span class="ct">Column Risk Matrix</span><span class="badge bb" id="colCt">—</span></div>
        <div class="fb-bar">
          <button class="fb fa" onclick="flt('all',this)">All</button>
          <button class="fb" onclick="flt('high',this)">🔴 High Risk</button>
          <button class="fb" onclick="flt('mid',this)">🟡 Mid Risk</button>
          <button class="fb" onclick="flt('low',this)">🟢 Low Risk</button>
        </div>
        <div class="tw">
          <table>
            <thead><tr><th>Table</th><th>Column</th><th>Description</th><th>Risk Score</th><th>Clarity</th><th>Issues</th></tr></thead>
            <tbody id="tbody"></tbody>
          </table>
        </div>
      </div>
      <div class="term-card">
        <div class="term-hdr"><span class="term-title">// Pipeline Terminal Output</span><span class="badge bb" id="termBadge">—</span></div>
        <div class="term-body" id="termLog"><span style="color:#334155">Waiting for pipeline run…</span></div>
      </div>
    </div>
    <div>
      <div class="card">
        <div class="ch"><span class="ct">ETL Lineage</span><span class="badge" id="loopB">—</span></div>
        <div id="linList"></div>
      </div>
      <div class="card">
        <div class="ch"><span class="ct">Description Quality</span></div>
        <div id="qualDiv" style="padding:16px"></div>
      </div>
    </div>
  </div>
</div>

<div class="overlay" id="overlay" onclick="closePopup(event)">
  <div class="popup">
    <div class="px" onclick="closePopup()">✕</div>
    <div class="pp-hdr">
      <div class="pp-meta">
        <div class="pp-col" id="ppCol"></div>
        <div class="pp-tbl" id="ppTbl"></div>
        <div class="dp-pills" id="ppDocs"></div>
      </div>
      <div><div class="pp-score" id="ppScore"></div><div class="pp-score-sub">risk score /100</div></div>
    </div>
    <div class="pp-sec">Description — Before → After</div>
    <div class="compare-grid">
      <div class="compare-box cb-before"><div class="cb-label">◀ Original</div><div id="ppBefore"></div></div>
      <div class="compare-box cb-after"><div class="cb-label">▶ Generated</div><div id="ppAfter"></div></div>
    </div>
    <div class="pp-sec" id="ppBdSec">Clarity Score Breakdown</div>
    <div class="pp-breakdown" id="ppBreakdown"></div>
    <div id="ppFactSec"><div class="pp-sec">Score Factors</div><div class="pp-factors" id="ppFactors"></div></div>
    <div id="ppIssSec"><div class="pp-sec">Issues Detected</div><div class="pp-issues" id="ppIssues"></div></div>
    <div id="ppFbkSec"><div class="pp-sec">Critic Feedback</div><div class="pp-feedback" id="ppFeedback"></div></div>
  </div>
</div>

<script>
let COLS=[],cf='all';
async function init(){await loadR();await loadL();poll();}
async function runPipeline(){
  document.getElementById('runBtn').disabled=true;
  document.getElementById('ps').classList.add('v');
  document.getElementById('termLog').innerHTML='<span class="tl-info">// Pipeline starting…</span>';
  await fetch('/api/run',{method:'POST'}).catch(()=>{});
}
function poll(){setInterval(async()=>{const d=await fetch('/api/status').then(r=>r.json()).catch(()=>null);if(!d)return;updateSt(d);if(d.status==='done'){await loadR();await loadL();}},1500);}
function updateSt(d){
  document.getElementById('dot').className='dot '+d.status;
  document.getElementById('slbl').textContent=d.status[0].toUpperCase()+d.status.slice(1);
  const btn=document.getElementById('runBtn');
  if(d.status==='running'){
    btn.disabled=true;
    document.getElementById('pStep').textContent=d.step;
    document.getElementById('pPct').textContent=d.progress+'%';
    document.getElementById('pFill').style.width=d.progress+'%';
    const lo=document.getElementById('logOut');
    lo.innerHTML=(d.log||[]).map(l=>{const c=l.startsWith('✅')||l.startsWith('🎉')?'ok':l.startsWith('❌')?'err':l.startsWith('⚠')||l.startsWith('🔄')?'warn':'inf';return`<div class="${c}">${l}</div>`;}).join('');
    lo.scrollTop=lo.scrollHeight;
  }
  if(['done','idle'].includes(d.status))btn.disabled=false;
}
async function loadR(){const d=await fetch('/api/results').then(r=>r.ok?r.json():null).catch(()=>null);if(d)renderAll(d);}
function renderAll(data){
  const tables=data.tables||[];COLS=[];

  tables.forEach(t=>{
    (t.columns||[]).forEach(col=>{
      // ── risk_score: backend always injects it now, JS fallback is safety net ──
      let rs = (col.risk_score !== null && col.risk_score !== undefined)
        ? Number(col.risk_score)
        : (() => {
            const q = col.description_quality||'';
            let s = q==='missing'?80:q==='wrong'?72:q==='english'?60:q==='vague'?45:q==='incomplete'?28:12;
            if(col.validation_issue) s=Math.max(s,65);
            if(col.distinct_count && col.distinct_count<100 && !col.has_lookup) s=Math.max(s,55);
            return Math.min(100,s);
          })();

      const band = rs>=60?'high':rs>=30?'mid':'low';

      // ── clarity_score ─────────────────────────────────────────────────────
      let cl = (col.clarity_score !== null && col.clarity_score !== undefined)
        ? Number(col.clarity_score)
        : hCl(col);

      // ── issues: backend injects, deduplicate here ─────────────────────────
      const issSet = new Set(col.issues||[]);
      if(col.validation_issue) issSet.add('VALUE MISMATCH: '+col.validation_issue);
      if(col.distinct_count&&col.distinct_count<100&&!col.has_lookup)
        issSet.add(`LOOKUP GAP: ${col.distinct_count} distinct values, no LKP table`);
      const issues=[...issSet];

      // ── original_description: what it looked like before enrichment ───────
      const origDesc = col.original_description !== undefined
        ? col.original_description
        : null; // null = never enriched; show "(pipeline not run yet)"

      COLS.push({
        table:t.table_name, schema:t.schema||'', col:col.column_name,
        desc:col.description||'', origDesc, quality:col.description_quality||'',
        rs, band, cl, issues, feedback:col.feedback||'',
        hasFrd:t.has_functional_doc||false, hasToa:t.has_toa_doc||false, hasDdl:t.has_ddl||false,
        deductions:col.clarity_deductions||[], bonuses:col.clarity_bonuses||[],
        breakdown:col.clarity_breakdown||null,
      });
    });
  });

  const n=COLS.length;
  if(!n) return;

  const hi=COLS.filter(c=>c.band==='high').length;
  const mi=COLS.filter(c=>c.band==='mid').length;
  const lo=COLS.filter(c=>c.band==='low').length;
  const avgC=Math.round(COLS.reduce((s,c)=>s+c.cl,0)/n);

  // Stats cards
  set('sHi',  hi);  set('sHiP',  `${(hi/n*100).toFixed(0)}% of cols`);
  set('sMid', mi);  set('sMidP', `${(mi/n*100).toFixed(0)}% of cols`);
  set('sLo',  lo);  set('sLoP',  `${(lo/n*100).toFixed(0)}% of cols`);
  set('sAvgC',avgC); set('sT',tables.length); set('sCols',`${n} columns`); set('colCt',`${n} columns`);

  // Risk distribution bar — always computed from COLS (not from summary, which may lag)
  const hp=(hi/n*100).toFixed(1), mp=(mi/n*100).toFixed(1), lp=(lo/n*100).toFixed(1);
  document.getElementById('rdbH').style.width=hp+'%';
  document.getElementById('rdbM').style.width=mp+'%';
  document.getElementById('rdbL').style.width=lp+'%';
  set('rdbHlbl',`High (≥60): ${hi} cols (${hp}%)`);
  set('rdbMlbl',`Mid (30–59): ${mi} cols (${mp}%)`);
  set('rdbLlbl',`Low (<30): ${lo} cols (${lp}%)`);

  // Override stats with backend summary if available (more precise)
  const rsum=(data.risk_report||{}).summary||{};
  if(rsum.yuksek_risk_count!==undefined){
    set('sHi',  rsum.yuksek_risk_count);  set('sHiP',  `${rsum.yuksek_risk_pct}% of cols`);
    set('sMid', rsum.orta_risk_count);    set('sMidP', `${rsum.orta_risk_pct}% of cols`);
    set('sLo',  rsum.dusuk_risk_count);   set('sLoP',  `${rsum.dusuk_risk_pct}% of cols`);
    const rH=rsum.yuksek_risk_pct, rM=rsum.orta_risk_pct, rL=rsum.dusuk_risk_pct;
    document.getElementById('rdbH').style.width=rH+'%';
    document.getElementById('rdbM').style.width=rM+'%';
    document.getElementById('rdbL').style.width=rL+'%';
    set('rdbHlbl',`High (≥60): ${rsum.yuksek_risk_count} cols (${rH}%)`);
    set('rdbMlbl',`Mid (30–59): ${rsum.orta_risk_count} cols (${rM}%)`);
    set('rdbLlbl',`Low (<30): ${rsum.dusuk_risk_count} cols (${rL}%)`);
  }

  buildTerm(data,tables);renderTable(cf);renderQ();
}
function buildTerm(data,tables){
  const TH=(data.config||{}).clarity_threshold||80;
  const lines=[`═══════════════════════════════════════════════════════`,`  MIP v2.0 — Clarity threshold: ${TH}/100 | Risk bands: ≥60 High · 30-59 Mid · <30 Low`,`═══════════════════════════════════════════════════════`];
  tables.forEach(t=>{
    const tKey=`${t.schema}.${t.table_name}`;
    const docs=[t.has_functional_doc?'FRD ✅':'FRD ❌',t.has_toa_doc?'TOA ✅':'TOA ❌',t.has_ddl?'DDL ✅':'DDL ❌'].join(' | ');
    lines.push(`📋 ${tKey}`);lines.push(`   Docs: ${docs}`);lines.push(`   ─────────────────────────────────────`);
    (t.columns||[]).forEach(col=>{
      const rs=col.risk_score!==undefined?col.risk_score:'?';const cl=col.clarity_score!==undefined?col.clarity_score:'?';
      const band=rs>=60?'🔴 HIGH':rs>=30?'🟡 MID':'🟢 LOW';
      const verdict=cl>=TH?'✅ OK':cl>=50?'⚠ AT_RISK':'🔴 FAIL';
      lines.push(`   ${String(band).padEnd(9)} ${col.column_name.padEnd(33)} risk=${String(rs).padStart(3)}/100  clarity=${String(cl).padStart(3)}/100  [${verdict}]`);
      if(col.validation_issue)lines.push(`        ⚠ ${col.validation_issue}`);
      (col.issues||[]).forEach(i=>lines.push(`        ⚠ ${i}`));
    });
    const cols2=t.columns||[];
    const ar=cols2.length?Math.round(cols2.reduce((s,c)=>s+(c.risk_score||0),0)/cols2.length):0;
    const ac=cols2.length?Math.round(cols2.reduce((s,c)=>s+(c.clarity_score||0),0)/cols2.length):0;
    lines.push(`   📊 avg risk: ${ar}/100 | avg clarity: ${ac}/100\n`);
  });
  const rp=(data.risk_report||{}).summary||{};
  lines.push(`═══════════════════════════════════════════════════════`,`  OVERALL SUMMARY`);
  if(rp.total_columns){lines.push(`  Avg risk score : ${rp.avg_risk_score}/100`);lines.push(`  🔴 High: ${rp.yuksek_risk_count} cols (%${rp.yuksek_risk_pct})  🟡 Mid: ${rp.orta_risk_count} cols (%${rp.orta_risk_pct})  🟢 Low: ${rp.dusuk_risk_count} cols (%${rp.dusuk_risk_pct})`);}
  (data.lineage_loops||[]).forEach(lp=>lines.push(`  ⚠ LOOP: ${lp}`));
  lines.push(`═══════════════════════════════════════════════════════`);
  set('termBadge',lines.length+' lines');
  document.getElementById('termLog').innerHTML=lines.map(l=>{
    const c=l.includes('✅')||l.includes('📊')?'tl-ok':l.includes('❌')||l.includes('🔴')?'tl-err':l.includes('⚠')||l.includes('🟡')||l.includes('🔄')?'tl-warn':l.startsWith('📋')?'tl-tbl':l.startsWith('═')||l.includes('─────')?'tl-sep':'tl-info';
    return`<div class="${c}">${l.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>`;
  }).join('');
}
function renderTable(filter){
  cf=filter;
  const rows=filter==='all'?COLS:filter==='high'?COLS.filter(c=>c.band==='high'):filter==='mid'?COLS.filter(c=>c.band==='mid'):COLS.filter(c=>c.band==='low');
  if(!rows.length){document.getElementById('tbody').innerHTML=`<tr><td colspan="6"><div style="padding:48px 24px;text-align:center"><div style="font-size:28px;margin-bottom:10px">📋</div><div style="font-size:13px;font-weight:600;color:var(--text3)">No data — run the pipeline</div></div></td></tr>`;return;}
  document.getElementById('tbody').innerHTML=rows.map(col=>{
    const rc=col.band==='high'?'rp-high':col.band==='mid'?'rp-mid':'rp-low';
    const rl=col.band==='high'?'🔴':col.band==='mid'?'🟡':'🟢';
    const cc=col.cl>=80?'var(--green)':col.cl>=50?'var(--amber)':'var(--red)';
    const dh=col.desc?`<span class="dt">${col.desc.length>65?col.desc.slice(0,65)+'…':col.desc}</span>`:`<span class="dm">— missing —</span>`;
    const ih=col.issues.length?`<span class="ic" onclick="showPopup('${col.table}','${col.col}')">⚠ ${col.issues.length}</span>`:`<span style="color:var(--text4);font-size:11px">—</span>`;
    return`<tr class="risk-${col.band}"><td><div class="sbadge sc-${col.schema||'OTHER'}">${col.schema||'—'}</div><div class="tn">${col.table}</div></td><td><span class="cn" onclick="showPopup('${col.table}','${col.col}')">${col.col}</span></td><td>${dh}</td><td><span class="rp ${rc}" onclick="showPopup('${col.table}','${col.col}')">${rl} ${col.rs}/100</span></td><td><div class="clb"><div class="clbt"><div class="clbf" style="width:${col.cl}%;background:${cc}"></div></div><span class="clbv" style="color:${cc}">${col.cl}</span></div></td><td>${ih}</td></tr>`;
  }).join('');
}
function flt(f,btn){document.querySelectorAll('.fb').forEach(b=>b.className='fb');const m={all:'fa',high:'fhi',mid:'fmi',low:'flo'};btn.classList.add(m[f]);renderTable(f);}
function renderQ(){
  const t={complete:0,generated:0,incomplete:0,english:0,missing:0,wrong:0,vague:0};
  COLS.forEach(c=>{if(t[c.quality]!==undefined)t[c.quality]++;});
  const cl={complete:'#059669',generated:'#2563EB',incomplete:'#D97706',english:'#7C3AED',missing:'#DC2626',wrong:'#DC2626',vague:'#EA580C'};
  const tot=COLS.length||1;
  document.getElementById('qualDiv').innerHTML=Object.entries(t).filter(([,v])=>v>0).map(([k,v])=>{const c=cl[k]||'#94A3B8',p=Math.round(v/tot*100);return`<div class="qr"><div class="qd" style="background:${c}"></div><span class="ql">${k}</span><div class="qb"><div class="qf" style="width:${p}%;background:${c}"></div></div><span class="qn" style="color:${c}">${v}</span></div>`;}).join('')||`<div style="color:var(--text4);font-size:12px;padding:4px 0">No data yet</div>`;
}
async function loadL(){
  const d=await fetch('/api/lineage').then(r=>r.ok?r.json():null).catch(()=>null);if(!d)return;
  const jobs=d.etl_lineage||[],loops=jobs.filter(j=>j.loop_risk).length;
  const lb=document.getElementById('loopB');lb.textContent=loops>0?`⚠ ${loops} Loop`:'✓ Clean';lb.className='badge '+(loops>0?'br':'bg');
  set('sLp',loops);set('sLpD',loops>0?'CRM ↔ RISK detected':'no loops');
  document.getElementById('linList').innerHTML=jobs.map(j=>`<div class="li"><span class="ls">${j.source.table}</span><span class="la">→</span><span class="lt">${j.target.table}</span>${j.loop_risk?`<span class="ll"><span class="badge br">LOOP</span></span>`:''}</div>`).join('');
}
function showPopup(table,colName){
  const col=COLS.find(c=>c.table===table&&c.col===colName);if(!col)return;
  const sc=col.rs>=60?'var(--red)':col.rs>=30?'var(--amber)':'var(--green)';
  set('ppCol',col.col);set('ppTbl',`${col.schema}.${col.table}`);
  document.getElementById('ppScore').innerHTML=`<span style="color:${sc}">${col.rs}</span>`;
  document.getElementById('ppDocs').innerHTML=[col.hasFrd?`<span class="dp dp-ok">FRD ✅</span>`:`<span class="dp dp-no">FRD ❌</span>`,col.hasToa?`<span class="dp dp-ok">TOA ✅</span>`:`<span class="dp dp-no">TOA ❌</span>`,col.hasDdl?`<span class="dp dp-ok">DDL ✅</span>`:`<span class="dp dp-no">DDL ❌</span>`].join('');
  document.getElementById('ppBefore').innerHTML = col.origDesc !== null
    ? (col.origDesc
        ? `<span class="cb-text">${col.origDesc}</span>`
        : `<span class="cb-null">(açıklama yoktu — null)</span>`)
    : `<span class="cb-null">(pipeline henüz çalıştırılmadı — mevcut açıklama orijinaldir)</span>`;
  document.getElementById('ppAfter').innerHTML = col.desc
    ? `<span class="cb-text">${col.desc}</span>`
    : `<span class="cb-null">(açıklama üretilemedi)</span>`;
  const bd=col.breakdown,bdSec=document.getElementById('ppBdSec'),bdEl=document.getElementById('ppBreakdown');
  if(bd){const items=[{label:'Domain Context',val:bd.domain_context_score,max:25},{label:'Value Range/LKP',val:bd.value_range_score,max:20},{label:'Ref. Integrity',val:bd.reference_integrity_score,max:15},{label:'Business Rule',val:bd.business_rule_score,max:20},{label:'Language',val:bd.language_score,max:10},{label:'Detail',val:bd.detail_score,max:10}].filter(b=>b.val!==undefined);bdEl.innerHTML=items.map(b=>{const p=b.max?Math.round((b.val||0)/b.max*100):0;const c=p>=75?'var(--green)':p>=40?'var(--amber)':'var(--red)';return`<div class="pbd"><div class="pbd-label">${b.label}</div><div class="pbd-val" style="color:${c}">${b.val||0}<span style="color:var(--text4);font-size:11px">/${b.max}</span></div></div>`;}).join('');bdSec.style.display=items.length?'block':'none';}else{bdSec.style.display='none';bdEl.innerHTML='';}
  const allF=[...(col.deductions||[]).map(([r,p])=>`<div class="pf-item"><span class="pf-lbl">${r}</span><span class="pf-ded">−${p}pt</span></div>`),...(col.bonuses||[]).map(([r,p])=>`<div class="pf-item"><span class="pf-lbl">${r}</span><span class="pf-bon">+${p}pt</span></div>`)];
  document.getElementById('ppFactors').innerHTML=allF.join('');document.getElementById('ppFactSec').style.display=allF.length?'block':'none';
  const issEl=document.getElementById('ppIssues');issEl.innerHTML=col.issues.map(i=>`<div class="pp-issue"><span>⚠</span><span>${i}</span></div>`).join('');document.getElementById('ppIssSec').style.display=col.issues.length?'block':'none';
  const fbkEl=document.getElementById('ppFeedback');fbkEl.textContent=col.feedback;document.getElementById('ppFbkSec').style.display=col.feedback?'block':'none';
  document.getElementById('overlay').classList.add('open');
}
function closePopup(e){if(!e||e.target===document.getElementById('overlay')||e.currentTarget.classList.contains('px'))document.getElementById('overlay').classList.remove('open');}
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('overlay').classList.remove('open');});
function set(id,v){const el=document.getElementById(id);if(el)el.textContent=v;}
function hCl(col){const d=col.description||'';if(!d)return 0;if(d.length<10)return 10;const w=d.split(' ').length;if(w<=2)return 20;if(w<=5)return 40;let s=55;if(d.toLowerCase().includes('lkp'))s+=15;if(d.length>80)s+=10;return Math.min(95,s);}
init();
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

if __name__ == "__main__":
    load_existing_results()
    print("\n\U0001F680 Metadata Intelligence Platform v2.0")
    print("   Open: http://localhost:5000\n")
    app.run(debug=True, port=5000)
