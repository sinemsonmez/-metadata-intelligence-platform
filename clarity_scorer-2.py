"""
Clarity Scorer — Bankacılık Sektörü Odaklı
-------------------------------------------
Kolon açıklamalarını 0-100 arasında puanlar.
Eşik değeri: 80 (üzeri OK, altı risk sinyali)

Puanlama heuristic pattern matching DEĞİL,
bankacılık sektörü anlam yeterliliğine dayanır:
  - Sektör bağlamı ve tablo rolü aktarılmış mı?
  - Düşük kardinaliteli kolonlarda değer aralığı açıklanmış mı?
  - FK / LKP referansı verilmiş mi?
  - İş kuralı varsa yansıtılmış mı?
  - Validation hatası açıklamada işaretlenmiş mi?
  - TOA / FRD notlarından çıkan kurallar kapsanmış mı?
"""

CLARITY_THRESHOLD = 80  # Bu değerin altı → risk var


# Bankacılık domaininde iş kuralı kritik olan kolonlar
BUSINESS_RULE_COLUMNS = {
    "VALOR_TARIHI", "ACILIS_TARIHI", "KAPANIS_TARIHI", "VADE_TARIHI",
    "FAIZ_ORANI", "KEFALET_TUTAR", "LIMIT_TUTAR", "BAKIYE",
    "RISK_SKOR", "RISK_SINIF", "SEGMENT_KOD", "GELIR_GRUBU",
    "HESAP_DURUM_KOD", "KRD_DURUM", "KRD_MUS_KOBI_TIP",
    "INT_SHK_A_30GCK_ADT_LM", "MUSTERI_NO", "SUBE_KOD",
}

# Türkçe bankacılık terim havuzu — bağlam kanıtı
BANKING_TERMS = [
    "hesap", "kredi", "müşteri", "şube", "bakiye", "faiz", "vade",
    "vadesiz", "vadeli", "iban", "döviz", "tl", "altın", "yatırım",
    "segment", "risk", "npl", "kobi", "teminat", "limit", "lookup",
    "lkp", "referans", "değer", "kod", "kodu", "tarih", "tutar",
    "açılış", "kapanış", "valör", "durum", "tip", "sınıf", "grup",
    "birincil anahtar", "yabancı anahtar", "fk", "pk", "tablosundan",
    "tablosunun", "tablosundaki", "ilişkilendirilmiş", "bağlantılı",
    "ticari", "bireysel", "tmmob", "banka", "bankamız",
]

ENGLISH_INDICATORS = [
    "the ", "is a", "this ", "which ", "where ", "that ", "account",
    "status", "code ", "date ", "number", "active", "closed",
]


def score_description(description: str | None, column: dict) -> dict:
    """
    Bankacılık sektörü odaklı clarity skoru.

    Returns dict:
      score         : int 0-100
      threshold     : 80
      verdict       : "OK" | "AT_RISK" | "FAIL"
      deductions    : [(reason, pts), ...]
      bonuses       : [(reason, pts), ...]
    """
    deductions = []
    bonuses = []

    col_name     = column.get("column_name", "")
    distinct     = column.get("distinct_count")
    has_lookup   = column.get("has_lookup", False)
    lookup_table = column.get("lookup_table")
    known_values = column.get("known_values", [])
    val_issue    = column.get("validation_issue")
    fk_table     = column.get("fk_table")
    cardinality  = column.get("cardinality", "")
    quality      = column.get("description_quality", "")
    notes        = column.get("notes", "") or ""

    # ── Açıklama yok ──────────────────────────────────────────────────────────
    if not description or not description.strip():
        deductions.append(("Açıklama tamamen eksik", 100))
        return _build_result(0, deductions, bonuses)

    desc       = description.strip()
    desc_lower = desc.lower()
    words      = desc.split()

    # ── Dil Kontrolü ──────────────────────────────────────────────────────────
    en_count = sum(1 for e in ENGLISH_INDICATORS if e in desc_lower)
    if en_count >= 3:
        deductions.append(("Türkçe bankacılık şemasında İngilizce açıklama", 25))
    elif en_count >= 1 and quality == "english":
        deductions.append(("Kısmen İngilizce — sektörel bağlam kaybolmuş", 15))

    # ── Bankacılık bağlamı ────────────────────────────────────────────────────
    banking_hit = sum(1 for t in BANKING_TERMS if t in desc_lower)
    if banking_hit == 0:
        deductions.append(("Bankacılık / iş domain bağlamı hiç yok", 20))
    elif banking_hit == 1:
        deductions.append(("Sektör bağlamı zayıf — yalnızca tek terim", 10))
    else:
        bonuses.append(("Bankacılık terminolojisi kullanılmış", 5))

    # ── Tablo bağlamı ─────────────────────────────────────────────────────────
    has_table_ctx = any(t in desc_lower for t in [
        "tablodaki", "tablosundaki", "tablosundan", "tablosunun",
        "tablosuna", "tabloda", "içindeki",
    ])
    if has_table_ctx:
        bonuses.append(("Tablo bağlamı açıklamaya dahil edilmiş", 5))

    # ── Sadece kolon adını tekrarlamak ────────────────────────────────────────
    col_norm = col_name.lower().replace("_", " ")
    if col_norm in desc_lower and len(words) <= 4:
        deductions.append(("Açıklama sadece kolon adını tekrarlıyor", 30))

    # ── Düşük kardinalite: değerler veya LKP açıklanmış mı? ──────────────────
    if distinct is not None and int(distinct) < 20:
        if has_lookup and lookup_table:
            lkp_lower = lookup_table.lower()
            if lkp_lower in desc_lower or "lkp" in desc_lower or "lookup" in desc_lower:
                bonuses.append(("Lookup tablosuna doğru atıf yapılmış", 10))
            else:
                deductions.append(("Lookup tablosu var ama açıklamada referans yok", 10))
        else:
            values_mentioned = sum(1 for v in known_values if str(v) in desc)
            if values_mentioned == 0:
                deductions.append((
                    f"Düşük kardinalite ({distinct} distinct) — bilinen değerler açıklanmamış, LKP da yok",
                    20
                ))
            elif known_values and values_mentioned < len(known_values):
                deductions.append(("Değerlerin bir kısmı eksik", 8))
            elif known_values:
                bonuses.append(("Tüm olası değerler dokümante edilmiş", 10))
    elif cardinality == "low" and not has_lookup:
        deductions.append(("Düşük kardinalite — değer aralığı belirtilmemiş", 15))

    # ── FK / referans tablosu ─────────────────────────────────────────────────
    if fk_table:
        if fk_table.lower() in desc_lower or "birincil anahtar" in desc_lower or "fk" in desc_lower:
            bonuses.append(("FK referans tablosu açıklamada belirtilmiş", 8))
        else:
            deductions.append(("FK ilişkisi var ama açıklamada referans verilmemiş", 10))

    # ── Validation hatası ─────────────────────────────────────────────────────
    if val_issue:
        deductions.append(("Validation hatası var ama açıklama bunu yansıtmıyor", 15))

    # ── Kritik iş kuralı kolonları — derinlik ────────────────────────────────
    if col_name in BUSINESS_RULE_COLUMNS:
        if len(words) < 8:
            deductions.append(("Kritik bankacılık kolonu için açıklama çok kısa", 15))
        elif len(words) >= 15:
            bonuses.append(("Kritik kolon için detaylı açıklama mevcut", 5))

    # ── Özel bankacılık iş kuralı kontrolleri ─────────────────────────────────
    if col_name == "VALOR_TARIHI" and "acilis" not in desc_lower:
        deductions.append(("VALOR_TARIHI'nde ACILIS_TARIHI ilişkisi belirtilmemiş", 10))

    if col_name == "ACILIS_TARIHI" and "valor" not in desc_lower:
        deductions.append(("ACILIS_TARIHI'nde valör bağlantısı belirtilmemiş", 10))

    if col_name.startswith("INT_") and "30" in col_name:
        if "30" not in desc and "otuz" not in desc_lower:
            deductions.append(("Kolon adındaki '30 gün' periyodu açıklamada doğrulanmamış", 15))
        if "60" in desc:
            deductions.append(("Açıklamada '60 gün' yazıyor ama kolon '30 gün' — KRİTİK MISMATCH", 25))

    if col_name == "RISK_SKOR":
        if "0" not in desc or "100" not in desc:
            deductions.append(("Risk skoru için değer aralığı (0-100) açıklanmamış", 10))

    # ── Belirsiz genel ifade ──────────────────────────────────────────────────
    vague = ["alandır.", "tutulur.", "bilgisidir.", "kodudur.", "tarihidir."]
    if any(p in desc_lower for p in vague) and len(words) <= 5:
        deductions.append(("Belirsiz genel ifade — sektörel içerik yok", 15))

    # ── Metadata notlarından iş kuralı kapsanmış mı? ─────────────────────────
    if notes.strip():
        notes_sentences = [s.strip() for s in notes.split(".") if len(s.strip()) > 8]
        covered = any(ns[:15].lower() in desc_lower for ns in notes_sentences)
        if not covered:
            deductions.append(("Metadata notlarındaki iş kuralı açıklamada yansıtılmamış", 8))

    # ── Hesapla ────────────────────────────────────────────────────────────────
    total_ded = sum(p for _, p in deductions)
    total_bon = sum(p for _, p in bonuses)
    score = max(0, min(100, 100 - total_ded + total_bon))

    return _build_result(score, deductions, bonuses)


def _build_result(score: int, deductions: list, bonuses: list) -> dict:
    if score >= CLARITY_THRESHOLD:
        verdict = "OK"
    elif score >= 50:
        verdict = "AT_RISK"
    else:
        verdict = "FAIL"

    return {
        "score": score,
        "threshold": CLARITY_THRESHOLD,
        "verdict": verdict,
        "deductions": deductions,
        "bonuses": bonuses,
    }


def score_all(tables: list) -> dict:
    """
    Tüm tablolar için clarity skoru hesaplar.
    Her kolon için detaylı terminal çıktısı üretir.
    Returns per-table ve özet dict.
    """
    results = {}
    all_scores = []
    risk_count = 0

    print("\n" + "═" * 65)
    print("  CLARITY SCORER — Bankacılık Sektörü Yeterlilik Değerlendirmesi")
    print(f"  Eşik Değeri: {CLARITY_THRESHOLD}/100  |  Altı → Risk Sinyali")
    print("═" * 65)

    for table in tables:
        table_key = f"{table['schema']}.{table['table_name']}"
        col_results = {}

        print(f"\n📋 TABLO: {table_key}")
        print(f"   {'─' * 55}")

        for col in table.get("columns", []):
            col["_table_name"] = table.get("table_name", "")
            result = score_description(col.get("description"), col)
            score  = result["score"]

            col["clarity_score"]   = score
            col["clarity_verdict"] = result["verdict"]
            col_results[col["column_name"]] = result
            all_scores.append(score)

            if score < CLARITY_THRESHOLD:
                risk_count += 1

            icon = "✅" if result["verdict"] == "OK" else ("⚠️ " if result["verdict"] == "AT_RISK" else "🔴")
            print(f"   {icon} {col['column_name']:<35}  {score:>3}/100  [{result['verdict']}]")
            for reason, pts in result["deductions"]:
                print(f"        ↳ -{pts:>2}pt  {reason}")
            for reason, pts in result["bonuses"]:
                print(f"        ↳ +{pts:>2}pt  {reason}")

        avg = round(sum(r["score"] for r in col_results.values()) / len(col_results), 1) if col_results else 0
        results[table_key] = {"average_clarity": avg, "columns": col_results}
        print(f"\n   📊 Tablo ortalaması: {avg:.1f}/100")

    # ── Genel özet ─────────────────────────────────────────────────────────────
    if all_scores:
        avg_all    = round(sum(all_scores) / len(all_scores), 1)
        risk_ratio = round(risk_count / len(all_scores) * 100, 1)

        print("\n" + "═" * 65)
        print("  GENEL ÖZET")
        print(f"  Toplam kolon         : {len(all_scores)}")
        print(f"  Genel ortalama skor  : {avg_all}/100")
        print(f"  Eşik altı (< {CLARITY_THRESHOLD}) kolon : {risk_count} / {len(all_scores)}")
        print(f"  Risk oranı           : %{risk_ratio}")
        print("═" * 65)

        results["__summary__"] = {
            "total_columns": len(all_scores),
            "average_score": avg_all,
            "below_threshold": risk_count,
            "risk_ratio_pct": risk_ratio,
            "threshold": CLARITY_THRESHOLD,
        }

    return results


if __name__ == "__main__":
    import json
    from pathlib import Path

    data_path = Path(__file__).parent.parent / "data" / "tables" / "enriched_tables.json"
    with open(data_path, "r", encoding="utf-8") as f:
        tables = json.load(f)

    scores = score_all(tables)
    print(json.dumps(scores, indent=2, ensure_ascii=False))
