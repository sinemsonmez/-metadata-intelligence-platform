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
  İsteğe bağlı: OPENAI_MODEL, OPENAI_MAX_WORKERS, OPENAI_MAX_TOKENS, ...
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent

from generator_agent import run_generator, load_json
from critic_agent import run_critic
from lineage_crawler import build_lineage_graph
from risk_classifier import classify_all_risks
from clarity_scorer import score_all
from pipeline_metrics import compute_metrics

DATA_DIR = REPO_ROOT
REGENERATION_THRESHOLD = 60
MAX_REGENERATION_ATTEMPTS = 2

ProgressCallback = Callable[[dict], None]


def merge_critic_into_tables(tables, critic_results):
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


def _apply_critic_col(col: dict, eval_data: dict) -> None:
    col["critic_score"] = eval_data.get("overall_score")
    col["risk_level"] = eval_data.get("risk_level", "HIGH_RISK")
    col["issues"] = eval_data.get("issues", [])
    col["feedback"] = eval_data.get("feedback", "")
    col["needs_regeneration"] = eval_data.get("needs_regeneration", False)


def filter_needs_regeneration(tables):
    filtered = []
    for table in tables:
        cols = [c for c in table.get("columns", []) if c.get("needs_regeneration")]
        if cols:
            t = dict(table)
            t["columns"] = cols
            filtered.append(t)
    return filtered


def _count_gen_tasks(tables: list) -> int:
    from generator_agent import _GENERATE_QUALITIES

    return sum(
        1
        for t in tables
        for c in t.get("columns", [])
        if c.get("description_quality", "") in _GENERATE_QUALITIES
    )


def run_pipeline(on_progress: ProgressCallback | None = None):
    def emit(
        phase: str,
        progress: int,
        step: str,
        log_msg: str | None = None,
        *,
        tables_snapshot: list | None = None,
        loops: list | None = None,
    ):
        if log_msg:
            print(log_msg)
        if on_progress:
            metrics = compute_metrics(
                tables_snapshot if tables_snapshot is not None else working,
                loops,
            )
            on_progress(
                {
                    "phase": phase,
                    "progress": progress,
                    "step": step,
                    "log": log_msg,
                    "metrics": metrics,
                }
            )

    print("=" * 60)
    print("METADATA INTELLIGENCE PLATFORM — Pipeline")
    print("=" * 60)

    tables_path = DATA_DIR / "synthetic_tables.json"
    if not tables_path.exists():
        tables_path = DATA_DIR / "data" / "tables" / "synthetic_tables.json"
    tables = load_json(tables_path)
    working = copy.deepcopy(tables)
    print(f"\n📥 {len(tables)} tables loaded")

    emit(
        "load",
        3,
        f"Veri yüklendi — {len(tables)} tablo",
        f"📥 {len(tables)} tablo yüklendi (başlangıç metrikleri)",
        tables_snapshot=working,
    )

    # Step 1: Generator
    gen_total = _count_gen_tasks(tables)
    gen_done = [0]

    def on_gen_column(table_name: str, col_name: str, updated_col: dict):
        for table in working:
            if table["table_name"] == table_name:
                for i, col in enumerate(table.get("columns", [])):
                    if col["column_name"] == col_name:
                        table["columns"][i] = updated_col
                        break
                break
        gen_done[0] += 1
        if gen_total:
            pct = 5 + int(38 * gen_done[0] / gen_total)
        else:
            pct = 43
        emit(
            "generator",
            pct,
            f"Generator (LLM): {gen_done[0]}/{gen_total} kolon — {table_name}.{col_name}",
            tables_snapshot=working,
        )

    emit("generator", 5, "Generator başlıyor…", "─── STEP 1: Generator ───")
    enriched = run_generator(tables, on_column_done=on_gen_column if gen_total else None)
    working = copy.deepcopy(enriched)
    emit(
        "generator",
        45,
        "Generator tamamlandı",
        f"✅ Generator bitti — {gen_done[0]} kolon zenginleştirildi",
        tables_snapshot=working,
    )

    # Step 2: Critic
    critic_total = sum(len(t.get("columns", [])) for t in working)
    critic_done = [0]

    def on_critic_column(table_name: str, col_name: str, eval_data: dict):
        for table in working:
            if table["table_name"] == table_name:
                for col in table.get("columns", []):
                    if col["column_name"] == col_name:
                        _apply_critic_col(col, eval_data)
                        break
                break
        critic_done[0] += 1
        pct = 45 + int(22 * critic_done[0] / max(critic_total, 1))
        emit(
            "critic",
            pct,
            f"Critic (LLM): {critic_done[0]}/{critic_total} kolon",
            tables_snapshot=working,
        )

    emit("critic", 46, "Critic başlıyor…", "─── STEP 2: Critic ───")
    critic_results = run_critic(enriched, on_column_done=on_critic_column)
    working = merge_critic_into_tables(copy.deepcopy(enriched), critic_results)
    emit(
        "critic",
        68,
        "Critic tamamlandı",
        "✅ Critic değerlendirmesi bitti",
        tables_snapshot=working,
    )

    # Step 3: Re-generation
    for attempt in range(MAX_REGENERATION_ATTEMPTS):
        regen_needed = filter_needs_regeneration(working)
        if not regen_needed:
            emit(
                "regen",
                72,
                "Yeniden üretim gerekmedi",
                f"✅ Yeniden üretim gerekmedi (deneme {attempt + 1})",
                tables_snapshot=working,
            )
            break

        emit(
            "regen",
            70 + attempt * 5,
            f"Yeniden üretim — tur {attempt + 1}",
            f"─── STEP 3: Re-generate (attempt {attempt + 1}) ───",
        )
        regen_gen_done = [0]
        regen_total = _count_gen_tasks(regen_needed)

        def on_regen_column(table_name: str, col_name: str, updated_col: dict):
            for table in working:
                if table["table_name"] == table_name:
                    for i, col in enumerate(table.get("columns", [])):
                        if col["column_name"] == col_name:
                            table["columns"][i] = updated_col
                            break
                    break
            regen_gen_done[0] += 1
            emit(
                "regen",
                72 + int(6 * regen_gen_done[0] / max(regen_total, 1)),
                f"Yeniden üretim: {regen_gen_done[0]}/{regen_total} kolon",
                tables_snapshot=working,
            )

        regen_enriched = run_generator(
            regen_needed,
            on_column_done=on_regen_column if regen_total else None,
        )
        regen_critic_done = [0]
        regen_crit_total = sum(len(t.get("columns", [])) for t in regen_enriched)

        def on_regen_critic(table_name: str, col_name: str, eval_data: dict):
            for table in working:
                if table["table_name"] == table_name:
                    for col in table.get("columns", []):
                        if col["column_name"] == col_name:
                            _apply_critic_col(col, eval_data)
                            break
                    break
            regen_critic_done[0] += 1
            emit(
                "regen",
                78 + int(4 * regen_critic_done[0] / max(regen_crit_total, 1)),
                f"Yeniden critic: {regen_critic_done[0]}/{regen_crit_total}",
                tables_snapshot=working,
            )

        regen_critic = run_critic(regen_enriched, on_column_done=on_regen_critic)
        regen_enriched = merge_critic_into_tables(regen_enriched, regen_critic)
        regen_map = {t["table_name"]: t for t in regen_enriched}
        for i, table in enumerate(working):
            if table["table_name"] in regen_map:
                regen_col_map = {
                    c["column_name"]: c for c in regen_map[table["table_name"]]["columns"]
                }
                for j, col in enumerate(working[i]["columns"]):
                    if col["column_name"] in regen_col_map:
                        working[i]["columns"][j] = regen_col_map[col["column_name"]]

    enriched = working

    # Step 4: Lineage
    emit("lineage", 84, "Lineage analizi…", "─── STEP 4: Lineage ───")
    lineage_path = DATA_DIR / "lineage.json"
    if not lineage_path.exists():
        lineage_path = DATA_DIR / "data" / "etl" / "lineage.json"
    graph, loops = build_lineage_graph(str(lineage_path))
    print(f"Nodes: {len(graph)} | Loops: {len(loops)}")
    emit(
        "lineage",
        88,
        f"Lineage tamam — {len(loops)} döngü",
        f"🔗 Lineage: {len(graph)} düğüm, {len(loops)} döngü",
        tables_snapshot=enriched,
        loops=loops,
    )

    # Step 5–6: Risk + Clarity
    emit("risk", 90, "Risk sınıflandırma…", "─── STEP 5: Risk Classifier ───")
    risk_report = classify_all_risks(enriched)
    emit("clarity", 93, "Clarity skorlama…", "─── STEP 6: Clarity Scorer ───")
    scored = score_all(enriched)
    working = enriched

    emit(
        "finalize",
        96,
        "Sonuçlar kaydediliyor…",
        tables_snapshot=working,
        loops=loops,
    )

    final = {
        "tables": enriched,
        "risk_report": risk_report,
        "lineage_graph": graph,
        "lineage_loops": loops,
        "clarity_scores": scored,
    }
    out_path = DATA_DIR / "final_output.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    total_high = sum(
        1 for t in enriched for c in t.get("columns", []) if c.get("risk_level") == "HIGH_RISK"
    )
    total_low = sum(
        1 for t in enriched for c in t.get("columns", []) if c.get("risk_level") == "LOW_RISK"
    )
    metrics = compute_metrics(enriched, loops)

    print("\n" + "=" * 60)
    print(f"DONE — {out_path}")
    print(f"HIGH_RISK: {total_high} | LOW_RISK: {total_low} | Loops: {len(loops)}")
    print("=" * 60)

    if on_progress:
        on_progress(
            {
                "phase": "done",
                "progress": 100,
                "step": "Pipeline tamamlandı",
                "log": (
                    f"🎉 Pipeline tamamlandı — Ort. clarity: {metrics['stat_clarity']} | "
                    f"🟢 {metrics['stat_low']} düşük risk | 🔴 {metrics['stat_high']} yüksek risk"
                ),
                "metrics": metrics,
                "done": True,
            }
        )

    return final


if __name__ == "__main__":
    run_pipeline()
