"""
Generator Agent — Bağlam Odaklı, Sektör Bilincine Sahip
---------------------------------------------------------
Kolon açıklamalarını üretir / zenginleştirir.

Yenilikler:
  1. Kolon ADINDA anlam çıkarımı (HESAP_DURUM_KOD → hesap durum kodu, statü bilgisi)
  2. Lookup tablosu değerlerini açıklamaya otomatik ekler
  3. TOA dokümanından iş kuralı cümleleri çıkarır (validasyon, tarih kısıtı vb.)
  4. FRD'den kolon spesifik kuralları çıkarır
  5. Açıklama tamamen boşsa kolon adından fallback türetir
  6. Original description'ı her zaman saklar (ilk hal karşılaştırması için)
"""

import json
import os
import re
from pathlib import Path
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

DATA_DIR = Path(__file__).parent.parent / "data"
DOCS_DIR = Path(__file__).parent.parent / "docs"

# ── Kolon adı → Türkçe anlam sözlüğü (fallback için) ────────────────────────
COL_SUFFIX_MAP = {
    "NO":       "numarası",
    "KOD":      "kodu",
    "KOD_":     "kodu",
    "TARIHI":   "tarihi",
    "TUTARI":   "tutarı",
    "TUTAR":    "tutarı",
    "SINIF":    "sınıfı",
    "TIP":      "tipi",
    "TIP_KOD":  "tip kodu",
    "DURUM":    "durum bilgisi",
    "DURUM_KOD":"durum kodu",
    "SKOR":     "skoru",
    "GRUBU":    "grubu",
    "ACIKLAMA": "açıklaması",
    "ADI":      "adı",
}

COL_PREFIX_MAP = {
    "HESAP":    "Hesap",
    "MUSTERI":  "Müşteri",
    "KREDI":    "Kredi",
    "KRD":      "Kredi",
    "RISK":     "Risk",
    "SUBE":     "Şube",
    "SEGMENT":  "Segment",
    "GELIR":    "Gelir",
    "VALOR":    "Valör",
    "ACILIS":   "Açılış",
    "KAPANIS":  "Kapanış",
    "VADE":     "Vade",
    "LKP":      "Lookup",
    "INT":      "Entegrasyon",
}


def infer_description_from_col_name(col_name: str, table_name: str = "", schema: str = "") -> str:
    """
    Kolon adından Türkçe açıklama taslağı türetir.
    Boş açıklama olduğunda fallback olarak kullanılır.
    """
    parts = col_name.split("_")
    readable_parts = []
    for p in parts:
        mapped = COL_PREFIX_MAP.get(p, None)
        if mapped:
            readable_parts.append(mapped)
        else:
            readable_parts.append(p.capitalize())

    base = " ".join(readable_parts)
    table_ctx = f" {table_name.replace('_', ' ').lower()} tablosuna ait" if table_name else ""
    return f"{base}{table_ctx} bilgisini tutar."


def extract_toa_business_rules(toa_doc: str, col_name: str) -> list[str]:
    """
    TOA dokümanından kolon adıyla ilgili iş kuralı cümlelerini çıkarır.
    Özellikle validasyon sorguları ve kısıt satırlarını toplar.
    """
    if not toa_doc:
        return []

    rules = []
    lines = toa_doc.split("\n")
    col_norm = col_name.upper()

    for i, line in enumerate(lines):
        line_upper = line.upper()
        # Kolon adını içeren satırlar
        if col_norm in line_upper:
            clean = line.strip().lstrip("- *#/").strip()
            if len(clean) > 10:
                rules.append(clean)

        # Özel iş kuralı kalıpları (validasyon yorumları)
        if col_norm in line_upper and (
            "BEKLENEN" in line_upper
            or "ALERT" in line_upper
            or "UYARI" in line_upper
            or "KONTROL" in line_upper
            or ">=" in line
            or "<" in line
        ):
            # Bir sonraki satırı da al (açıklayıcı olabilir)
            if i + 1 < len(lines):
                next_clean = lines[i + 1].strip().lstrip("- *#/--").strip()
                if len(next_clean) > 5 and next_clean not in rules:
                    rules.append(next_clean)

    return rules[:3]  # En fazla 3 kural


def extract_frd_column_rules(frd_doc: str, col_name: str) -> str:
    """
    FRD dokümanından kolon adı başlığı altındaki açıklama bloğunu çıkarır.
    """
    if not frd_doc:
        return ""

    lines = frd_doc.split("\n")
    col_header = f"### {col_name}"
    in_section = False
    block = []

    for line in lines:
        if line.strip().startswith(col_header):
            in_section = True
            continue
        if in_section:
            if line.strip().startswith("### ") or line.strip().startswith("## "):
                break
            clean = line.strip()
            if clean:
                block.append(clean)

    return "\n".join(block[:5]) if block else ""


def enrich_column_with_lookup(column: dict, all_tables: list) -> list:
    """
    Lookup tablosundan değerleri çekip listeye döner.
    Sadece metadata'daki known_values'u kullanır (DB bağlantısı yok).
    """
    lookup_table = column.get("lookup_table")
    if not lookup_table:
        return column.get("known_values", [])

    # Metadata içinde lookup tablosunu bul
    for t in all_tables:
        if t.get("table_name") == lookup_table:
            for c in t.get("columns", []):
                if c.get("known_values"):
                    return c["known_values"]

    return column.get("known_values", [])


def load_json(path: Path) -> dict | list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_text(path: Path) -> str | None:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def load_context(table_name: str, schema: str) -> dict:
    """Tablo için tüm mevcut bağlam dokümanlarını yükler."""
    context = {}

    schema_path = DATA_DIR / "schemas" / "schema_list.json"
    if schema_path.exists():
        schema_data = load_json(schema_path)
        for s in schema_data.get("schemas", []):
            if s["schema_name"] == schema:
                context["schema_info"] = s
        context["conceptual_model"] = schema_data.get("conceptual_model", {})

    ddl_path = DOCS_DIR / "ddl" / "create_scripts.sql"
    if ddl_path.exists():
        ddl_content = ddl_path.read_text(encoding="utf-8")
        lines = ddl_content.split("\n")
        relevant, in_table = [], False
        for line in lines:
            if table_name in line and "CREATE TABLE" in line:
                in_table = True
            if in_table:
                relevant.append(line)
                if line.strip().startswith(");"):
                    break
        if relevant:
            context["ddl"] = "\n".join(relevant)

    frd_path = DOCS_DIR / "functional_requirements" / f"FRD_{table_name}.md"
    frd_text = load_text(frd_path)
    context["functional_doc"] = frd_text
    context["has_frd"] = frd_text is not None

    toa_path = DOCS_DIR / "toa" / f"TOA_{table_name}.md"
    toa_text = load_text(toa_path)
    context["toa_doc"] = toa_text[:2000] if toa_text else None
    context["has_toa"] = toa_text is not None

    return context


def build_prompt(table: dict, column: dict, context: dict, lookup_values: list) -> str:
    col_name = column["column_name"]

    # FRD'den kolon spesifik kural
    frd_col_rule = ""
    if context.get("functional_doc"):
        frd_col_rule = extract_frd_column_rules(context["functional_doc"], col_name)

    # TOA'dan iş kuralları
    toa_rules = []
    if context.get("toa_doc"):
        toa_rules = extract_toa_business_rules(context["toa_doc"], col_name)

    # Kolon adından anlam çıkarımı
    col_name_hint = infer_description_from_col_name(col_name, table.get("table_name", ""), table.get("schema", ""))

    prompt_parts = [
        "Sen deneyimli bir bankacılık veri mimarısın.",
        "Görevin: Kolon açıklamasını TÜRKÇE, sektörel anlam yeterliliğiyle yeniden yaz.",
        "",
        f"ŞEMA     : {table['schema']}",
        f"TABLO    : {table['table_name']}",
        f"TABLO AÇIKLAMASI: {table.get('description', 'Mevcut değil')}",
        "",
        f"KOLON    : {col_name}",
        f"VERİ TİPİ: {column['data_type']}",
        f"MEVCUT AÇIKLAMA: {column.get('description', '(boş)')}",
        f"AÇIKLAMA KALİTESİ: {column.get('description_quality', 'bilinmiyor')}",
        f"KARDİNALİTE: {column.get('cardinality', 'bilinmiyor')}",
    ]

    if column.get("distinct_count"):
        prompt_parts.append(f"DISTINCT DEĞER SAYISI: {column['distinct_count']}")

    if lookup_values:
        prompt_parts.append(f"BİLİNEN DEĞERLER (lookup/enum): {lookup_values}")

    if column.get("has_lookup") and column.get("lookup_table"):
        prompt_parts.append(f"LOOKUP TABLOSU: {column['lookup_table']}")

    if column.get("fk_table"):
        prompt_parts.append(f"FK REFERANSI: {column['fk_table']}")

    if column.get("validation_issue"):
        prompt_parts.append(f"⚠ VALİDASYON SORUNU: {column['validation_issue']}")

    if column.get("notes"):
        prompt_parts.append(f"METADATA NOTLARI: {column['notes']}")

    if col_name_hint:
        prompt_parts.append(f"KOLON ADI ANALİZİ: {col_name_hint}")

    if frd_col_rule:
        prompt_parts.append(f"\nFRD — KOLON SPESIFIK KURAL:\n{frd_col_rule}")

    if toa_rules:
        prompt_parts.append(f"\nTOA — İŞ KURALLARI:\n" + "\n".join(f"  - {r}" for r in toa_rules))

    if context.get("schema_info"):
        prompt_parts.append(f"\nŞEMA BİLGİSİ: {json.dumps(context['schema_info'], ensure_ascii=False)}")

    if context.get("functional_doc") and not frd_col_rule:
        # Tüm FRD (truncate) — kolon spesifik kural yoksa
        prompt_parts.append(f"\nFONKSİYONEL İHTİYAÇ DOKÜMANI (özet):\n{context['functional_doc'][:1500]}")

    if context.get("ddl"):
        prompt_parts.append(f"\nDDL:\n{context['ddl']}")

    prompt_parts.append("""
─────────────────────────────────────────────────
YAZMA KURALLARI:
1. Kolon hangi tabloya ait, tablo ne işe yarar — bağlamı dahil et.
2. Düşük kardinaliteli kolonlarda TÜM bilinen değerleri "Değerler: X=..., Y=..." formatında yaz.
3. Varsa lookup tablosuna "LKP_XXX tablosundan gelir" şeklinde atıf yap.
4. FK varsa "XXX tablosunun birincil anahtarıdır" şeklinde belirt.
5. TOA / FRD'den çıkan iş kuralını bir cümleyle ekle (örn: "VALOR_TARIHI, ACILIS_TARIHI'nden küçük olamaz.").
6. Validation sorunu varsa uyarı olarak ekle.
7. Maksimum 3-4 cümle.
8. SADECE açıklamayı yaz — başka hiçbir şey ekleme.
─────────────────────────────────────────────────""")

    return "\n".join(prompt_parts)


def generate_description(table: dict, column: dict, context: dict, all_tables: list) -> str:
    """Claude API çağrısı yaparak açıklama üretir."""
    lookup_values = enrich_column_with_lookup(column, all_tables)
    prompt = build_prompt(table, column, context, lookup_values)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()


def run_generator(tables: list) -> list:
    """Tüm tablolar için açıklama üretir / zenginleştirir."""
    enriched = []

    for table in tables:
        print(f"\n📋 İşleniyor: {table['schema']}.{table['table_name']}")
        context = load_context(table["table_name"], table["schema"])

        doc_status = []
        if context.get("has_frd"):  doc_status.append("FRD ✅")
        else:                        doc_status.append("FRD ❌")
        if context.get("has_toa"):  doc_status.append("TOA ✅")
        else:                        doc_status.append("TOA ❌")
        if context.get("ddl"):      doc_status.append("DDL ✅")
        else:                        doc_status.append("DDL ❌")
        print(f"   Dokümanlar: {' | '.join(doc_status)}")

        enriched_table = dict(table)
        enriched_columns = []

        for col in table.get("columns", []):
            quality = col.get("description_quality", "")

            if quality in ("incomplete", "missing", "wrong", "english", "vague"):
                print(f"  ✏️  Üretiliyor: {col['column_name']} [{quality}]")

                # ── Fallback: açıklama tamamen yoksa kolon adından türet ──────
                if not col.get("description") or quality == "missing":
                    fallback = infer_description_from_col_name(
                        col["column_name"],
                        table.get("table_name", ""),
                        table.get("schema", "")
                    )
                    print(f"       → Fallback (kolon adından): {fallback}")
                    col = dict(col)
                    col.setdefault("description", fallback)

                try:
                    new_description = generate_description(table, col, context, tables)
                    enriched_col = dict(col)
                    enriched_col["original_description"] = col.get("original_description") or col.get("description")
                    enriched_col["description"] = new_description
                    enriched_col["description_quality"] = "generated"

                    # Doküman kaynaklarını işaretle
                    enriched_col["generated_with"] = {
                        "has_frd": context.get("has_frd", False),
                        "has_toa": context.get("has_toa", False),
                        "has_ddl": bool(context.get("ddl")),
                    }
                    enriched_columns.append(enriched_col)
                    print(f"       ✅ Üretildi: {new_description[:80]}...")

                except Exception as e:
                    print(f"  ❌ Hata: {e}")
                    enriched_columns.append(col)
            else:
                # İyi kalitede — original_description'ı sakla
                kept = dict(col)
                kept.setdefault("original_description", col.get("description"))
                print(f"  ✅ Mevcut açıklama yeterli: {col['column_name']}")
                enriched_columns.append(kept)

        enriched_table["columns"] = enriched_columns
        enriched.append(enriched_table)

    return enriched


if __name__ == "__main__":
    tables = load_json(DATA_DIR / "tables" / "synthetic_tables.json")
    enriched = run_generator(tables)

    out_path = DATA_DIR / "tables" / "enriched_tables.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Zenginleştirilmiş metadata kaydedildi: {out_path}")
