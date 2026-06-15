# Fonksiyonel İhtiyaç Dokümanı: MUS_SEGMENTASYON

**Doküman No:** FRD-CRM-MUS_SE  
**Tablo:** CRM.MUS_SEGMENTASYON  
**Kavramsal Model:** Customer  
**Durum:** Sentetik örnek (otomatik üretim)

---

## 1. Genel Tanım

Customer segmentation table for CRM analytics.

## 2. Kolon Açıklamaları ve İş Kuralları

### MUSTERI_NO
Veri tipi: NUMBER(10).
Müşteri kimlik numarasıdır.

### SEGMENT_KOD
Veri tipi: VARCHAR(5).
Lookup referansı: LKP_SEGMENT.

### GELIR_GRUBU
Veri tipi: NUMBER(1).
Bilinen değerler: [1, 2, 3, 4, 5].
Gelir grubu kodu.


## 3. Veri Kalitesi Kuralları

- Birincil anahtar kolonları NULL olamaz.
- Lookup referanslı kolonlar ilgili LKP tablosu ile tutarlı olmalıdır.
- Düşük kardinaliteli kod kolonları için değer aralığı dokümante edilmelidir.
