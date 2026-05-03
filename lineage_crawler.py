"""
Lineage Crawler
---------------
Parses ETL lineage JSON/XML and builds a directed graph.
Detects circular dependencies (loops) using DFS.
"""

import json
from pathlib import Path
from collections import defaultdict


def build_lineage_graph(lineage_json_path: str) -> tuple[dict, list]:
    """
    Build a directed graph from ETL lineage data.
    Returns: (graph, loops)
      - graph: {source_table: [target_table, ...]}
      - loops: list of circular paths detected
    """
    with open(lineage_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs = data.get("etl_lineage", [])
    graph = defaultdict(list)
    node_meta = {}

    for job in jobs:
        src_schema = job["source"]["schema"]
        src_table = job["source"]["table"]
        tgt_schema = job["target"]["schema"]
        tgt_table = job["target"]["table"]

        src_key = f"{src_schema}.{src_table}"
        tgt_key = f"{tgt_schema}.{tgt_table}"

        graph[src_key].append(tgt_key)
        node_meta[src_key] = {"schema": src_schema, "table": src_table}
        node_meta[tgt_key] = {"schema": tgt_schema, "table": tgt_table}

    loops = detect_loops(dict(graph))

    print(f"📌 Nodes: {list(graph.keys())}")
    for src, targets in graph.items():
        for tgt in targets:
            print(f"  {src} → {tgt}")

    return dict(graph), loops


def detect_loops(graph: dict) -> list:
    """
    DFS-based cycle detection on a directed graph.
    Returns list of detected cycle paths.
    """
    visited = set()
    rec_stack = set()
    cycles = []

    def dfs(node, path):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, path)
            elif neighbor in rec_stack:
                # Found a cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(" → ".join(cycle))

        path.pop()
        rec_stack.discard(node)

    all_nodes = set(graph.keys())
    for targets in graph.values():
        all_nodes.update(targets)

    for node in all_nodes:
        if node not in visited:
            dfs(node, [])

    return cycles


def get_upstream(graph: dict, table: str) -> list:
    """Get all upstream tables that feed into this table."""
    upstream = []
    for src, targets in graph.items():
        if table in targets:
            upstream.append(src)
    return upstream


def get_downstream(graph: dict, table: str) -> list:
    """Get all downstream tables fed by this table."""
    return graph.get(table, [])


def find_orphans(graph: dict) -> list:
    """Tables that have no upstream AND no downstream connections."""
    all_sources = set(graph.keys())
    all_targets = {t for targets in graph.values() for t in targets}
    all_nodes = all_sources | all_targets

    orphans = []
    for node in all_nodes:
        has_upstream = node in all_targets
        has_downstream = node in all_sources and len(graph[node]) > 0
        if not has_upstream and not has_downstream:
            orphans.append(node)

    return orphans


if __name__ == "__main__":
    lineage_path = Path(__file__).parent.parent / "data" / "etl" / "lineage.json"
    graph, loops = build_lineage_graph(str(lineage_path))

    print("\n🔄 Loop Analysis:")
    if loops:
        for loop in loops:
            print(f"  ⚠️  LOOP: {loop}")
    else:
        print("  ✅ No loops detected")

    print("\n🏝️  Orphan Analysis:")
    orphans = find_orphans(graph)
    if orphans:
        for o in orphans:
            print(f"  ❓ ORPHAN: {o}")
    else:
        print("  ✅ No orphans detected")
