"""
Generator Agent
---------------
Reads raw table/column metadata and generates enriched descriptions
using the Anthropic Claude API. Context-aware: uses schema, DDL,
functional requirement docs, and TOA docs when available.
"""

import json
import os
from pathlib import Path
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

DATA_DIR = Path(__file__).parent.parent / "data"
DOCS_DIR = Path(__file__).parent.parent / "docs"


def load_json(path: Path) -> dict | list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_text(path: Path) -> str | None:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def load_context(table_name: str, schema: str) -> dict:
    """Load all available context documents for a table."""
    context = {}

    # Schema info
    schema_path = DATA_DIR / "schemas" / "schema_list.json"
    if schema_path.exists():
        schema_data = load_json(schema_path)
        for s in schema_data.get("schemas", []):
            if s["schema_name"] == schema:
                context["schema_info"] = s
        context["conceptual_model"] = schema_data.get("conceptual_model", {})

    # DDL
    ddl_path = DOCS_DIR / "ddl" / "create_scripts.sql"
    if ddl_path.exists():
        ddl_content = ddl_path.read_text(encoding="utf-8")
        # Extract just the relevant table section
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

    # Functional requirements
    frd_path = DOCS_DIR / "functional_requirements" / f"FRD_{table_name}.md"
    context["functional_doc"] = load_text(frd_path)

    # TOA
    toa_path = DOCS_DIR / "toa" / f"TOA_{table_name}.md"
    context["toa_doc"] = load_text(toa_path)

    return context


def build_prompt(table: dict, column: dict, context: dict) -> str:
    prompt_parts = [
        f"Sen bir veri mimarısın ve metadata kalitesini artırmaya çalışıyorsun.",
        f"\nTABLO: {table['schema']}.{table['table_name']}",
        f"TABLO AÇIKLAMASI: {table.get('description', 'Mevcut değil')}",
        f"\nKOLON: {column['column_name']}",
        f"VERİ TİPİ: {column['data_type']}",
        f"MEVCUT AÇIKLAMA: {column.get('description', 'Yok')}",
        f"AÇIKLAMA KALİTESİ: {column.get('description_quality', 'bilinmiyor')}",
    ]

    if column.get("known_values"):
        prompt_parts.append(f"BİLİNEN DEĞERLER: {column['known_values']}")

    if column.get("has_lookup") and column.get("lookup_table"):
        prompt_parts.append(f"LOOKUP TABLOSU: {column['lookup_table']}")

    if column.get("fk_table"):
        prompt_parts.append(f"FK REFERANSI: {column['fk_table']}")

    if column.get("notes"):
        prompt_parts.append(f"NOTLAR: {column['notes']}")

    if context.get("schema_info"):
        prompt_parts.append(f"\nŞEMA BİLGİSİ: {json.dumps(context['schema_info'], ensure_ascii=False)}")

    if context.get("functional_doc"):
        prompt_parts.append(f"\nFONKSİYONEL İHTİYAÇ DOKÜMANI:\n{context['functional_doc'][:2000]}")

    if context.get("toa_doc"):
        prompt_parts.append(f"\nTOA DOKÜMANI:\n{context['toa_doc'][:1000]}")

    if context.get("ddl"):
        prompt_parts.append(f"\nDDL:\n{context['ddl']}")

    prompt_parts.append("""
Görevin: Bu kolon için TÜRKÇE, net, hiyerarşik ve belirsizlik içermeyen bir açıklama üret.

Kurallar:
1. Kolon hangi tabloya ait olduğunu, o tablonun ne anlam ifade ettiğini bağlamına katarak açıkla.
2. Varsa lookup değerlerini veya referans tablosunu belirt.
3. İş kuralı varsa ekle.
4. İlgili kolonlara (örn. valör/açılış tarihi gibi çiftler) referans ver.
5. Yanlış veya eksik mevcut açıklamayı düzelt.
6. Maksimum 3 cümle.

Sadece düzeltilmiş açıklamayı yaz, başka hiçbir şey ekleme.
""")

    return "\n".join(prompt_parts)


def generate_description(table: dict, column: dict, context: dict) -> str:
    """Call Claude API to generate an enriched column description."""
    prompt = build_prompt(table, column, context)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text.strip()


def run_generator(tables: list) -> list:
    """Run generator on all tables and columns, return enriched metadata."""
    enriched = []

    for table in tables:
        print(f"\n📋 Processing table: {table['schema']}.{table['table_name']}")
        context = load_context(table["table_name"], table["schema"])

        enriched_table = dict(table)
        enriched_columns = []

        for col in table.get("columns", []):
            quality = col.get("description_quality", "")

            # Only enrich columns that need it
            if quality in ("incomplete", "missing", "wrong", "english", "vague"):
                print(f"  ✏️  Generating description for: {col['column_name']} [{quality}]")
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
    tables = load_json(DATA_DIR / "tables" / "synthetic_tables.json")
    enriched = run_generator(tables)

    out_path = DATA_DIR / "tables" / "enriched_tables.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Enriched metadata saved to {out_path}")
