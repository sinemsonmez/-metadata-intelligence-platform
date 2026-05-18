"""
Critic Agent — Bankacılık Sektörü Yeterlilik Değerlendirmesi
-------------------------------------------------------------
Üretilen/mevcut kolon açıklamalarını değerlendirir.

Değerlendirme kriterleri:
  - Sektörel yeterlilik (bankacılık terminolojisi, domain bağlamı)
  - Completeness (tablo bağlamı, değer aralığı, FK/LKP referansı)
  - Accuracy (DDL, lookup, FRD ile çelişki var mı?)
  - İş kuralı kapsımı (TOA / FRD kuralları yansıtılmış mı?)
  - Dil tutarlılığı (Türkçe şema → Türkçe açıklama)

Çıktı: 0-100 arası overall_score
Eşik: 80 — altındaki kolonlar yeniden üretim için işaretlenir.
"""

import json
import os
from pathlib import Path
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SCORE_THRESHOLD = 80         # Altındaki → needs_regeneration = True
CARDINALITY_THRESHOLD = 100


def evaluate_column(table: dict, column: dict) -> dict:
    """
    Claude API ile kolon açıklamasını değerlendirir.
    Bankacılık sektörü yeterlilik odaklı.
    0-100 arası skor döner.
    """
    known_values_str = ""
    if column.get("known_values"):
        kv = column["known_values"]
        known_values_str = ", ".join(str(v) for v in kv)

    doc_note = ""
    if not table.get("has_functional_doc"):
        doc_note += "FRD MEVCUT DEĞİL. "
    if not table.get("has_toa_doc"):
        doc_note += "TOA MEVCUT DEĞİL. "

    prompt = f"""Sen bankacılık veri kalitesi uzmanısın. Aşağıdaki kolon açıklamasını değerlendir.

TABLO: {table['schema']}.{table['table_name']}
TABLO AÇIKLAMASI: {table.get('description', 'Yok')}
DOKÜMAN DURUMU: {doc_note if doc_note else 'FRD ve TOA mevcut'}

KOLON: {column['column_name']}
VERİ TİPİ: {column['data_type']}
MEVCUT AÇIKLAMA: {column.get('description', '(boş)')}
ORİJİNAL AÇIKLAMA: {column.get('original_description', '(yok)')}
KARDİNALİTE: {column.get('cardinality', 'bilinmiyor')}
DISTINCT SAYISI: {column.get('distinct_count', 'bilinmiyor')}
LOOKUP TABLOSU: {column.get('lookup_table', 'Yok')}
BİLİNEN DEĞERLER: {known_values_str or 'Yok'}
VALİDASYON SORUNU: {column.get('validation_issue', 'Yok')}
FK REFERANSI: {column.get('fk_table', 'Yok')}
NOTLAR: {column.get('notes', 'Yok')}

DEĞERLENDİRME KRİTERLERİ (toplam 100 puan):
1. Bankacılık domain bağlamı (25pt) — Tablo rolü ve sektörel terimler var mı?
2. Değer aralığı / LKP kapsımı (20pt) — Düşük kardinaliteli kolonlarda değerler açıklanmış mı?
3. Referans bütünlüğü (15pt) — FK / LKP tablosuna atıf var mı?
4. İş kuralı (20pt) — Varsa validasyon uyarısı, tarih kısıtı, iş kuralı yansıtılmış mı?
5. Dil tutarlılığı (10pt) — Türkçe şemada Türkçe açıklama mı?
6. Yeterli detay (10pt) — Teknik olmayan okuyucu anlayabilir mi?

SADECE JSON formatında yanıt ver, başka bir şey yazma:
{{
  "domain_context_score": 0-25,
  "value_range_score": 0-20,
  "reference_integrity_score": 0-15,
  "business_rule_score": 0-20,
  "language_score": 0-10,
  "detail_score": 0-10,
  "overall_score": 0-100,
  "issues": ["sorun1", "sorun2"],
  "feedback": "Kısa iyileştirme önerisi (max 2 cümle)",
  "needs_regeneration": true | false
}}

needs_regeneration: overall_score < 80 ise true."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()

    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        # Ensure overall_score consistency
        if "overall_score" not in result:
            result["overall_score"] = sum([
                result.get("domain_context_score", 0),
                result.get("value_range_score", 0),
                result.get("reference_integrity_score", 0),
                result.get("business_rule_score", 0),
                result.get("language_score", 0),
                result.get("detail_score", 0),
            ])
        return result
    except json.JSONDecodeError:
        return {
            "overall_score": 0,
            "issues": ["Değerlendirme parse edilemedi"],
            "feedback": raw[:200],
            "needs_regeneration": True,
        }


def check_lookup_gaps(column: dict) -> list:
    """Kural bazlı: düşük kardinalite + lookup yok → sorun."""
    issues = []
    distinct = column.get("distinct_count")
    has_lookup = column.get("has_lookup", False)
    if distinct is not None and int(distinct) < CARDINALITY_THRESHOLD and not has_lookup:
        issues.append(
            f"Düşük kardinalite ({distinct} distinct değer) ama LKP tablosu tanımlı değil. "
            f"Bilinen değerler: {column.get('known_values', 'bilinmiyor')}"
        )
    return issues


def check_value_validation(column: dict) -> list:
    """Validation mismatch varsa işaretle."""
    issues = []
    if column.get("validation_issue"):
        issues.append(f"VALUE MISMATCH: {column['validation_issue']}")
    return issues


def run_critic(enriched_tables: list) -> list:
    """Tüm tablolar / kolonlar için değerlendirme çalıştırır."""
    results = []

    print("\n" + "═" * 65)
    print("  CRITIC AGENT — Bankacılık Sektörü Yeterlilik Değerlendirmesi")
    print(f"  Yeniden Üretim Eşiği: {SCORE_THRESHOLD}/100")
    print("═" * 65)

    for table in enriched_tables:
        table_key = f"{table['schema']}.{table['table_name']}"
        print(f"\n📋 {table_key}")

        table_result = {
            "table_name": table["table_name"],
            "schema": table["schema"],
            "has_frd": table.get("has_functional_doc", False),
            "has_toa": table.get("has_toa_doc", False),
            "column_evaluations": [],
        }

        for col in table.get("columns", []):
            print(f"   🔍 Değerlendiriliyor: {col['column_name']}")

            lookup_issues     = check_lookup_gaps(col)
            validation_issues = check_value_validation(col)

            try:
                eval_result = evaluate_column(table, col)
            except Exception as e:
                print(f"   ❌ Hata: {e}")
                eval_result = {
                    "overall_score": 0,
                    "issues": [str(e)],
                    "feedback": "Değerlendirme başarısız",
                    "needs_regeneration": True,
                }

            # Kural bazlı sorunları birleştir
            all_issues = eval_result.get("issues", []) + lookup_issues + validation_issues
            eval_result["issues"] = all_issues

            # Kural bazlı sorun varsa skoru düşür
            if lookup_issues or validation_issues:
                penalty = len(lookup_issues) * 15 + len(validation_issues) * 20
                eval_result["overall_score"] = max(0, eval_result.get("overall_score", 0) - penalty)
                eval_result["needs_regeneration"] = True

            score = eval_result.get("overall_score", 0)

            # Risk bandı
            if score >= 80:
                band = "DÜŞÜK"
                icon = "🟢"
            elif score >= 50:
                band = "ORTA"
                icon = "🟡"
            else:
                band = "YÜKSEK"
                icon = "🔴"

            eval_result["risk_band"] = band

            col_result = {
                "column_name": col["column_name"],
                "original_description": col.get("original_description"),
                "description": col.get("description"),
                **eval_result,
            }
            table_result["column_evaluations"].append(col_result)

            print(f"   {icon} Skor: {score}/100  [{band} risk]"
                  f"  {'→ Yeniden üretilecek' if eval_result.get('needs_regeneration') else ''}")
            for issue in all_issues:
                print(f"      ⚠ {issue}")
            if eval_result.get("feedback"):
                print(f"      💬 {eval_result['feedback']}")

        results.append(table_result)

    return results


if __name__ == "__main__":
    data_dir = Path(__file__).parent.parent / "data" / "tables"

    enriched_path = data_dir / "enriched_tables.json"
    if not enriched_path.exists():
        print("⚠️  enriched_tables.json bulunamadı. Önce generator_agent.py'yi çalıştırın.")
        exit(1)

    with open(enriched_path, "r", encoding="utf-8") as f:
        enriched_tables = json.load(f)

    results = run_critic(enriched_tables)

    out_path = data_dir / "critic_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Critic sonuçları kaydedildi: {out_path}")
