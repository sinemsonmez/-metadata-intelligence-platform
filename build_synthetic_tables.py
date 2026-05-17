"""Tek seferlik: 20 tabloluk synthetic_tables.json üretir. Çalıştır: python build_synthetic_tables.py"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

QUALITIES = ("complete", "incomplete", "missing", "wrong", "english", "vague")

SCHEMAS = {
    "CORE_BANKING": {
        "tables": [
            ("XXX_HESAP", "Account", "Banka müşterilerine ait hesap bilgilerini içeren ana tablodur."),
            ("XXX_MUSTERI", "Customer", "Müşteri ana verisi; kimlik ve iletişim bilgilerini tutar."),
            ("XXX_ISLEM", "Transaction", "Hesap hareketleri ve işlem kayıtları."),
            ("XXX_KART", "Card", "Debit/kredi kartı ana verisi."),
            ("LKP_HESAP_TIP", "Lookup", "Hesap tipi lookup tablosu."),
            ("LKP_SUBE", "Lookup", "Şube kodları lookup tablosu."),
            ("LKP_DOVIZ", "Lookup", "Döviz cinsi lookup tablosu."),
        ],
    },
    "CREDIT": {
        "tables": [
            ("KRD_MUS_KREDI", "Credit", "Müşteri kredi ana tablosu; kullandırım ve durum bilgisi."),
            ("KRD_TEMINAT", "Collateral", "Kredi teminat ve rehin kayıtları."),
            ("KRD_ODEME_PLAN", "PaymentPlan", "Kredi taksit ve ödeme planı."),
            ("KRD_BASVURU", "Application", "Kredi başvuru süreci verileri."),
            ("KRD_GARANTI", "Guarantee", "Kefalet ve garanti ilişkileri."),
        ],
    },
    "CRM": {
        "tables": [
            ("MUS_SEGMENTASYON", "Customer", "Müşteri segmentasyon ve gelir grubu."),
            ("LKP_SEGMENT", "Lookup", "Segment kodları lookup."),
            ("KAMPANYA_HEDEF", "Campaign", "Kampanya hedef müşteri listesi."),
            ("MUS_ILETISIM", "Contact", "Müşteri iletişim kanalı ve tercihleri."),
        ],
    },
    "RISK": {
        "tables": [
            ("RISK_IZLEME", "Risk", "Müşteri bazlı risk izleme ve skor."),
            ("RISK_LIMIT", "RiskLimit", "Limit tanım ve kullanım özeti."),
            ("RISK_RAPOR", "RiskReport", "Regülasyon raporlama çıktıları."),
            ("RISK_AML", "AML", "Kara para ve uyum izleme kayıtları."),
        ],
    },
}

# Mevcut 5 tablonun kolon şablonları (korunur)
PRESERVE_TABLES = {"XXX_HESAP", "KRD_MUS_KREDI", "MUS_SEGMENTASYON", "LKP_HESAP_TIP", "RISK_IZLEME"}

COLUMN_TEMPLATES = [
    ("{pfx}_NO", "VARCHAR(20)", 0, "high", False),
    ("{pfx}_TARIH", "DATE", 1, "high", False),
    ("{pfx}_KOD", "NUMBER(2)", 2, "low", True),
    ("{pfx}_DURUM", "NUMBER(1)", 3, "low", False),
    ("MUSTERI_NO", "NUMBER(10)", 4, "high", False),
]

DESCRIPTIONS = {
    "complete": lambda n: f"{n} alanı; iş kurallarına uygun tam açıklama.",
    "incomplete": lambda n: f"{n} bilgisidir.",
    "missing": lambda n: None,
    "wrong": lambda n: f"{n} — last 90 days aggregate (column name implies 30 days).",
    "english": lambda n: f"{n} code value.",
    "vague": lambda n: f"{n} için tutulan alan.",
}


def _col(table_name: str, col_name: str, data_type: str, qidx: int, card: str, has_lkp: bool) -> dict:
    quality = QUALITIES[qidx % len(QUALITIES)]
    if quality == "missing":
        desc = None
    else:
        desc = DESCRIPTIONS[quality](col_name)
    col: dict = {
        "column_name": col_name,
        "data_type": data_type,
        "description": desc,
        "description_quality": quality,
        "cardinality": card,
        "has_lookup": has_lkp,
        "nullable": quality in ("missing", "vague"),
    }
    if card == "low":
        col["distinct_count"] = 3 + (qidx % 5)
        col["known_values"] = [0, 1, 2] if "DURUM" in col_name or "KOD" in col_name else ["A", "B", "C"]
    if has_lkp:
        col["lookup_table"] = f"LKP_{table_name.split('_')[-1][:6]}"
    if quality == "wrong":
        col["validation_issue"] = "Documented range does not match production samples."
    if quality == "english" and col_name.endswith("_DURUM"):
        col["actual_values_in_db"] = [0, 1, 2, 3]
    return col


def _build_table(schema: str, table_name: str, model: str, desc: str, tidx: int) -> dict:
    pfx = table_name.split("_")[-1][:4].upper() if not table_name.startswith("LKP") else "KOD"
    if table_name.startswith("LKP"):
        cols = [
            _col(table_name, "KOD", "NUMBER(4)", tidx, "low", False),
            _col(table_name, "ACIKLAMA", "VARCHAR(100)", tidx + 1, "low", False),
        ]
    else:
        cols = []
        for i, (pat, dtype, qoff, card, lkp) in enumerate(COLUMN_TEMPLATES[:4]):
            name = pat.format(pfx=pfx) if "{pfx}" in pat else pat
            if name == f"{pfx}_NO" and table_name == "XXX_MUSTERI":
                name = "MUSTERI_NO"
            cols.append(_col(table_name, name, dtype, tidx + qoff + i, card, lkp and i == 2))
        if "MUSTERI" not in table_name:
            cols.append(_col(table_name, "MUSTERI_NO", "NUMBER(10)", tidx + 3, "high", False))

    return {
        "table_name": table_name,
        "schema": schema,
        "conceptual_model": model,
        "description": desc if tidx % 4 != 2 else None,
        "description_quality": "complete" if tidx % 4 != 2 else "missing",
        "has_functional_doc": tidx % 3 == 0,
        "has_toa_doc": tidx % 5 == 0,
        "has_ddl": table_name not in ("MUS_SEGMENTASYON", "MUS_ILETISIM", "KAMPANYA_HEDEF"),
        "is_partitioned": table_name in ("KRD_MUS_KREDI", "RISK_IZLEME", "XXX_ISLEM", "RISK_RAPOR"),
        **(
            {"partition_column": "ISLEM_TARIHI", "partition_type": "RANGE"}
            if table_name in ("KRD_MUS_KREDI", "XXX_ISLEM")
            else {"partition_column": "RAPOR_TARIHI", "partition_type": "RANGE"}
            if table_name in ("RISK_IZLEME", "RISK_RAPOR")
            else {}
        ),
        "columns": cols,
    }


def main() -> None:
    existing_path = ROOT / "synthetic_tables.json"
    preserved: dict[str, dict] = {}
    if existing_path.exists():
        for t in json.loads(existing_path.read_text(encoding="utf-8")):
            if t["table_name"] in PRESERVE_TABLES:
                preserved[t["table_name"]] = t

    tables: list[dict] = []
    tidx = 0
    for schema, info in SCHEMAS.items():
        for table_name, model, desc in info["tables"]:
            if table_name in preserved:
                tables.append(preserved[table_name])
            else:
                tables.append(_build_table(schema, table_name, model, desc, tidx))
            tidx += 1

    assert len(tables) == 20, f"Beklenen 20 tablo, bulunan: {len(tables)}"

    existing_path.write_text(
        json.dumps(tables, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    schema_list = {
        "schemas": [],
        "conceptual_model": {
            "entities": [
                {"entity": "Customer", "turkish": "Müşteri", "tables": ["XXX_MUSTERI", "MUS_SEGMENTASYON", "MUS_ILETISIM"], "key_attribute": "MUSTERI_NO"},
                {"entity": "Account", "turkish": "Hesap", "tables": ["XXX_HESAP", "XXX_ISLEM"], "key_attribute": "HESAP_NO", "parent_entity": "Customer"},
                {"entity": "Credit", "turkish": "Kredi", "tables": ["KRD_MUS_KREDI", "KRD_BASVURU", "KRD_TEMINAT"], "key_attribute": "KRD_NO", "parent_entity": "Customer"},
                {"entity": "Risk", "turkish": "Risk", "tables": ["RISK_IZLEME", "RISK_LIMIT", "RISK_AML"], "key_attribute": "MUSTERI_NO", "parent_entity": "Customer"},
            ]
        },
    }
    for schema, info in SCHEMAS.items():
        schema_list["schemas"].append({
            "schema_name": schema,
            "description": f"{schema} şeması — sentetik metadata örnekleri.",
            "owner": f"{schema.split('_')[0]}_TEAM",
            "tables": [t[0] for t in info["tables"]],
        })

    (ROOT / "schema_list.json").write_text(
        json.dumps(schema_list, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"OK: {len(tables)} tablo -> synthetic_tables.json")
    print("OK: schema_list.json guncellendi")


if __name__ == "__main__":
    main()
