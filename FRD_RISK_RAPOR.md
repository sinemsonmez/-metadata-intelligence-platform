# Fonksiyonel İhtiyaç Dokümanı: RISK_RAPOR

**Doküman No:** FRD-RISK-RISK_R  
**Tablo:** RISK.RISK_RAPOR  
**Kavramsal Model:** RiskReport  
**Durum:** Sentetik örnek (otomatik üretim)

---

## 1. Genel Tanım

Tablo açıklaması mevcut değil.

## 2. Kolon Açıklamaları ve İş Kuralları

### RAPO_NO
Veri tipi: VARCHAR(20).
RAPO_NO alanı; iş kurallarına uygun tam açıklama.

### RAPO_TARIH
Veri tipi: DATE.

### RAPO_KOD
Veri tipi: NUMBER(2).
Lookup referansı: LKP_RAPOR.
Bilinen değerler: [0, 1, 2].
RAPO_KOD code value.

### RAPO_DURUM
Veri tipi: NUMBER(1).
Bilinen değerler: [0, 1, 2].
RAPO_DURUM alanı; iş kurallarına uygun tam açıklama.

### MUSTERI_NO
Veri tipi: NUMBER(10).
⚠️ Veri kalitesi notu: Documented range does not match production samples.
MUSTERI_NO — last 90 days aggregate (column name implies 30 days).


## 3. Veri Kalitesi Kuralları

- Birincil anahtar kolonları NULL olamaz.
- Lookup referanslı kolonlar ilgili LKP tablosu ile tutarlı olmalıdır.
- Düşük kardinaliteli kod kolonları için değer aralığı dokümante edilmelidir.
