# Fonksiyonel İhtiyaç Dokümanı: KRD_ODEME_PLAN

**Doküman No:** FRD-CRED-KRD_OD  
**Tablo:** CREDIT.KRD_ODEME_PLAN  
**Kavramsal Model:** PaymentPlan  
**Durum:** Sentetik örnek (otomatik üretim)

---

## 1. Genel Tanım

Kredi taksit ve ödeme planı.

## 2. Kolon Açıklamaları ve İş Kuralları

### PLAN_NO
Veri tipi: VARCHAR(20).
⚠️ Veri kalitesi notu: Documented range does not match production samples.
PLAN_NO — last 90 days aggregate (column name implies 30 days).

### PLAN_TARIH
Veri tipi: DATE.
PLAN_TARIH için tutulan alan.

### PLAN_KOD
Veri tipi: NUMBER(2).
Lookup referansı: LKP_PLAN.
Bilinen değerler: [0, 1, 2].
PLAN_KOD bilgisidir.

### PLAN_DURUM
Veri tipi: NUMBER(1).
Bilinen değerler: [0, 1, 2].
⚠️ Veri kalitesi notu: Documented range does not match production samples.
PLAN_DURUM — last 90 days aggregate (column name implies 30 days).

### MUSTERI_NO
Veri tipi: NUMBER(10).
MUSTERI_NO alanı; iş kurallarına uygun tam açıklama.


## 3. Veri Kalitesi Kuralları

- Birincil anahtar kolonları NULL olamaz.
- Lookup referanslı kolonlar ilgili LKP tablosu ile tutarlı olmalıdır.
- Düşük kardinaliteli kod kolonları için değer aralığı dokümante edilmelidir.
