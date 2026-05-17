"""
Generator Agent
---------------
Reads raw table/column metadata and generates enriched descriptions
using OpenAI Chat Completions API. Context-aware: uses schema, DDL,
functional requirement docs, and TOA docs when available.
"""

import json
from pathlib import Path

from openai_util import generate_text

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT
DOCS_DIR = REPO_ROOT


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_text(path):
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


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
    return generate_text(prompt)


def run_generator(tables):
    """Run generator on all tables and columns, return enriched metadata."""
    enriched = []

    for table in tables:
        print(f"\n📋 Processing table: {table['schema']}.{table['table_name']}")
        context = load_context(table["table_name"], table["schema"])

        enriched_table = dict(table)
        enriched_columns = []

        for col in table.get("columns", []):
            quality = col.get("description_quality", "")

            if quality in ("incomplete", "missing", "wrong", "english", "vague"):
                print(f"  ✏️  Generating: {col['column_name']} [{quality}]")
                try:
                    new_description = generate_description(table, col, context)
                    enriched_col = dict(col)
                    enriched_col["original_description"] = col.get("description")
                    enriched_col["description"] = new_description
                    enriched_col["description_quality"] = "generated"
                    enriched_columns.append(enriched_col)
                except Exception as e:
                    print(f"  ❌ Error: {e}")
                    enriched_columns.append(col)
            else:
                print(f"  ✅ OK: {col['column_name']}")
                enriched_columns.append(col)

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
