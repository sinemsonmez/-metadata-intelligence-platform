"""Pipeline sırasında UI için canlı metrik hesaplama."""

from __future__ import annotations

from clarity_scorer import score_description

_HIGH_QUALITY = frozenset({"missing", "wrong", "vague", "english", "incomplete"})


def _column_risk(column: dict) -> str:
    if column.get("risk_level") in ("HIGH_RISK", "LOW_RISK"):
        return column["risk_level"]
    q = column.get("description_quality", "")
    if q in _HIGH_QUALITY:
        return "HIGH_RISK"
    return "LOW_RISK"


def _column_clarity(column: dict) -> int:
    if column.get("clarity_score") is not None:
        return int(column["clarity_score"])
    if column.get("critic_score") is not None:
        return int(column["critic_score"])
    return score_description(column.get("description"), column)


def compute_metrics(tables: list, lineage_loops: list | None = None) -> dict:
    high = low = 0
    clarity_sum = 0
    n = 0
    enriched = 0
    tables_with_gen = set()

    for table in tables:
        table_enriched = False
        for col in table.get("columns", []):
            n += 1
            if col.get("description_quality") == "generated" or col.get("original_description"):
                enriched += 1
                table_enriched = True
            risk = _column_risk(col)
            if risk == "HIGH_RISK":
                high += 1
            else:
                low += 1
            clarity_sum += _column_clarity(col)
        if table_enriched:
            tables_with_gen.add(table.get("table_name"))

    return {
        "stat_high": high,
        "stat_low": low,
        "stat_clarity": round(clarity_sum / n) if n else 0,
        "stat_tables": len(tables_with_gen) if tables_with_gen else len(tables),
        "stat_loops": len(lineage_loops) if lineage_loops is not None else 0,
        "columns_total": n,
        "columns_enriched": enriched,
        "tables_total": len(tables),
    }
