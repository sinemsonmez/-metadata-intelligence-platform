# Fonksiyonel İhtiyaç Dokümanı: MUS_ILETISIM

**Doküman No:** FRD-CRM-MUS_IL  
**Tablo:** CRM.MUS_ILETISIM  
**Kavramsal Model:** Contact  
**Durum:** Sentetik örnek (otomatik üretim)

---

## 1. Genel Tanım

Müşteri iletişim kanalı ve tercihleri.

## 2. Kolon Açıklamaları ve İş Kuralları

### ILET_NO
Veri tipi: VARCHAR(20).
⚠️ Veri kalitesi notu: Documented range does not match production samples.
ILET_NO — last 90 days aggregate (column name implies 30 days).

### ILET_TARIH
Veri tipi: DATE.
ILET_TARIH için tutulan alan.

### ILET_KOD
Veri tipi: NUMBER(2).
Lookup referansı: LKP_ILETIS.
Bilinen değerler: [0, 1, 2].
ILET_KOD bilgisidir.

### ILET_DURUM
Veri tipi: NUMBER(1).
Bilinen değerler: [0, 1, 2].
⚠️ Veri kalitesi notu: Documented range does not match production samples.
ILET_DURUM — last 90 days aggregate (column name implies 30 days).

### MUSTERI_NO
Veri tipi: NUMBER(10).
MUSTERI_NO alanı; iş kurallarına uygun tam açıklama.


## 3. Veri Kalitesi Kuralları

- Birincil anahtar kolonları NULL olamaz.
- Lookup referanslı kolonlar ilgili LKP tablosu ile tutarlı olmalıdır.
- Düşük kardinaliteli kod kolonları için değer aralığı dokümante edilmelidir.
