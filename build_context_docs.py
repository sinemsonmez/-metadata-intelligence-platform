"""Sentetik tablolar için kısmi FRD/TOA dokümanları üretir.

Yalnızca synthetic_tables.json içinde has_functional_doc / has_toa_doc
bayrağı true olan tablolar için dosya oluşturur. Mevcut elle yazılmış
dokümanların üzerine yazmaz.

Çalıştır: python build_context_docs.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _col_section(col: dict) -> str:
    name = col["column_name"]
    dtype = col.get("data_type", "")
    lines = [f"### {name}", f"Veri tipi: {dtype}."]
    if col.get("lookup_table"):
        lines.append(f"Lookup referansı: {col['lookup_table']}.")
    if col.get("known_values"):
        lines.append(f"Bilinen değerler: {col['known_values']}.")
    if col.get("validation_issue"):
        lines.append(f"⚠️ Veri kalitesi notu: {col['validation_issue']}")
    if col.get("notes"):
        lines.append(col["notes"])
    desc = col.get("description")
    if desc:
        lines.append(desc)
    return "\n".join(lines) + "\n"


def build_frd(table: dict) -> str:
    schema = table["schema"]
    name = table["table_name"]
    model = table.get("conceptual_model", "")
    desc = table.get("description") or "Tablo açıklaması mevcut değil."
    cols = "\n".join(_col_section(c) for c in table.get("columns", []))
    return f"""# Fonksiyonel İhtiyaç Dokümanı: {name}

**Doküman No:** FRD-{schema[:4]}-{name[:6]}  
**Tablo:** {schema}.{name}  
**Kavramsal Model:** {model}  
**Durum:** Sentetik örnek (otomatik üretim)

---

## 1. Genel Tanım

{desc}

## 2. Kolon Açıklamaları ve İş Kuralları

{cols}

## 3. Veri Kalitesi Kuralları

- Birincil anahtar kolonları NULL olamaz.
- Lookup referanslı kolonlar ilgili LKP tablosu ile tutarlı olmalıdır.
- Düşük kardinaliteli kod kolonları için değer aralığı dokümante edilmelidir.
"""


def build_toa(table: dict) -> str:
    schema = table["schema"]
    name = table["table_name"]
    partitioned = table.get("is_partitioned", False)
    part_col = table.get("partition_column", "—")
    return f"""# TOA Dokümanı: {name}

**Doküman No:** TOA-{schema[:4]}-{name[:6]}  
**Tablo:** {schema}.{name}  
**Durum:** Sentetik örnek (otomatik üretim)

---

## TOA (Teknik Operasyonel Analiz)

### Boyut Analizi
- Tahmini kayıt sayısı: sentetik ortam örneği
- Partition: {"Evet — " + part_col if partitioned else "Hayır"}

### Örnek Analiz Sorguları

```sql
SELECT COUNT(*) FROM {schema}.{name};
```

```sql
SELECT column_name, data_type
FROM all_tab_columns
WHERE owner = '{schema}' AND table_name = '{name}';
```
"""


def main() -> None:
    tables_path = ROOT / "synthetic_tables.json"
    tables = json.loads(tables_path.read_text(encoding="utf-8"))

    frd_created = toa_created = 0
    for table in tables:
        name = table["table_name"]
        if table.get("has_functional_doc"):
            path = ROOT / f"FRD_{name}.md"
            if not path.exists():
                path.write_text(build_frd(table), encoding="utf-8")
                frd_created += 1
                print(f"  FRD -> {path.name}")
        if table.get("has_toa_doc"):
            path = ROOT / f"TOA_{name}.md"
            if not path.exists():
                path.write_text(build_toa(table), encoding="utf-8")
                toa_created += 1
                print(f"  TOA -> {path.name}")

    print(f"OK: {frd_created} FRD, {toa_created} TOA oluşturuldu (mevcut dosyalar korundu)")


if __name__ == "__main__":
    main()
