"""
Risk Classifier
---------------
Tags columns as HIGH_RISK or LOW_RISK based on metadata quality indicators.
"""

CARDINALITY_THRESHOLD = 100


def get_risk_reasons(column: dict) -> list[str]:
    """Return human-readable reasons for risk classification."""
    reasons: list[str] = []

    if column.get("risk_level") == "HIGH_RISK" and column.get("critic_score") is not None:
        if column.get("critic_score", 100) < 60:
            reasons.append(f"Critic skoru düşük ({column['critic_score']}/100)")

    quality = column.get("description_quality", "")
    quality_labels = {
        "missing": "Açıklama eksik (missing)",
        "wrong": "Yanlış veya tutarsız açıklama (wrong)",
        "vague": "Belirsiz açıklama (vague)",
        "english": "İngilizce açıklama — Türkçe şema bekleniyor",
        "incomplete": "Eksik açıklama (incomplete)",
    }
    if quality in quality_labels and quality != "generated":
        reasons.append(quality_labels[quality])

    if column.get("validation_issue"):
        reasons.append("Doğrulama uyumsuzluğu: " + column["validation_issue"])

    distinct = column.get("distinct_count")
    has_lookup = column.get("has_lookup", False)
    if distinct is not None and int(distinct) < CARDINALITY_THRESHOLD and not has_lookup:
        reasons.append(f"Düşük kardinalite ({distinct} distinct) ancak lookup tablosu yok")

    for issue in column.get("issues", []):
        if issue not in reasons:
            reasons.append(issue)

    if not reasons and column.get("risk_level") == "LOW_RISK":
        reasons.append("Açıklama kalitesi ve metadata göstergeleri yeterli")

    return reasons


def classify_risk(column: dict) -> str:
    """
    Rule-based risk classification for a column.
    HIGH_RISK triggers:
      - Missing or vague description
      - Low cardinality without lookup table
      - Validation mismatch documented
      - Description in wrong language (English in Turkish schema)
      - Already marked by critic as HIGH_RISK
    """
    # Carry over critic assessment
    if column.get("risk_level") == "HIGH_RISK":
        return "HIGH_RISK"

    quality = column.get("description_quality", "")
    if quality in ("missing", "wrong", "vague"):
        return "HIGH_RISK"

    if quality == "english":
        return "HIGH_RISK"  # English description in Turkish schema

    if column.get("validation_issue"):
        return "HIGH_RISK"

    distinct = column.get("distinct_count")
    has_lookup = column.get("has_lookup", False)
    if distinct is not None and int(distinct) < CARDINALITY_THRESHOLD and not has_lookup:
        return "HIGH_RISK"

    return "LOW_RISK"


def classify_all_risks(tables: list) -> dict:
    """Run risk classification on all tables/columns and produce a summary."""
    report = {
        "high_risk_columns": [],
        "low_risk_columns": [],
        "summary": {}
    }

    for table in tables:
        table_key = f"{table['schema']}.{table['table_name']}"

        for col in table.get("columns", []):
            risk = classify_risk(col)
            col["risk_level"] = risk
            col["risk_reasons"] = get_risk_reasons(col)

            entry = {
                "table": table_key,
                "column": col["column_name"],
                "risk_level": risk,
                "issues": col.get("issues", []),
                "description": col.get("description", ""),
            }

            if risk == "HIGH_RISK":
                report["high_risk_columns"].append(entry)
            else:
                report["low_risk_columns"].append(entry)

    report["summary"] = {
        "total_columns": len(report["high_risk_columns"]) + len(report["low_risk_columns"]),
        "high_risk_count": len(report["high_risk_columns"]),
        "low_risk_count": len(report["low_risk_columns"]),
    }

    print(f"🔴 HIGH RISK: {report['summary']['high_risk_count']}")
    print(f"🟢 LOW RISK:  {report['summary']['low_risk_count']}")

    return report


if __name__ == "__main__":
    import json
    from pathlib import Path

    data_path = Path(__file__).resolve().parent / "enriched_tables.json"
    if not data_path.exists():
        data_path = Path(__file__).resolve().parent / "data" / "tables" / "enriched_tables.json"
    with open(data_path, "r", encoding="utf-8") as f:
        tables = json.load(f)

    report = classify_all_risks(tables)
    print(json.dumps(report["summary"], indent=2))
