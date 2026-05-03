"""
Orchestrator
------------
Runs the full metadata enrichment pipeline:
  1. Generator Agent   → enrich descriptions
  2. Critic Agent      → score and flag risks
  3. Re-generate       → if score < threshold
  4. Lineage Crawler   → traverse ETL graph
  5. Risk Classifier   → produce final risk report
  6. Export            → dashboard-ready JSON
"""

import json
import os
from pathlib import Path

# Agents
from generator_agent import run_generator, load_json
from critic_agent import run_critic

# Scripts
import sys
sys.path.append(str(Path(__file__).parent.parent / "scripts"))
from lineage_crawler import build_lineage_graph, detect_loops
from risk_classifier import classify_all_risks
from clarity_scorer import score_all

DATA_DIR = Path(__file__).parent.parent / "data"
REGENERATION_THRESHOLD = 60
MAX_REGENERATION_ATTEMPTS = 2


def merge_critic_into_tables(tables: list, critic_results: list) -> list:
    """Merge critic scores back into table/column objects."""
    critic_map = {r["table_name"]: r for r in critic_results}

    for table in tables:
        table_critic = critic_map.get(table["table_name"], {})
        col_evals = {e["column_name"]: e for e in table_critic.get("column_evaluations", [])}

        for col in table.get("columns", []):
            eval_data = col_evals.get(col["column_name"], {})
            col["critic_score"] = eval_data.get("overall_score", None)
            col["risk_level"] = eval_data.get("risk_level", "HIGH_RISK")
            col["issues"] = eval_data.get("issues", [])
            col["feedback"] = eval_data.get("feedback", "")
            col["needs_regeneration"] = eval_data.get("needs_regeneration", False)

    return tables


def filter_needs_regeneration(tables: list) -> list:
    """Filter down to only tables/columns that need regeneration."""
    filtered = []
    for table in tables:
        cols_to_regen = [c for c in table.get("columns", []) if c.get("needs_regeneration")]
        if cols_to_regen:
            t = dict(table)
            t["columns"] = cols_to_regen
            filtered.append(t)
    return filtered


def run_pipeline():
    print("=" * 60)
    print("🚀 METADATA INTELLIGENCE PLATFORM — Pipeline Start")
    print("=" * 60)

    # Step 1: Load raw tables
    tables_path = DATA_DIR / "tables" / "synthetic_tables.json"
    tables = load_json(tables_path)
    print(f"\n📥 Loaded {len(tables)} tables")

    # Step 2: Generator
    print("\n" + "─" * 40)
    print("STEP 1: Generator Agent")
    print("─" * 40)
    enriched = run_generator(tables)

    # Step 3: Critic
    print("\n" + "─" * 40)
    print("STEP 2: Critic Agent")
    print("─" * 40)
    critic_results = run_critic(enriched)
    enriched = merge_critic_into_tables(enriched, critic_results)

    # Step 4: Re-generation loop
    for attempt in range(MAX_REGENERATION_ATTEMPTS):
        regen_needed = filter_needs_regeneration(enriched)
        if not regen_needed:
            print(f"\n✅ No columns need regeneration after attempt {attempt}")
            break

        print(f"\n" + "─" * 40)
        print(f"STEP 3: Re-generation attempt {attempt + 1}")
        print("─" * 40)
        regen_enriched = run_generator(regen_needed)
        regen_critic = run_critic(regen_enriched)
        regen_enriched = merge_critic_into_tables(regen_enriched, regen_critic)

        # Patch back into main enriched list
        regen_map = {t["table_name"]: t for t in regen_enriched}
        for i, table in enumerate(enriched):
            if table["table_name"] in regen_map:
                regen_table = regen_map[table["table_name"]]
                regen_col_map = {c["column_name"]: c for c in regen_table["columns"]}
                for j, col in enumerate(enriched[i]["columns"]):
                    if col["column_name"] in regen_col_map:
                        enriched[i]["columns"][j] = regen_col_map[col["column_name"]]

    # Step 5: Lineage
    print("\n" + "─" * 40)
    print("STEP 4: Lineage Crawler")
    print("─" * 40)
    lineage_path = DATA_DIR / "etl" / "lineage.json"
    graph, loops = build_lineage_graph(str(lineage_path))
    print(f"📊 Lineage graph: {len(graph)} nodes")
    if loops:
        print(f"⚠️  LOOPS DETECTED: {loops}")
    else:
        print("✅ No circular dependencies found")

    # Step 6: Risk classification
    print("\n" + "─" * 40)
    print("STEP 5: Risk Classifier")
    print("─" * 40)
    risk_report = classify_all_risks(enriched)

    # Step 7: Clarity scoring
    print("\n" + "─" * 40)
    print("STEP 6: Clarity Scorer")
    print("─" * 40)
    scored = score_all(enriched)

    # Final output
    final_output = {
        "tables": enriched,
        "risk_report": risk_report,
        "lineage_graph": graph,
        "lineage_loops": loops,
        "clarity_scores": scored
    }

    out_path = DATA_DIR / "tables" / "final_output.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"✅ PIPELINE COMPLETE — Output: {out_path}")
    print("=" * 60)

    # Summary
    total_high = sum(
        1 for t in enriched
        for c in t.get("columns", [])
        if c.get("risk_level") == "HIGH_RISK"
    )
    total_low = sum(
        1 for t in enriched
        for c in t.get("columns", [])
        if c.get("risk_level") == "LOW_RISK"
    )
    print(f"\n📊 Summary:")
    print(f"   🔴 HIGH_RISK columns: {total_high}")
    print(f"   🟢 LOW_RISK  columns: {total_low}")
    print(f"   🔗 Lineage loops:     {len(loops)}")

    return final_output


if __name__ == "__main__":
    run_pipeline()
