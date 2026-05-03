"""
Critic Agent
------------
Evaluates generated column descriptions for:
  - Completeness (is the context fully captured?)
  - Accuracy (does it match DDL, lookup values, functional docs?)
  - Clarity Score (hierarchical, no ambiguity, structured)
  - Risk Level (HIGH_RISK / LOW_RISK)

Returns a score (0-100) and improvement feedback.
"""

import json
import os
from pathlib import Path
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

CARDINALITY_THRESHOLD = 100  # columns with distinct < threshold are "low cardinality"


def evaluate_column(table: dict, column: dict) -> dict:
    """
    Call Claude to evaluate the quality of a column description.
    Returns a dict with score, risk_level, issues, and feedback.
    """

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

Aşağıdaki kriterlere göre değerlendir ve SADECE JSON formatında yanıt ver:

{{
  "clarity_score": 0-100,
  "completeness_score": 0-100,
  "accuracy_score": 0-100,
  "overall_score": 0-100,
  "risk_level": "LOW_RISK" | "HIGH_RISK",
  "issues": ["sorun1", "sorun2"],
  "feedback": "İyileştirme önerisi",
  "needs_regeneration": true | false
}}

Kriterler:
- HIGH_RISK: belirsiz açıklama, lookup eksik (düşük kardinaliteli ama LKP yok), validation hatası, eksik açıklama, yanlış değer aralığı
- LOW_RISK: net açıklama, tüm değerler dokümante, lookup mevcut veya gerekmez, validation clean
- needs_regeneration: overall_score < 60 ise true
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()

    # Parse JSON response
    try:
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "clarity_score": 0,
            "completeness_score": 0,
            "accuracy_score": 0,
            "overall_score": 0,
            "risk_level": "HIGH_RISK",
            "issues": ["Değerlendirme parse edilemedi"],
            "feedback": raw,
            "needs_regeneration": True
        }


def check_lookup_gaps(column: dict) -> list:
    """
    Rule-based check: if cardinality is low and no lookup table exists,
    flag as lookup gap. Avoids heavy DB queries via metadata first.
    """
    issues = []
    distinct = column.get("distinct_count")
    has_lookup = column.get("has_lookup", False)

    if distinct is not None and distinct < CARDINALITY_THRESHOLD and not has_lookup:
        issues.append(
            f"LOW CARDINALITY ({distinct} distinct değer) ama LKP tablosu yok. "
            f"Bilinen değerler: {column.get('known_values', 'bilinmiyor')}"
        )

    return issues


def check_value_validation(column: dict) -> list:
    """Check if documented values match actual DB values."""
    issues = []
    if column.get("validation_issue"):
        issues.append(f"VALUE MISMATCH: {column['validation_issue']}")
    return issues


def run_critic(enriched_tables: list) -> list:
    """Run critic on all enriched tables and columns."""
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

            # Rule-based checks
            lookup_issues = check_lookup_gaps(col)
            validation_issues = check_value_validation(col)

            # AI evaluation
            try:
                eval_result = evaluate_column(table, col)
            except Exception as e:
                print(f"  ❌ Error evaluating {col['column_name']}: {e}")
                eval_result = {
                    "overall_score": 0,
                    "risk_level": "HIGH_RISK",
                    "issues": [str(e)],
                    "feedback": "Değerlendirme başarısız",
                    "needs_regeneration": True
                }

            # Merge rule-based issues
            all_issues = eval_result.get("issues", []) + lookup_issues + validation_issues
            eval_result["issues"] = all_issues

            # Force HIGH_RISK if rule-based issues found
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
    data_dir = Path(__file__).parent.parent / "data" / "tables"

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
