"""
Orchestrator
------------
Tam pipeline'ı çalıştırır:
  1. Generator Agent  → açıklamaları üret
  2. Critic Agent     → skorla ve risk etiketle
  3. Re-generate      → skoru düşük olanları tekrar üret
  4. Lineage Crawler  → ETL graph traversal
  5. Risk Classifier  → final risk raporu
  6. Clarity Scorer   → kolon başı skor

Çalıştırmak için:
  OPENAI_API_KEY (veya proje kökünde .env)
  İsteğe bağlı: OPENAI_MODEL, OPENAI_MAX_WORKERS (varsayılan 16, paralel API),
  OPENAI_MAX_TOKENS, OPENAI_MIN_INTERVAL_SEC (varsayılan 0), OPENAI_MAX_RETRIES.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

from generator_agent import run_generator, load_json
from critic_agent import run_critic
from lineage_crawler import build_lineage_graph, detect_loops
from risk_classifier import classify_all_risks
from clarity_scorer import score_all

DATA_DIR = REPO_ROOT
REGENERATION_THRESHOLD = 60
MAX_REGENERATION_ATTEMPTS = 2


def merge_critic_into_tables(tables, critic_results):
    critic_map = {r["table_name"]: r for r in critic_results}
    for table in tables:
        table_critic = critic_map.get(table["table_name"], {})
        col_evals = {e["column_name"]: e for e in table_critic.get("column_evaluations", [])}
        for col in table.get("columns", []):
            eval_data = col_evals.get(col["column_name"], {})
            col["critic_score"]        = eval_data.get("overall_score", None)
            col["risk_level"]          = eval_data.get("risk_level", "HIGH_RISK")
            col["issues"]              = eval_data.get("issues", [])
            col["feedback"]            = eval_data.get("feedback", "")
            col["needs_regeneration"]  = eval_data.get("needs_regeneration", False)
    return tables


def filter_needs_regeneration(tables):
    filtered = []
    for table in tables:
        cols = [c for c in table.get("columns", []) if c.get("needs_regeneration")]
        if cols:
            t = dict(table)
            t["columns"] = cols
            filtered.append(t)
    return filtered


def run_pipeline():
    print("=" * 60)
    print("🚀 METADATA INTELLIGENCE PLATFORM — Pipeline")
    print("=" * 60)

    tables_path = DATA_DIR / "synthetic_tables.json"
    if not tables_path.exists():
        tables_path = DATA_DIR / "data" / "tables" / "synthetic_tables.json"
    tables = load_json(tables_path)
    print(f"\n📥 {len(tables)} tables loaded")

    # Step 1: Generate
    print("\n─── STEP 1: Generator ───")
    enriched = run_generator(tables)

    # Step 2: Critic
    print("\n─── STEP 2: Critic ───")
    critic_results = run_critic(enriched)
    enriched = merge_critic_into_tables(enriched, critic_results)

    # Step 3: Re-generation loop
    for attempt in range(MAX_REGENERATION_ATTEMPTS):
        regen_needed = filter_needs_regeneration(enriched)
        if not regen_needed:
            print(f"\n✅ No re-generation needed after attempt {attempt}")
            break
        print(f"\n─── STEP 3: Re-generate (attempt {attempt+1}) ───")
        regen_enriched = run_generator(regen_needed)
        regen_critic   = run_critic(regen_enriched)
        regen_enriched = merge_critic_into_tables(regen_enriched, regen_critic)
        regen_map = {t["table_name"]: t for t in regen_enriched}
        for i, table in enumerate(enriched):
            if table["table_name"] in regen_map:
                regen_col_map = {c["column_name"]: c for c in regen_map[table["table_name"]]["columns"]}
                for j, col in enumerate(enriched[i]["columns"]):
                    if col["column_name"] in regen_col_map:
                        enriched[i]["columns"][j] = regen_col_map[col["column_name"]]

    # Step 4: Lineage
    print("\n─── STEP 4: Lineage ───")
    lineage_path = DATA_DIR / "lineage.json"
    if not lineage_path.exists():
        lineage_path = DATA_DIR / "data" / "etl" / "lineage.json"
    graph, loops = build_lineage_graph(str(lineage_path))
    print(f"Nodes: {len(graph)} | Loops: {len(loops)}")

    # Step 5: Risk
    print("\n─── STEP 5: Risk Classifier ───")
    risk_report = classify_all_risks(enriched)

    # Step 6: Clarity
    print("\n─── STEP 6: Clarity Scorer ───")
    scored = score_all(enriched)

    # Save
    final = {"tables": enriched, "risk_report": risk_report, "lineage_graph": graph, "lineage_loops": loops, "clarity_scores": scored}
    out_path = DATA_DIR / "final_output.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    total_high = sum(1 for t in enriched for c in t.get("columns", []) if c.get("risk_level") == "HIGH_RISK")
    total_low  = sum(1 for t in enriched for c in t.get("columns", []) if c.get("risk_level") == "LOW_RISK")

    print("\n" + "=" * 60)
    print(f"✅ DONE — {out_path}")
    print(f"🔴 HIGH_RISK: {total_high} | 🟢 LOW_RISK: {total_low} | 🔗 Loops: {len(loops)}")
    print("=" * 60)


if __name__ == "__main__":
    run_pipeline()
