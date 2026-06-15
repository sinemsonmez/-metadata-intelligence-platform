"""
Risk Classifier — Skor Bazlı Risk Değerlendirmesi
--------------------------------------------------
HIGH_RISK / LOW_RISK etiketleme YERİNE:
  - 0-100 arası risk_score üretir (yüksek = daha riskli)
  - risk_ratio_pct: tüm kolonlar arasındaki risk oranı
  - Her kolon için neden bu skoru aldığını açıklar
  - Eşik 80 (clarity_score < 80 → riskli)

Terminal'den de UI'dan da okunabilir detay çıktısı verir.
"""

from clarity_scorer import CLARITY_THRESHOLD

CARDINALITY_THRESHOLD = 100


def calculate_risk_score(column: dict) -> dict:
    """
    Kolon için 0-100 arası risk skoru hesaplar.
    Yüksek risk_score → daha fazla dikkat gerektirir.

    Faktörler:
      - Açıklama kalitesi (description_quality)
      - Clarity score (bankacılık yeterliliği)
      - Validation hatası
      - Lookup eksikliği (düşük kardinalite)
      - Kritik iş kuralı kolonu olup olmadığı
      - Dil tutarsızlığı
      - Functional doc / TOA eksikliği (tablo bazlı)
    """
    risk_score  = 0
    risk_factors = []

    quality    = column.get("description_quality", "")
    val_issue  = column.get("validation_issue")
    distinct   = column.get("distinct_count")
    has_lookup = column.get("has_lookup", False)
    clarity    = column.get("clarity_score")  # varsa clarity scorer'dan gelir
    col_name   = column.get("column_name", "")

    # ── Açıklama kalitesi ──────────────────────────────────────────────────────
    quality_penalty = {
        "missing":    40,
        "wrong":      35,
        "english":    25,
        "vague":      20,
        "incomplete": 15,
        "complete":    0,
        "generated":   0,
    }
    pen = quality_penalty.get(quality, 10)
    if pen > 0:
        risk_score += pen
        risk_factors.append({"factor": f"Açıklama kalitesi: '{quality}'", "penalty": pen})

    # ── Clarity skoru düşükse ─────────────────────────────────────────────────
    if clarity is not None:
        if clarity < 40:
            pen = 30
            risk_score += pen
            risk_factors.append({"factor": f"Clarity skoru çok düşük: {clarity}/100", "penalty": pen})
        elif clarity < CLARITY_THRESHOLD:
            pen = int((CLARITY_THRESHOLD - clarity) * 0.5)
            risk_score += pen
            risk_factors.append({"factor": f"Clarity skoru eşiğin altında: {clarity}/100 (eşik {CLARITY_THRESHOLD})", "penalty": pen})

    # ── Validation hatası ─────────────────────────────────────────────────────
    if val_issue:
        pen = 25
        risk_score += pen
        risk_factors.append({"factor": f"Validation hatası: {val_issue}", "penalty": pen})

    # ── Lookup eksikliği ──────────────────────────────────────────────────────
    if distinct is not None and int(distinct) < CARDINALITY_THRESHOLD and not has_lookup:
        pen = 20
        risk_score += pen
        risk_factors.append({
            "factor": f"Düşük kardinalite ({distinct} distinct) ama LKP tablosu yok",
            "penalty": pen
        })

    # ── Dil tutarsızlığı ──────────────────────────────────────────────────────
    if quality == "english":
        pen = 10  # zaten yukarıda 25 aldı, ek ceza
        risk_score += pen
        risk_factors.append({"factor": "Türkçe şemada İngilizce açıklama — dil tutarsızlığı", "penalty": pen})

    # ── Kritik kolonlar ───────────────────────────────────────────────────────
    from clarity_scorer import BUSINESS_RULE_COLUMNS
    if col_name in BUSINESS_RULE_COLUMNS and (clarity is None or clarity < CLARITY_THRESHOLD):
        pen = 10
        risk_score += pen
        risk_factors.append({"factor": "Kritik bankacılık kolonu — yeterli açıklama yok", "penalty": pen})

    # ── Normalize ─────────────────────────────────────────────────────────────
    risk_score = min(100, risk_score)

    # ── Risk seviyesi etiketi (bilgi amaçlı, eşik değil) ─────────────────────
    if risk_score >= 60:
        risk_band = "YÜKSEK"
    elif risk_score >= 30:
        risk_band = "ORTA"
    else:
        risk_band = "DÜŞÜK"

    return {
        "risk_score": risk_score,
        "risk_band": risk_band,
        "risk_factors": risk_factors,
    }


def classify_all_risks(tables: list) -> dict:
    """
    Tüm tablolar/kolonlar için risk skoru üretir.
    Terminal çıktısı verir, dashboard için dict döner.
    """
    report = {
        "columns": [],
        "summary": {},
        "risk_distribution": {},
    }

    all_risk_scores = []

    print("\n" + "═" * 65)
    print("  RISK CLASSIFIER — Skor Bazlı Değerlendirme")
    print("═" * 65)

    for table in tables:
        table_key = f"{table['schema']}.{table['table_name']}"
        print(f"\n📋 {table_key}")
        print(f"   {'─' * 55}")

        for col in table.get("columns", []):
            result   = calculate_risk_score(col)
            rs       = result["risk_score"]
            band     = result["risk_band"]
            factors  = result["risk_factors"]

            col["risk_score"] = rs
            col["risk_band"]  = band
            col["risk_factors"] = factors
            all_risk_scores.append(rs)

            icon = "🔴" if band == "YÜKSEK" else ("🟡" if band == "ORTA" else "🟢")
            print(f"   {icon} {col['column_name']:<35}  risk={rs:>3}/100  [{band}]")
            for f in factors:
                print(f"        ↳ +{f['penalty']:>2}pt  {f['factor']}")

            entry = {
                "table": table_key,
                "column": col["column_name"],
                "risk_score": rs,
                "risk_band": band,
                "risk_factors": [f["factor"] for f in factors],
                "clarity_score": col.get("clarity_score"),
                "description": col.get("description", ""),
                "original_description": col.get("original_description"),
                "issues": col.get("issues", []),
                "validation_issue": col.get("validation_issue"),
            }
            report["columns"].append(entry)

    # ── Dağılım hesapla ────────────────────────────────────────────────────────
    n = len(all_risk_scores)
    if n:
        yuksek  = sum(1 for s in all_risk_scores if s >= 60)
        orta    = sum(1 for s in all_risk_scores if 30 <= s < 60)
        dusuk   = sum(1 for s in all_risk_scores if s < 30)
        avg_r   = round(sum(all_risk_scores) / n, 1)

        report["summary"] = {
            "total_columns": n,
            "avg_risk_score": avg_r,
            "yuksek_risk_count": yuksek,
            "orta_risk_count":   orta,
            "dusuk_risk_count":  dusuk,
            "yuksek_risk_pct": round(yuksek / n * 100, 1),
            "orta_risk_pct":   round(orta   / n * 100, 1),
            "dusuk_risk_pct":  round(dusuk  / n * 100, 1),
        }
        report["risk_distribution"] = {
            "0-29  (Düşük)": dusuk,
            "30-59 (Orta)":  orta,
            "60-100 (Yüksek)": yuksek,
        }

        print("\n" + "═" * 65)
        print("  RISK DAĞILIMI")
        print(f"  Toplam kolon          : {n}")
        print(f"  Ortalama risk skoru   : {avg_r}/100")
        print(f"  🔴 Yüksek (%60+)  : {yuksek} kolon (%{report['summary']['yuksek_risk_pct']})")
        print(f"  🟡 Orta   (%30-59): {orta}  kolon (%{report['summary']['orta_risk_pct']})")
        print(f"  🟢 Düşük  (0-29)  : {dusuk}  kolon (%{report['summary']['dusuk_risk_pct']})")
        print("═" * 65)

    return report


if __name__ == "__main__":
    import json
    from pathlib import Path

    data_path = Path(__file__).parent.parent / "data" / "tables" / "enriched_tables.json"
    with open(data_path, "r", encoding="utf-8") as f:
        tables = json.load(f)

    report = classify_all_risks(tables)
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
