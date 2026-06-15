"""
Generator Agent
---------------
Reads raw table/column metadata and generates enriched descriptions
using OpenAI Chat Completions API. Context-aware: uses schema, DDL,
functional requirement docs, and TOA docs when available.
"""

import json
from pathlib import Path

from openai_util import generate_text, get_max_workers, run_parallel

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT
DOCS_DIR = REPO_ROOT

_GENERATE_QUALITIES = frozenset({"incomplete", "missing", "wrong", "english", "vague"})
_context_cache: dict[tuple[str, str], dict] = {}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_text(path):
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _extract_col_snippet(doc: str | None, col_name: str, max_len: int = 800) -> str | None:
    """FRD/TOA içinden kolon adına ait bölümü çıkarır."""
    if not doc or col_name not in doc:
        return None
    lines = doc.split("\n")
    chunks: list[str] = []
    capture = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("###") and col_name in line:
            capture = True
            chunks.append(line)
            continue
        if capture:
            if stripped.startswith("###") and col_name not in line:
                break
            chunks.append(line)
        elif col_name in line:
            chunks.append(line)
    text = "\n".join(chunks).strip()
    return text[:max_len] if text else None


def _table_schema(table_name: str, all_tables: list) -> str:
    for t in all_tables:
        if t["table_name"] == table_name:
            return t["schema"]
    return "UNKNOWN"


def enrich_context_for_column(table: dict, column: dict, all_tables: list) -> dict:
    """Kolon için bağlam yükler; kendi tablosunda yetersizse ilişkili dokümanlara bakar."""
    base = dict(_cached_context(table["table_name"], table["schema"]))
    sources: list[dict] = []
    cross_snippets: list[str] = []
    col_name = column["column_name"]
    table_name = table["table_name"]
    schema = table["schema"]
    seen_keys: set[tuple] = set()

    def _add_source(doc_type: str, src_schema: str, src_table: str, reason: str, snippet: str) -> None:
        key = (doc_type, src_schema, src_table, reason)
        if key in seen_keys:
            return
        seen_keys.add(key)
        sources.append({
            "doc_type": doc_type,
            "source_schema": src_schema,
            "source_table": src_table,
            "reason": reason,
        })
        cross_snippets.append(
            f"[Kaynak: {src_schema}.{src_table} — {doc_type} ({reason})]\n{snippet}"
        )

    if base.get("functional_doc"):
        own = _extract_col_snippet(base["functional_doc"], col_name)
        if own:
            _add_source("FRD", schema, table_name, "own_table", own)
    if base.get("toa_doc"):
        own = _extract_col_snippet(base["toa_doc"], col_name)
        if own:
            _add_source("TOA", schema, table_name, "own_table", own)

    has_own_col_doc = any(s["reason"] == "own_table" for s in sources)
    needs_cross = not has_own_col_doc or not (base.get("functional_doc") or base.get("toa_doc"))

    if needs_cross:
        lkp_name = column.get("lookup_table")
        if lkp_name:
            lkp_schema = _table_schema(lkp_name, all_tables)
            lkp_ctx = _cached_context(lkp_name, lkp_schema)
            for doc_type, key in (("FRD", "functional_doc"), ("TOA", "toa_doc")):
                doc = lkp_ctx.get(key)
                if not doc:
                    continue
                snip = _extract_col_snippet(doc, col_name) or _extract_col_snippet(doc, "KOD")
                if snip:
                    _add_source(doc_type, lkp_schema, lkp_name, "lookup_table", snip)

        for doc_type, prefix in (("FRD", "FRD_"), ("TOA", "TOA_")):
            for path in sorted(DOCS_DIR.glob(f"{prefix}*.md")):
                src_table = path.stem[len(prefix):]
                if src_table == table_name:
                    continue
                doc = load_text(path)
                if not doc or col_name not in doc:
                    continue
                snip = _extract_col_snippet(doc, col_name)
                if not snip:
                    continue
                src_schema = _table_schema(src_table, all_tables)
                _add_source(doc_type, src_schema, src_table, "related_column_reference", snip)
                if len(cross_snippets) >= 4:
                    break

    base["context_sources"] = sources
    if cross_snippets:
        base["cross_context"] = "\n\n".join(cross_snippets[:4])
    return base


def load_context(table_name, schema):
    """Load all available context documents for a table."""
    context = {}

    schema_path = DATA_DIR / "schema_list.json"
    if not schema_path.exists():
        schema_path = DATA_DIR / "data" / "schemas" / "schema_list.json"
    if schema_path.exists():
        schema_data = load_json(schema_path)
        for s in schema_data.get("schemas", []):
            if s["schema_name"] == schema:
                context["schema_info"] = s
        context["conceptual_model"] = schema_data.get("conceptual_model", {})

    ddl_path = DOCS_DIR / "create_scripts.sql"
    if not ddl_path.exists():
        ddl_path = DOCS_DIR / "docs" / "ddl" / "create_scripts.sql"
    if ddl_path.exists():
        ddl_content = ddl_path.read_text(encoding="utf-8")
        lines = ddl_content.split("\n")
        relevant = []
        in_table = False
        for line in lines:
            if table_name in line and "CREATE TABLE" in line:
                in_table = True
            if in_table:
                relevant.append(line)
                if line.strip().startswith(");"):
                    break
        if relevant:
            context["ddl"] = "\n".join(relevant)

    frd_path = DOCS_DIR / f"FRD_{table_name}.md"
    if not frd_path.exists():
        frd_path = DOCS_DIR / "docs" / "functional_requirements" / f"FRD_{table_name}.md"
    context["functional_doc"] = load_text(frd_path)

    toa_path = DOCS_DIR / f"TOA_{table_name}.md"
    if not toa_path.exists():
        toa_path = DOCS_DIR / "docs" / "toa" / f"TOA_{table_name}.md"
    context["toa_doc"] = load_text(toa_path)

    return context


def _cached_context(table_name: str, schema: str) -> dict:
    key = (schema, table_name)
    if key not in _context_cache:
        _context_cache[key] = load_context(table_name, schema)
    return _context_cache[key]


def build_prompt(table, column, context):
    parts = [
        "Sen bir veri mimarısın ve metadata kalitesini artırmaya çalışıyorsun.",
        f"\nTABLO: {table['schema']}.{table['table_name']}",
        f"TABLO AÇIKLAMASI: {table.get('description', 'Mevcut değil')}",
        f"\nKOLON: {column['column_name']}",
        f"VERİ TİPİ: {column['data_type']}",
        f"MEVCUT AÇIKLAMA: {column.get('description', 'Yok')}",
        f"AÇIKLAMA KALİTESİ: {column.get('description_quality', 'bilinmiyor')}",
    ]

    if column.get("known_values"):
        parts.append(f"BİLİNEN DEĞERLER: {column['known_values']}")
    if column.get("has_lookup") and column.get("lookup_table"):
        parts.append(f"LOOKUP TABLOSU: {column['lookup_table']}")
    if column.get("fk_table"):
        parts.append(f"FK REFERANSI: {column['fk_table']}")
    if column.get("notes"):
        parts.append(f"NOTLAR: {column['notes']}")
    if context.get("schema_info"):
        parts.append(f"\nŞEMA BİLGİSİ: {json.dumps(context['schema_info'], ensure_ascii=False)}")
    if context.get("functional_doc"):
        parts.append(f"\nFONKSİYONEL İHTİYAÇ DOKÜMANI:\n{context['functional_doc'][:2000]}")
    if context.get("toa_doc"):
        parts.append(f"\nTOA DOKÜMANI:\n{context['toa_doc'][:1000]}")
    if context.get("cross_context"):
        parts.append(
            f"\nİLİŞKİLİ TABLO/KOLON DOKÜMANLARI (cross-reference):\n{context['cross_context'][:2000]}"
        )
    if context.get("ddl"):
        parts.append(f"\nDDL:\n{context['ddl']}")

    parts.append("""
Görevin: Bu kolon için TÜRKÇE, net, hiyerarşik ve belirsizlik içermeyen bir açıklama üret.

Kurallar:
1. Kolon hangi tabloya ait olduğunu, o tablonun ne anlam ifade ettiğini bağlamına katarak açıkla.
2. Varsa lookup değerlerini veya referans tablosunu belirt.
3. İş kuralı varsa ekle.
4. İlgili kolonlara (örn. valör/açılış tarihi gibi çiftler) referans ver.
5. Yanlış veya eksik mevcut açıklamayı düzelt.
6. Maksimum 3 cümle.

Sadece düzeltilmiş açıklamayı yaz, başka hiçbir şey ekleme.""")

    return "\n".join(parts)


def generate_description(table, column, context):
    """OpenAI API ile zenginleştirilmiş kolon açıklaması üretir."""
    prompt = build_prompt(table, column, context)
    return generate_text(prompt, max_tokens=400)


def _generate_task(item: tuple) -> tuple:
    table, column, context = item
    table_name = table["table_name"]
    col_name = column["column_name"]
    try:
        desc = generate_description(table, column, context)
        return table_name, col_name, desc, None
    except Exception as e:
        return table_name, col_name, None, e


def _context_labels(ctx: dict, table: dict) -> dict:
    """Pipeline öncesi mevcut bağlam dokümanlarını etiketle."""
    frd = bool(ctx.get("functional_doc"))
    toa = bool(ctx.get("toa_doc"))
    ddl = bool(ctx.get("ddl"))
    schema = bool(ctx.get("schema_info"))
    any_doc = frd or toa or ddl or bool(ctx.get("cross_context"))
    cross_sources = [s for s in ctx.get("context_sources", []) if s.get("reason") != "own_table"]
    return {
        "frd": frd,
        "toa": toa,
        "ddl": ddl,
        "schema": schema,
        "coverage": "with_docs" if any_doc else "no_docs",
        "cross_refs": len(cross_sources) > 0,
        "sources": ctx.get("context_sources", []),
        "flags": {
            "has_functional_doc": table.get("has_functional_doc", False),
            "has_toa_doc": table.get("has_toa_doc", False),
            "has_ddl": table.get("has_ddl", False),
        },
    }


def run_generator(tables, on_column_done=None):
    """Run generator on all tables and columns, return enriched metadata."""
    _context_cache.clear()
    tasks: list[tuple] = []
    col_contexts: dict[tuple[str, str], dict] = {}
    for table in tables:
        for col in table.get("columns", []):
            if col.get("description_quality", "") in _GENERATE_QUALITIES:
                col_ctx = enrich_context_for_column(table, col, tables)
                col_contexts[(table["table_name"], col["column_name"])] = col_ctx
                tasks.append((table, col, col_ctx))

    generated: dict[tuple[str, str], tuple[str | None, Exception | None]] = {}
    if tasks:
        print(f"  Paralel üretim: {len(tasks)} kolon ({get_max_workers()} worker)")

        def _task_with_cb(item: tuple) -> tuple:
            row = _generate_task(item)
            tn, cn, desc, err = row
            if on_column_done and desc is not None and err is None:
                table, column, _ctx = item
                updated = dict(column)
                updated["original_description"] = column.get("description")
                updated["description"] = desc
                updated["description_quality"] = "generated"
                on_column_done(tn, cn, updated)
            return row

        for row in run_parallel(tasks, _task_with_cb, label="Generator"):
            tn, cn, desc, err = row
            generated[(tn, cn)] = (desc, err)

    enriched = []
    for table in tables:
        print(f"\n📋 Processing table: {table['schema']}.{table['table_name']}")
        ctx = _cached_context(table["table_name"], table["schema"])
        table_sources: list[dict] = []
        enriched_table = dict(table)
        enriched_table["context_labels"] = _context_labels(ctx, table)
        enriched_columns = []

        for col in table.get("columns", []):
            quality = col.get("description_quality", "")
            key = (table["table_name"], col["column_name"])
            col_ctx = col_contexts.get(key)

            if key in generated:
                desc, err = generated[key]
                if err:
                    print(f"  ❌ Error {col['column_name']}: {err}")
                    enriched_columns.append(col)
                else:
                    print(f"  ✏️  Generated: {col['column_name']} [{quality}]")
                    enriched_col = dict(col)
                    enriched_col["original_description"] = col.get("description")
                    enriched_col["description"] = desc
                    enriched_col["description_quality"] = "generated"
                    if col_ctx:
                        enriched_col["context_sources"] = col_ctx.get("context_sources", [])
                        table_sources.extend(col_ctx.get("context_sources", []))
                    enriched_columns.append(enriched_col)
            else:
                print(f"  ✅ OK: {col['column_name']}")
                enriched_columns.append(col)

        if table_sources:
            merged = {(
                s["doc_type"], s["source_schema"], s["source_table"], s["reason"]
            ): s for s in table_sources}
            enriched_table["context_labels"]["sources"] = list(merged.values())
            enriched_table["context_labels"]["cross_refs"] = any(
                s.get("reason") != "own_table" for s in merged.values()
            )
        enriched_table["columns"] = enriched_columns
        enriched.append(enriched_table)

    return enriched


if __name__ == "__main__":
    tables_path = DATA_DIR / "synthetic_tables.json"
    if not tables_path.exists():
        tables_path = DATA_DIR / "data" / "tables" / "synthetic_tables.json"
    tables = load_json(tables_path)
    enriched = run_generator(tables)

    out_path = DATA_DIR / "enriched_tables.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Enriched metadata saved to {out_path}")
