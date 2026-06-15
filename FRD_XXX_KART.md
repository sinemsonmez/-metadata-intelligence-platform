# Fonksiyonel İhtiyaç Dokümanı: XXX_KART

**Doküman No:** FRD-CORE-XXX_KA  
**Tablo:** CORE_BANKING.XXX_KART  
**Kavramsal Model:** Card  
**Durum:** Sentetik örnek (otomatik üretim)

---

## 1. Genel Tanım

Debit/kredi kartı ana verisi.

## 2. Kolon Açıklamaları ve İş Kuralları

### KART_NO
Veri tipi: VARCHAR(20).
⚠️ Veri kalitesi notu: Documented range does not match production samples.
KART_NO — last 90 days aggregate (column name implies 30 days).

### KART_TARIH
Veri tipi: DATE.
KART_TARIH için tutulan alan.

### KART_KOD
Veri tipi: NUMBER(2).
Lookup referansı: LKP_KART.
Bilinen değerler: [0, 1, 2].
KART_KOD bilgisidir.

### KART_DURUM
Veri tipi: NUMBER(1).
Bilinen değerler: [0, 1, 2].
⚠️ Veri kalitesi notu: Documented range does not match production samples.
KART_DURUM — last 90 days aggregate (column name implies 30 days).

### MUSTERI_NO
Veri tipi: NUMBER(10).
MUSTERI_NO alanı; iş kurallarına uygun tam açıklama.


## 3. Veri Kalitesi Kuralları

- Birincil anahtar kolonları NULL olamaz.
- Lookup referanslı kolonlar ilgili LKP tablosu ile tutarlı olmalıdır.
- Düşük kardinaliteli kod kolonları için değer aralığı dokümante edilmelidir.
