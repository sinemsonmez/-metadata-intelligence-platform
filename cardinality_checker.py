"""
Cardinality Checker
-------------------
Identifies low-cardinality columns that are missing LKP table definitions.

Strategy:
1. First check metadata (distinct_count in synthetic_tables.json)
2. If metadata stats unavailable, generate SELECT COUNT(DISTINCT ...) query
3. For partitioned tables: consolidate across partitions
4. Threshold: CARDINALITY_THRESHOLD = 100
"""

CARDINALITY_THRESHOLD = 100


def check_cardinality_from_metadata(column: dict) -> dict:
    """
    Use metadata stats if available. Returns analysis dict.
    """
    distinct = column.get("distinct_count")
    has_lookup = column.get("has_lookup", False)
    cardinality = column.get("cardinality", "unknown")

    result = {
        "column_name": column["column_name"],
        "source": "metadata",
        "distinct_count": distinct,
        "cardinality_category": cardinality,
        "has_lookup": has_lookup,
        "lookup_gap": False,
        "suggested_query": None
    }

    if distinct is not None:
        if int(distinct) < CARDINALITY_THRESHOLD and not has_lookup:
            result["lookup_gap"] = True
            result["recommendation"] = (
                f"Column has {distinct} distinct values (below threshold {CARDINALITY_THRESHOLD}) "
                f"but no LKP table is defined. Consider creating a lookup table."
            )
    else:
        # Metadata stats unavailable — suggest a query
        result["source"] = "query_needed"
        result["suggested_query"] = generate_cardinality_query(
            column["column_name"],
            column.get("_table_name", "UNKNOWN_TABLE"),
            column.get("_schema", "UNKNOWN_SCHEMA"),
            column.get("_is_partitioned", False),
            column.get("_partition_column", None)
        )

    return result


def generate_cardinality_query(
    col_name: str,
    table_name: str,
    schema: str,
    is_partitioned: bool = False,
    partition_col: str = None
) -> str:
    """Generate an optimized cardinality check query."""
    full_table = f"{schema}.{table_name}"

    if is_partitioned and partition_col:
        # Consolidate across recent partitions to avoid full scan
        return f"""
-- Partitioned table cardinality check (consolidated across partitions)
-- NOTE: Table statistics may be stale; querying sample of recent partitions

SELECT '{col_name}' AS COLUMN_NAME,
       COUNT(DISTINCT {col_name}) AS DISTINCT_COUNT,
       COUNT(*) AS TOTAL_ROWS
FROM {full_table}
WHERE {partition_col} >= ADD_MONTHS(SYSDATE, -12)  -- Last 12 months sample
UNION ALL
-- Full table stats from metadata (may be stale)
SELECT '{col_name}' AS COLUMN_NAME,
       NUM_DISTINCT AS DISTINCT_COUNT,
       NUM_ROWS AS TOTAL_ROWS
FROM ALL_TAB_COL_STATISTICS
WHERE OWNER = '{schema}'
  AND TABLE_NAME = '{table_name}'
  AND COLUMN_NAME = '{col_name}';
""".strip()
    else:
        return f"""
-- Cardinality check for {full_table}.{col_name}
SELECT COUNT(DISTINCT {col_name}) AS DISTINCT_COUNT
FROM {full_table};
-- If DISTINCT_COUNT < {CARDINALITY_THRESHOLD}, consider creating an LKP table.
""".strip()


def run_cardinality_check(tables: list) -> list:
    """Run cardinality analysis on all tables."""
    gaps = []

    for table in tables:
        schema = table["schema"]
        table_name = table["table_name"]
        is_partitioned = table.get("is_partitioned", False)
        partition_col = table.get("partition_column")

        for col in table.get("columns", []):
            col["_table_name"] = table_name
            col["_schema"] = schema
            col["_is_partitioned"] = is_partitioned
            col["_partition_column"] = partition_col

            result = check_cardinality_from_metadata(col)
            result["table"] = f"{schema}.{table_name}"

            if result["lookup_gap"] or result["source"] == "query_needed":
                gaps.append(result)

    return gaps


if __name__ == "__main__":
    import json
    from pathlib import Path

    data_path = Path(__file__).parent.parent / "data" / "tables" / "synthetic_tables.json"
    with open(data_path, "r", encoding="utf-8") as f:
        tables = json.load(f)

    gaps = run_cardinality_check(tables)

    print(f"\n⚠️  Found {len(gaps)} cardinality issues:\n")
    for g in gaps:
        print(f"  🔍 {g['table']}.{g['column_name']}")
        if g.get("recommendation"):
            print(f"     {g['recommendation']}")
        if g.get("suggested_query"):
            print(f"     Suggested query:\n{g['suggested_query']}\n")
