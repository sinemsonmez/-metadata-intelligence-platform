"""
Orchestrator — Metadata Intelligence Pipeline v2.0
----------------------------------------------------
Pipeline adımları:
  1. Generator Agent   → açıklama üretimi (kolon adı fallback, TOA/FRD kural çıkarımı, LKP değerleri)
  2. Critic Agent      → bankacılık sektörü yeterlilik değerlendirmesi (0-100 skor)
  3. Re-generate       → overall_score < 80 olan kolonlar için yeniden üretim
  4. Clarity Scorer    → heuristic skor (0-100, eşik 80)
  5. Risk Classifier   → skor bazlı risk oranı
  6. Lineage Crawler   → ETL döngü tespiti
  7. Export            → dashboard-ready JSON
"""

import json
import os
from pathlib import Path

from generator_agent import run_generator, load_json
from critic_agent import run_critic

import sys
sys.path.append(str(Path(__file__).parent.parent / "scripts"))
from lineage_crawler import build_lineage_graph
from risk_classifier import classify_all_risks
from clarity_scorer import score_all, CLARITY_THRESHOLD

DATA_DIR = Path(__file__).parent.parent / "data"
REGENERATION_THRESHOLD = 80   # critic overall_score < 80 → yeniden üret
MAX_REGENERATION_ATTEMPTS = 2


def merge_critic_into_tables(tables: list, critic_results: list) -> list:
    critic_map = {r["table_name"]: r for r in critic_results}
    for table in tables:
        table_critic = critic_map.get(table["table_name"], {})
        col_evals = {e["column_name"]: e for e in table_critic.get("column_evaluations", [])}
        for col in table.get("columns", []):
            ev = col_evals.get(col["column_name"], {})
            col["critic_score"]        = ev.get("overall_score")
            col["risk_band"]           = ev.get("risk_band", "YÜKSEK")
            col["issues"]              = ev.get("issues", [])
            col["feedback"]            = ev.get("feedback", "")
            col["needs_regeneration"]  = ev.get("needs_regeneration", False)
    return tables


def filter_needs_regeneration(tables: list) -> list:
    filtered = []
    for table in tables:
        cols = [c for c in table.get("columns", []) if c.get("needs_regeneration")]
        if cols:
            t = dict(table)
            t["columns"] = cols
            filtered.append(t)
    return filtered


def run_pipeline():
    print("=" * 65)
    print("🚀 METADATA INTELLIGENCE PLATFORM — Pipeline v2.0")
    print(f"   Clarity Eşiği      : {CLARITY_THRESHOLD}/100")
    print(f"   Regeneration Eşiği : {REGENERATION_THRESHOLD}/100")
    print("=" * 65)

    # ── 1. Raw data yükle ─────────────────────────────────────────────────
    tables_path = DATA_DIR / "tables" / "synthetic_tables.json"
    tables = load_json(tables_path)
    print(f"\n📥 {len(tables)} tablo yüklendi | "
          f"{sum(len(t.get('columns',[])) for t in tables)} kolon")

    # ── 2. Generator ──────────────────────────────────────────────────────
    print("\n" + "─" * 50)
    print("ADIM 1: Generator Agent")
    print("─" * 50)
    enriched = run_generator(tables)

    # ── 3. Critic ─────────────────────────────────────────────────────────
    print("\n" + "─" * 50)
    print("ADIM 2: Critic Agent — Bankacılık Sektörü Değerlendirmesi")
    print("─" * 50)
    critic_results = run_critic(enriched)
    enriched = merge_critic_into_tables(enriched, critic_results)

    # ── 4. Re-generation döngüsü ──────────────────────────────────────────
    for attempt in range(MAX_REGENERATION_ATTEMPTS):
        regen_needed = filter_needs_regeneration(enriched)
        if not regen_needed:
            print(f"\n✅ Tüm kolonlar eşiği geçti (attempt {attempt + 1})")
            break

        regen_count = sum(len(t.get("columns", [])) for t in regen_needed)
        print(f"\n" + "─" * 50)
        print(f"ADIM 3: Yeniden Üretim — Attempt {attempt + 1}")
        print(f"   {regen_count} kolon yeniden üretilecek")
        print("─" * 50)

        regen_enriched = run_generator(regen_needed)
        regen_critic   = run_critic(regen_enriched)
        regen_enriched = merge_critic_into_tables(regen_enriched, regen_critic)

        regen_map = {t["table_name"]: t for t in regen_enriched}
        for i, table in enumerate(enriched):
            if table["table_name"] in regen_map:
                regen_table = regen_map[table["table_name"]]
                regen_col_map = {c["column_name"]: c for c in regen_table["columns"]}
                for j, col in enumerate(enriched[i]["columns"]):
                    if col["column_name"] in regen_col_map:
                        enriched[i]["columns"][j] = regen_col_map[col["column_name"]]

    # ── 5. Clarity Scorer ─────────────────────────────────────────────────
    print("\n" + "─" * 50)
    print("ADIM 4: Clarity Scorer — Bankacılık Yeterlilik Skoru")
    print("─" * 50)
    clarity_results = score_all(enriched)

    # ── 6. Risk Classifier ────────────────────────────────────────────────
    print("\n" + "─" * 50)
    print("ADIM 5: Risk Classifier — Skor Bazlı Dağılım")
    print("─" * 50)
    risk_report = classify_all_risks(enriched)

    # ── 7. Lineage ────────────────────────────────────────────────────────
    print("\n" + "─" * 50)
    print("ADIM 6: Lineage Crawler")
    print("─" * 50)
    lineage_path = DATA_DIR / "etl" / "lineage.json"
    graph, loops = build_lineage_graph(str(lineage_path))
    print(f"📊 {len(graph)} node | {len(loops)} döngü tespit edildi")
    if loops:
        for lp in loops:
            print(f"  ⚠️  LOOP: {lp}")

    # ── 8. Final export ───────────────────────────────────────────────────
    final = {
        "tables": enriched,
        "risk_report": risk_report,
        "clarity_scores": clarity_results,
        "lineage_graph": graph,
        "lineage_loops": loops,
        "config": {
            "clarity_threshold": CLARITY_THRESHOLD,
            "regeneration_threshold": REGENERATION_THRESHOLD,
        }
    }

    out_path = DATA_DIR / "tables" / "final_output.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    # ── Özet ──────────────────────────────────────────────────────────────
    summary = risk_report.get("summary", {})
    clarity_summary = clarity_results.get("__summary__", {})

    print("\n" + "=" * 65)
    print("✅ PIPELINE TAMAMLANDI")
    print(f"   Çıktı: {out_path}")
    print("=" * 65)
    print("\n📊 ÖZET:")
    print(f"   Toplam kolon          : {summary.get('total_columns', '?')}")
    print(f"   Avg risk skoru        : {summary.get('avg_risk_score', '?')}/100")
    print(f"   🔴 Yüksek risk        : {summary.get('yuksek_risk_count', '?')} (%{summary.get('yuksek_risk_pct','?')})")
    print(f"   🟡 Orta risk          : {summary.get('orta_risk_count', '?')} (%{summary.get('orta_risk_pct','?')})")
    print(f"   🟢 Düşük risk         : {summary.get('dusuk_risk_count', '?')} (%{summary.get('dusuk_risk_pct','?')})")
    print(f"   Avg clarity skoru     : {clarity_summary.get('average_score', '?')}/100")
    print(f"   Eşik altı (<{CLARITY_THRESHOLD}) kolon: {clarity_summary.get('below_threshold', '?')}")
    print(f"   Clarity risk oranı    : %{clarity_summary.get('risk_ratio_pct', '?')}")
    print(f"   ETL lineage döngüsü   : {len(loops)}")
    print("=" * 65)

    return final


if __name__ == "__main__":
    run_pipeline()
