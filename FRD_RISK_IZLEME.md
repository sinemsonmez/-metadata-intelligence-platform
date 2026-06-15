# Fonksiyonel İhtiyaç Dokümanı: RISK_IZLEME

**Doküman No:** FRD-RISK-RISK_I  
**Tablo:** RISK.RISK_IZLEME  
**Kavramsal Model:** Risk  
**Durum:** Sentetik örnek (otomatik üretim)

---

## 1. Genel Tanım

Risk izleme ve takip tablosu. Müşteri bazlı risk skorlarını ve limit aşım bilgilerini içerir.

## 2. Kolon Açıklamaları ve İş Kuralları

### MUSTERI_NO
Veri tipi: NUMBER(10).
Müşteri kimlik numarası.

### RISK_SKOR
Veri tipi: NUMBER(5,2).
0-100 arası risk skoru. Yüksek değer yüksek riski ifade eder.

### RISK_SINIF
Veri tipi: VARCHAR(10).
Bilinen değerler: ['LOW', 'MEDIUM', 'HIGH'].
Risk sınıfı.


## 3. Veri Kalitesi Kuralları

- Birincil anahtar kolonları NULL olamaz.
- Lookup referanslı kolonlar ilgili LKP tablosu ile tutarlı olmalıdır.
- Düşük kardinaliteli kod kolonları için değer aralığı dokümante edilmelidir.
