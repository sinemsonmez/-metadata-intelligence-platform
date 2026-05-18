"""
Clarity Scorer
--------------
Calculates a 0-100 clarity score for column descriptions without calling the API.

A column is accepted only if its clarity score is >= 80.
The system no longer returns HIGH_RISK / LOW_RISK labels.
"""

ACCEPTANCE_THRESHOLD = 80


def score_description(description, column: dict) -> dict:
    issues = []

    if not description:
        return {
            "score": 0,
            "risk_score": 100,
            "accepted": False,
            "threshold": ACCEPTANCE_THRESHOLD,
            "issues": ["Missing description"]
        }

    score = 100
    desc = description.strip()
    word_count = len(desc.split())

    # Length and clarity
    if len(desc) < 10:
        score -= 60
        issues.append("Description is too short")
    elif len(desc) < 30:
        score -= 20
        issues.append("Description may be too short")

    # Word count check
    if word_count <= 2:
        score -= 40
        issues.append("Description contains too few words")
    elif word_count <= 5:
        score -= 20
        issues.append("Description is not detailed enough")

    # Just repeats column name
    col_name = column.get("column_name", "").lower().replace("_", " ")
    if col_name in desc.lower() and word_count <= 4:
        score -= 30
        issues.append("Description only repeats the column name")

    # Low cardinality value explanation
    distinct = column.get("distinct_count")
    has_lookup = column.get("has_lookup", False)

    if distinct and int(distinct) < 20:
        known_values = column.get("known_values", [])
        any_value_mentioned = (
            any(str(v) in desc for v in known_values)
            if known_values else False
        )

        if not has_lookup and not any_value_mentioned:
            score -= 20
            issues.append("Low-cardinality values are not explained")

    # Lookup exists but not mentioned
    if has_lookup and "lookup" not in desc.lower() and "referans" not in desc.lower():
        score -= 10
        issues.append("Lookup/reference table exists but is not mentioned")

    # English detection in Turkish context
    english_indicators = ["the ", "is ", "this ", "which ", "where ", "that "]
    is_english = sum(1 for e in english_indicators if e in desc.lower()) >= 2

    if is_english:
        score -= 20
        issues.append("Description language is not consistent with Turkish context")

    # Vague Turkish phrases
    vague_phrases = ["alandır", "tutulur", "bilgisidir", "kodudur", "tarihidir"]

    if any(p in desc.lower() for p in vague_phrases) and word_count <= 4:
        score -= 15
        issues.append("Description is vague or generic")

    score = max(0, min(100, score))

    return {
        "score": score,
        "risk_score": 100 - score,
        "accepted": score >= ACCEPTANCE_THRESHOLD,
        "threshold": ACCEPTANCE_THRESHOLD,
        "issues": issues
    }


def score_all(tables: list) -> dict:
    results = {}

    for table in tables:
        table_key = f"{table['schema']}.{table['table_name']}"
        col_scores = {}

        for col in table.get("columns", []):
            score_result = score_description(col.get("description"), col)

            col["clarity_score"] = score_result["score"]
            col["risk_score"] = score_result["risk_score"]
            col["accepted"] = score_result["accepted"]
            col["quality_issues"] = score_result["issues"]

            col_scores[col["column_name"]] = score_result

        avg = (
            sum(item["score"] for item in col_scores.values()) / len(col_scores)
            if col_scores else 0
        )

        results[table_key] = {
            "average_clarity": round(avg, 1),
            "threshold": ACCEPTANCE_THRESHOLD,
            "accepted_columns": sum(
                1 for item in col_scores.values() if item["accepted"]
            ),
            "columns": col_scores
        }

        print(f"  📊 {table_key}: avg clarity = {avg:.1f}")

    return results


if __name__ == "__main__":
    import json
    from pathlib import Path

    data_path = Path(__file__).resolve().parent / "enriched_tables.json"

    if not data_path.exists():
        data_path = (
            Path(__file__).resolve().parent
            / "data"
            / "tables"
            / "enriched_tables.json"
        )

    with open(data_path, "r", encoding="utf-8") as f:
        tables = json.load(f)

    scores = score_all(tables)
    print(json.dumps(scores, indent=2, ensure_ascii=False))