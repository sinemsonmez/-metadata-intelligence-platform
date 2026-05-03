"""
Ablation Study
==============
4 konfigürasyonu karşılaştırır, her birinin accuracy'ye katkısını ölçer.
Google Gemini API kullanır (ücretsiz).

Çalıştırmak için: GOOGLE_API_KEY veya GEMINI_API_KEY
"""

import json
import os
import time
import statistics
from pathlib import Path
from dataclasses import dataclass, field, asdict

from gemini_util import generate_text

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT
DOCS_DIR = ROOT
OUT_DIR = ROOT / "ablation"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── Ground Truth ─────────────────────────────────────────────────────────────
GROUND_TRUTH = {
    "XXX_HESAP.HESAP_NO":               {"risk": "LOW_RISK",  "validation": False, "lookup_gap": False},
    "XXX_HESAP.ACILIS_TARIHI":          {"risk": "LOW_RISK",  "validation": False, "lookup_gap": False},
    "XXX_HESAP.VALOR_TARIHI":           {"risk": "LOW_RISK",  "validation": False, "lookup_gap": False},
    "XXX_HESAP.HESAP_TIP_KOD":          {"risk": "LOW_RISK",  "validation": False, "lookup_gap": False},
    "XXX_HESAP.HESAP_DURUM_KOD":        {"risk": "HIGH_RISK", "validation": True,  "lookup_gap": True},
    "XXX_HESAP.MUSTERI_NO":             {"risk": "LOW_RISK",  "validation": False, "lookup_gap": False},
    "XXX_HESAP.SUBE_KOD":               {"risk": "HIGH_RISK", "validation": False, "lookup_gap": True},
    "KRD_MUS_KREDI.KRD_NO":             {"risk": "HIGH_RISK", "validation": False, "lookup_gap": False},
    "KRD_MUS_KREDI.KRD_MUS_KOBI_TIP":  {"risk": "HIGH_RISK", "validation": False, "lookup_gap": True},
    "KRD_MUS_KREDI.INT_SHK_A_30GCK_ADT_LM": {"risk": "HIGH_RISK", "validation": True, "lookup_gap": False},
    "KRD_MUS_KREDI.KRD_TUTAR":          {"risk": "LOW_RISK",  "validation": False, "lookup_gap": False},
    "KRD_MUS_KREDI.KRD_DURUM":          {"risk": "HIGH_RISK", "validation": False, "lookup_gap": True},
    "MUS_SEGMENTASYON.MUSTERI_NO":       {"risk": "LOW_RISK",  "validation": False, "lookup_gap": False},
    "MUS_SEGMENTASYON.SEGMENT_KOD":      {"risk": "HIGH_RISK", "validation": False, "lookup_gap": False},
    "MUS_SEGMENTASYON.GELIR_GRUBU":      {"risk": "HIGH_RISK", "validation": False, "lookup_gap": True},
    "RISK_IZLEME.MUSTERI_NO":            {"risk": "LOW_RISK",  "validation": False, "lookup_gap": False},
    "RISK_IZLEME.RISK_SKOR":             {"risk": "LOW_RISK",  "validation": False, "lookup_gap": False},
    "RISK_IZLEME.RISK_SINIF":            {"risk": "HIGH_RISK", "validation": False, "lookup_gap": True},
}

TRUE_HIGH_RISK  = {k for k, v in GROUND_TRUTH.items() if v["risk"] == "HIGH_RISK"}
TRUE_VALIDATION = {k for k, v in GROUND_TRUTH.items() if v["validation"]}
TRUE_LOOKUP_GAP = {k for k, v in GROUND_TRUTH.items() if v["lookup_gap"]}

# ─── Data classes ─────────────────────────────────────────────────────────────
@dataclass
class ColumnResult:
    key: str
    table: str
    column: str
    description: str
    clarity_score: float
    predicted_risk: str
    issues: list
    api_calls: int = 0

@dataclass
class ConfigResult:
    config_name: str
    config_label: str
    columns: list = field(default_factory=list)
    total_api_calls: int = 0
    elapsed_seconds: float = 0.0
    avg_clarity: float = 0.0
    high_risk_detection_rate: float = 0.0
    low_risk_precision: float = 0.0
    f1_score: float = 0.0
    validation_catch_rate: float = 0.0
    lookup_gap_catch_rate: float = 0.0
    avg_desc_length: float = 0.0

# ─── Context loading ──────────────────────────────────────────────────────────
def load_context_full(table_name, schema):
    ctx = {}
    schema_path = DATA_DIR / "schema_list.json"
    if not schema_path.exists():
        schema_path = DATA_DIR / "data" / "schemas" / "schema_list.json"
    if schema_path.exists():
        data = json.loads(schema_path.read_text("utf-8"))
        for s in data.get("schemas", []):
            if s["schema_name"] == schema:
                ctx["schema_info"] = s
        ctx["conceptual_model"] = data.get("conceptual_model", {})

    ddl_path = DOCS_DIR / "create_scripts.sql"
    if not ddl_path.exists():
        ddl_path = DOCS_DIR / "docs" / "ddl" / "create_scripts.sql"
    if ddl_path.exists():
        lines = ddl_path.read_text("utf-8").split("\n")
        block, in_t = [], False
        for line in lines:
            if table_name in line and "CREATE TABLE" in line:
                in_t = True
            if in_t:
                block.append(line)
                if line.strip().startswith(");"):
                    break
        if block:
            ctx["ddl"] = "\n".join(block)

    frd = DOCS_DIR / f"FRD_{table_name}.md"
    if not frd.exists():
        frd = DOCS_DIR / "docs" / "functional_requirements" / f"FRD_{table_name}.md"
    if frd.exists():
        ctx["functional_doc"] = frd.read_text("utf-8")

    toa = DOCS_DIR / f"TOA_{table_name}.md"
    if not toa.exists():
        toa = DOCS_DIR / "docs" / "toa" / f"TOA_{table_name}.md"
    if toa.exists():
        ctx["toa_doc"] = toa.read_text("utf-8")[:1000]

    return ctx

# ─── Prompts ──────────────────────────────────────────────────────────────────
def build_generator_prompt(table, col, ctx):
    parts = [
        "Sen bir veri mimarısın ve metadata kalitesini artırmaya çalışıyorsun.",
        f"TABLO: {table['schema']}.{table['table_name']}",
        f"TABLO AÇIKLAMASI: {table.get('description', 'Yok')}",
        f"KOLON: {col['column_name']}",
        f"VERİ TİPİ: {col['data_type']}",
        f"MEVCUT AÇIKLAMA: {col.get('description', 'Yok')}",
    ]
    if col.get("known_values"):
        parts.append(f"BİLİNEN DEĞERLER: {col['known_values']}")
    if col.get("has_lookup") and col.get("lookup_table"):
        parts.append(f"LOOKUP TABLOSU: {col['lookup_table']}")
    if col.get("notes"):
        parts.append(f"NOTLAR: {col['notes']}")
    if ctx.get("schema_info"):
        parts.append(f"ŞEMA: {json.dumps(ctx['schema_info'], ensure_ascii=False)}")
    if ctx.get("functional_doc"):
        parts.append(f"FRD:\n{ctx['functional_doc'][:1500]}")
    if ctx.get("toa_doc"):
        parts.append(f"TOA:\n{ctx['toa_doc']}")
    if ctx.get("ddl"):
        parts.append(f"DDL:\n{ctx['ddl']}")
    parts.append("Görev: TÜRKÇE, net, max 3 cümle açıklama üret. Sadece açıklamayı yaz.")
    return "\n".join(parts)


def build_critic_prompt(table, col, description):
    return f"""Veri kalite uzmanısın. Kolon açıklamasını değerlendir.

TABLO: {table['schema']}.{table['table_name']}
KOLON: {col['column_name']} ({col['data_type']})
AÇIKLAMA: {description}
DISTINCT: {col.get('distinct_count','?')} | LOOKUP: {col.get('has_lookup',False)} | VALİDASYON: {col.get('validation_issue','Yok')}

SADECE JSON döndür (markdown yok):
{{"clarity_score":0,"completeness_score":0,"accuracy_score":0,"overall_score":0,"risk_level":"HIGH_RISK","issues":[],"feedback":"","needs_regeneration":true}}"""

# ─── API call ─────────────────────────────────────────────────────────────────
def call_api(prompt):
    return generate_text(prompt)


def parse_critic_json(raw):
    text = raw.strip()
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip())
    except Exception:
        return {"overall_score": 30, "risk_level": "HIGH_RISK", "issues": ["Parse hatası"], "needs_regeneration": True, "clarity_score": 30}

# ─── Clarity scorer (no API) ──────────────────────────────────────────────────
def heuristic_clarity(desc, col):
    if not desc:
        return 0.0
    score = 100.0
    d = desc.strip()
    if len(d) < 10:   score -= 60
    elif len(d) < 40: score -= 20
    wc = len(d.split())
    if wc <= 2:   score -= 40
    elif wc <= 5: score -= 20
    col_words = col.get("column_name", "").lower().replace("_", " ")
    if col_words in d.lower() and wc <= 4:
        score -= 30
    distinct = col.get("distinct_count")
    if distinct and int(distinct) < 20 and not col.get("has_lookup"):
        known = col.get("known_values", [])
        if known and not any(str(v) in d for v in known):
            score -= 20
    en_hits = sum(1 for e in ["the ", "is a ", "this ", "which ", "where "] if e in d.lower())
    if en_hits >= 2:
        score -= 25
    vague = ["alandır", "tutulur", "bilgisidir", "kodudur", "tarihidir"]
    if any(p in d.lower() for p in vague) and wc <= 4:
        score -= 15
    return max(0.0, min(100.0, score))


def rule_based_issues(col):
    issues = []
    distinct = col.get("distinct_count")
    if distinct and int(distinct) < 100 and not col.get("has_lookup"):
        issues.append(f"LOOKUP_GAP: {distinct} distinct değer ama LKP tablosu yok")
    if col.get("validation_issue"):
        issues.append(f"VALIDATION: {col['validation_issue']}")
    return issues

# ─── Metrics ──────────────────────────────────────────────────────────────────
def compute_metrics(config):
    clarity_scores = [c.clarity_score for c in config.columns]
    config.avg_clarity = round(statistics.mean(clarity_scores), 2) if clarity_scores else 0

    desc_lengths = [len(c.description) for c in config.columns if c.description]
    config.avg_desc_length = round(statistics.mean(desc_lengths), 1) if desc_lengths else 0

    pred_high = {c.key for c in config.columns if c.predicted_risk == "HIGH_RISK"}
    pred_low  = {c.key for c in config.columns if c.predicted_risk == "LOW_RISK"}

    tp = len(pred_high & TRUE_HIGH_RISK)
    fp = len(pred_high - TRUE_HIGH_RISK)
    fn = len(TRUE_HIGH_RISK - pred_high)
    tn = len(pred_low - TRUE_HIGH_RISK)

    recall    = tp / (tp + fn) if (tp + fn) else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    lr_prec   = tn / (tn + fp) if (tn + fp) else 0

    config.high_risk_detection_rate = round(recall * 100, 1)
    config.low_risk_precision       = round(lr_prec * 100, 1)
    config.f1_score = round(2 * precision * recall / (precision + recall) * 100, 1) if (precision + recall) else 0

    pred_val = {c.key for c in config.columns if any("VALIDATION" in i or "mismatch" in i.lower() for i in c.issues)}
    config.validation_catch_rate = round(len(pred_val & TRUE_VALIDATION) / len(TRUE_VALIDATION) * 100, 1) if TRUE_VALIDATION else 0

    pred_lkp = {c.key for c in config.columns if any("LOOKUP" in i.upper() or "LKP" in i.upper() for i in c.issues)}
    config.lookup_gap_catch_rate = round(len(pred_lkp & TRUE_LOOKUP_GAP) / len(TRUE_LOOKUP_GAP) * 100, 1) if TRUE_LOOKUP_GAP else 0

# ─── Config runners ───────────────────────────────────────────────────────────
NEEDS_ENRICH = {"incomplete", "missing", "wrong", "english", "vague"}


def run_config_A(tables):
    """A: Full Pipeline — Generator + Critic + Re-generate + Full Context"""
    cfg = ConfigResult("A", "Full Pipeline")
    t0 = time.time()
    for table in tables:
        ctx = load_context_full(table["table_name"], table["schema"])
        for col in table.get("columns", []):
            key = f"{table['table_name']}.{col['column_name']}"
            api_calls = 0
            if col.get("description_quality") in NEEDS_ENRICH:
                desc = call_api(build_generator_prompt(table, col, ctx))
                api_calls += 1
            else:
                desc = col.get("description", "")
            critic = parse_critic_json(call_api(build_critic_prompt(table, col, desc)))
            api_calls += 1
            if critic.get("needs_regeneration") and critic.get("overall_score", 100) < 60:
                desc = call_api(build_generator_prompt(table, col, ctx) + f"\n\nGERİ BİLDİRİM: {critic.get('feedback','')}\nDaha iyi yaz.")
                api_calls += 1
            issues = critic.get("issues", []) + rule_based_issues(col)
            cfg.columns.append(ColumnResult(key=key, table=table["table_name"], column=col["column_name"],
                description=desc, clarity_score=heuristic_clarity(desc, col),
                predicted_risk=critic.get("risk_level", "HIGH_RISK"), issues=issues, api_calls=api_calls))
            cfg.total_api_calls += api_calls
    cfg.elapsed_seconds = round(time.time() - t0, 1)
    compute_metrics(cfg)
    return cfg


def run_config_B(tables):
    """B: No Critic — only Generator, rule-based risk"""
    cfg = ConfigResult("B", "No Critic")
    t0 = time.time()
    for table in tables:
        ctx = load_context_full(table["table_name"], table["schema"])
        for col in table.get("columns", []):
            key = f"{table['table_name']}.{col['column_name']}"
            api_calls = 0
            if col.get("description_quality") in NEEDS_ENRICH:
                desc = call_api(build_generator_prompt(table, col, ctx))
                api_calls += 1
            else:
                desc = col.get("description", "")
            clarity = heuristic_clarity(desc, col)
            issues = rule_based_issues(col)
            predicted_risk = "HIGH_RISK" if clarity < 50 or issues else "LOW_RISK"
            cfg.columns.append(ColumnResult(key=key, table=table["table_name"], column=col["column_name"],
                description=desc, clarity_score=clarity, predicted_risk=predicted_risk, issues=issues, api_calls=api_calls))
            cfg.total_api_calls += api_calls
    cfg.elapsed_seconds = round(time.time() - t0, 1)
    compute_metrics(cfg)
    return cfg


def run_config_C(tables):
    """C: No Context — Generator + Critic but no docs/DDL/schema"""
    cfg = ConfigResult("C", "No Context")
    t0 = time.time()
    for table in tables:
        for col in table.get("columns", []):
            key = f"{table['table_name']}.{col['column_name']}"
            api_calls = 0
            if col.get("description_quality") in NEEDS_ENRICH:
                stripped_col = {"column_name": col["column_name"], "data_type": col["data_type"], "description": col.get("description", "")}
                stripped_table = {"schema": table["schema"], "table_name": table["table_name"], "description": None}
                desc = call_api(build_generator_prompt(stripped_table, stripped_col, {}))
                api_calls += 1
            else:
                desc = col.get("description", "")
            critic = parse_critic_json(call_api(build_critic_prompt(table, col, desc)))
            api_calls += 1
            issues = critic.get("issues", []) + rule_based_issues(col)
            cfg.columns.append(ColumnResult(key=key, table=table["table_name"], column=col["column_name"],
                description=desc, clarity_score=heuristic_clarity(desc, col),
                predicted_risk=critic.get("risk_level", "HIGH_RISK"), issues=issues, api_calls=api_calls))
            cfg.total_api_calls += api_calls
    cfg.elapsed_seconds = round(time.time() - t0, 1)
    compute_metrics(cfg)
    return cfg


def run_config_D(tables):
    """D: No Re-generate — Generator + Critic + Context, single pass"""
    cfg = ConfigResult("D", "No Re-generate")
    t0 = time.time()
    for table in tables:
        ctx = load_context_full(table["table_name"], table["schema"])
        for col in table.get("columns", []):
            key = f"{table['table_name']}.{col['column_name']}"
            api_calls = 0
            if col.get("description_quality") in NEEDS_ENRICH:
                desc = call_api(build_generator_prompt(table, col, ctx))
                api_calls += 1
            else:
                desc = col.get("description", "")
            critic = parse_critic_json(call_api(build_critic_prompt(table, col, desc)))
            api_calls += 1
            issues = critic.get("issues", []) + rule_based_issues(col)
            cfg.columns.append(ColumnResult(key=key, table=table["table_name"], column=col["column_name"],
                description=desc, clarity_score=heuristic_clarity(desc, col),
                predicted_risk=critic.get("risk_level", "HIGH_RISK"), issues=issues, api_calls=api_calls))
            cfg.total_api_calls += api_calls
    cfg.elapsed_seconds = round(time.time() - t0, 1)
    compute_metrics(cfg)
    return cfg

# ─── Main ─────────────────────────────────────────────────────────────────────
def run_ablation():
    print("=" * 60)
    print("🔬 ABLATION STUDY — Metadata Intelligence Platform")
    print("=" * 60)

    tables_path = DATA_DIR / "synthetic_tables.json"
    if not tables_path.exists():
        tables_path = DATA_DIR / "data" / "tables" / "synthetic_tables.json"
    tables = json.loads(tables_path.read_text("utf-8"))

    print(f"\n📋 Tables: {len(tables)} | Columns: {sum(len(t.get('columns',[])) for t in tables)}")

    configs = [
        ("A — Full Pipeline",   run_config_A),
        ("B — No Critic",       run_config_B),
        ("C — No Context",      run_config_C),
        ("D — No Re-generate",  run_config_D),
    ]

    results = []
    for label, runner in configs:
        print(f"\n{'─'*50}\n▶  {label}\n{'─'*50}")
        cfg = runner(tables)
        results.append(cfg)
        print(f"  ✅ {cfg.elapsed_seconds}s | {cfg.total_api_calls} API calls")
        print(f"  📈 Clarity={cfg.avg_clarity:.1f} F1={cfg.f1_score:.1f}% HR={cfg.high_risk_detection_rate:.1f}%")

    # Save results
    json_path = OUT_DIR / "ablation_results.json"
    json_path.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Results saved to {json_path}")

    # Print summary table
    print(f"\n{'Config':<20} {'Clarity':>8} {'F1%':>7} {'HR%':>7} {'Val%':>6} {'LKP%':>6} {'API':>5}")
    print("─" * 58)
    for r in results:
        print(f"{r.config_name:<20} {r.avg_clarity:>8.1f} {r.f1_score:>7.1f} {r.high_risk_detection_rate:>7.1f} {r.validation_catch_rate:>6.1f} {r.lookup_gap_catch_rate:>6.1f} {r.total_api_calls:>5}")

    return results


if __name__ == "__main__":
    run_ablation()
