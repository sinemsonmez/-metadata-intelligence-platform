"""
Clarity Scorer
--------------
Calculates a clarity score for column descriptions without calling the API.
Uses heuristic rules aligned with the professor's criteria.
"""


def score_description(description: str | None, column: dict) -> int:
    """
    Heuristic clarity score (0-100) for a column description.

    Deductions:
    - Missing description: -100
    - Too short (< 10 chars): -60
    - No table context mentioned: -15
    - No value range/lookup reference (when low cardinality): -20
    - Single word description: -40
    - English text in Turkish context: -20
    - Just repeats column name: -30
    """
    if not description:
        return 0

    score = 100
    desc = description.strip()

    # Too short
    if len(desc) < 10:
        score -= 60
    elif len(desc) < 30:
        score -= 20

    # Single-sentence check
    word_count = len(desc.split())
    if word_count <= 2:
        score -= 40
    elif word_count <= 5:
        score -= 20

    # Just repeats column name
    col_name = column.get("column_name", "").lower().replace("_", " ")
    if col_name in desc.lower() and word_count <= 4:
        score -= 30

    # No value range mentioned when it should be
    distinct = column.get("distinct_count")
    has_lookup = column.get("has_lookup", False)
    if distinct and int(distinct) < 20 and not has_lookup:
        # Low cardinality, no lookup — description should mention values
        known = column.get("known_values", [])
        any_value_mentioned = any(str(v) in desc for v in known) if known else False
        if not any_value_mentioned:
            score -= 20

    # English detection (simple heuristic)
    english_indicators = ["the ", "is ", "this ", "which ", "where ", "that "]
    is_english = sum(1 for e in english_indicators if e in desc.lower()) >= 2
    if is_english:
        score -= 20

    # Vague phrases (Turkish)
    vague_phrases = ["alandır", "tutulur", "bilgisidir", "kodudur", "tarihidir"]
    if any(p in desc.lower() for p in vague_phrases) and word_count <= 4:
        score -= 15

    return max(0, min(100, score))


def score_all(tables: list) -> dict:
    """Calculate clarity scores for all columns."""
    results = {}

    for table in tables:
        table_key = f"{table['schema']}.{table['table_name']}"
        col_scores = {}

        for col in table.get("columns", []):
            score = score_description(col.get("description"), col)
            col["clarity_score"] = score
            col_scores[col["column_name"]] = score

        avg = sum(col_scores.values()) / len(col_scores) if col_scores else 0
        results[table_key] = {
            "average_clarity": round(avg, 1),
            "columns": col_scores
        }
        print(f"  📊 {table_key}: avg clarity = {avg:.1f}")

    return results


if __name__ == "__main__":
    import json
    from pathlib import Path

    data_path = Path(__file__).parent.parent / "data" / "tables" / "enriched_tables.json"
    with open(data_path, "r", encoding="utf-8") as f:
        tables = json.load(f)

    scores = score_all(tables)
    print(json.dumps(scores, indent=2, ensure_ascii=False))
