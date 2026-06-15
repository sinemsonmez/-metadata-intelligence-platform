# Fonksiyonel İhtiyaç Dokümanı: LKP_DOVIZ

**Doküman No:** FRD-CORE-LKP_DO  
**Tablo:** CORE_BANKING.LKP_DOVIZ  
**Kavramsal Model:** Lookup  
**Durum:** Sentetik örnek (otomatik üretim)

---

## 1. Genel Tanım

Tablo açıklaması mevcut değil.

## 2. Kolon Açıklamaları ve İş Kuralları

### KOD
Veri tipi: NUMBER(4).
Bilinen değerler: [0, 1, 2].
KOD alanı; iş kurallarına uygun tam açıklama.

### ACIKLAMA
Veri tipi: VARCHAR(100).
Bilinen değerler: ['A', 'B', 'C'].
ACIKLAMA bilgisidir.


## 3. Veri Kalitesi Kuralları

- Birincil anahtar kolonları NULL olamaz.
- Lookup referanslı kolonlar ilgili LKP tablosu ile tutarlı olmalıdır.
- Düşük kardinaliteli kod kolonları için değer aralığı dokümante edilmelidir.
