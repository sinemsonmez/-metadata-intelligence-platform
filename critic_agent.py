"""
Critic Agent
------------
Evaluates generated column descriptions using Google Gemini API.
Scores clarity, completeness, accuracy and assigns HIGH_RISK / LOW_RISK.
"""

import json
from pathlib import Path

from gemini_util import generate_text

CARDINALITY_THRESHOLD = 100


def evaluate_column(table, column):
    prompt = f"""Sen bir veri kalite uzmanısın. Aşağıdaki kolon açıklamasını değerlendir.

TABLO: {table['schema']}.{table['table_name']}
TABLO AÇIKLAMASI: {table.get('description', 'Yok')}

KOLON: {column['column_name']}
VERİ TİPİ: {column['data_type']}
AÇIKLAMA: {column.get('description', 'Yok')}
ORİJİNAL AÇIKLAMA: {column.get('original_description', 'Yok')}
KARDİNALİTE: {column.get('cardinality', 'bilinmiyor')}
DISTINCT SAYISI: {column.get('distinct_count', 'bilinmiyor')}
LOOKUP TABLOSU VAR MI: {column.get('has_lookup', False)}
LOOKUP TABLOSU: {column.get('lookup_table', 'Yok')}
BİLİNEN DEĞERLER: {column.get('known_values', 'Yok')}
VALİDASYON SORUNU: {column.get('validation_issue', 'Yok')}

SADECE JSON döndür, başka hiçbir şey yazma, markdown kullanma:
{{"clarity_score":0,"completeness_score":0,"accuracy_score":0,"overall_score":0,"risk_level":"HIGH_RISK","issues":[],"feedback":"","needs_regeneration":true}}

HIGH_RISK: belirsiz/eksik açıklama, lookup eksikliği, validation hatası, ingilizce açıklama.
LOW_RISK: net, tam, tüm değerler dokümante, validation temiz."""

    raw = generate_text(prompt)

    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception:
        return {
            "clarity_score": 0,
            "completeness_score": 0,
            "accuracy_score": 0,
            "overall_score": 30,
            "risk_level": "HIGH_RISK",
            "issues": ["Parse hatası"],
            "feedback": raw,
            "needs_regeneration": True
        }


def check_lookup_gaps(column):
    issues = []
    distinct = column.get("distinct_count")
    has_lookup = column.get("has_lookup", False)
    if distinct is not None and distinct < CARDINALITY_THRESHOLD and not has_lookup:
        issues.append(
            f"LOW CARDINALITY ({distinct} distinct değer) ama LKP tablosu yok. "
            f"Bilinen değerler: {column.get('known_values', 'bilinmiyor')}"
        )
    return issues


def check_value_validation(column):
    issues = []
    if column.get("validation_issue"):
        issues.append(f"VALUE MISMATCH: {column['validation_issue']}")
    return issues


def run_critic(enriched_tables):
    results = []

    for table in enriched_tables:
        print(f"\n🔍 Critiquing: {table['schema']}.{table['table_name']}")
        table_result = {
            "table_name": table["table_name"],
            "schema": table["schema"],
            "column_evaluations": []
        }

        for col in table.get("columns", []):
            print(f"  📊 Evaluating: {col['column_name']}")

            lookup_issues = check_lookup_gaps(col)
            validation_issues = check_value_validation(col)

            try:
                eval_result = evaluate_column(table, col)
            except Exception as e:
                print(f"  ❌ Error: {e}")
                eval_result = {
                    "overall_score": 0,
                    "risk_level": "HIGH_RISK",
                    "issues": [str(e)],
                    "feedback": "Değerlendirme başarısız",
                    "needs_regeneration": True
                }

            all_issues = eval_result.get("issues", []) + lookup_issues + validation_issues
            eval_result["issues"] = all_issues

            if lookup_issues or validation_issues:
                eval_result["risk_level"] = "HIGH_RISK"

            col_result = {
                "column_name": col["column_name"],
                "description": col.get("description"),
                **eval_result
            }

            table_result["column_evaluations"].append(col_result)

            risk_emoji = "🔴" if eval_result["risk_level"] == "HIGH_RISK" else "🟢"
            print(f"  {risk_emoji} Score: {eval_result.get('overall_score', 0)} | {eval_result['risk_level']}")

        results.append(table_result)

    return results


if __name__ == "__main__":
    data_dir = Path(__file__).resolve().parent

    enriched_path = data_dir / "enriched_tables.json"
    if not enriched_path.exists():
        print("⚠️  enriched_tables.json not found. Run generator_agent.py first.")
        exit(1)

    with open(enriched_path, "r", encoding="utf-8") as f:
        enriched_tables = json.load(f)

    results = run_critic(enriched_tables)

    out_path = data_dir / "critic_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Critic results saved to {out_path}")
