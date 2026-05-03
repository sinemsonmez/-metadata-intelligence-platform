# TOA Dokümanı ve Analiz Sorguları: XXX_HESAP

**Doküman No:** TOA-CORE-001  
**Tablo:** CORE_BANKING.XXX_HESAP  
**Hazırlayan:** Data Architecture Team  

---

## TOA (Teknik Operasyonel Analiz)

### Boyut Analizi
- Tahmini kayıt sayısı: 45 milyon
- Ortalama günlük değişim: ~50.000 kayıt
- Veri saklama süresi: Süresiz (tarihsel)

### Partition Durumu
Tablo partition'lı DEĞİLDİR. Büyük tabloda sorgu performansı için index kullanımı kritiktir.

### Kritik Indexler
```sql
CREATE INDEX IDX_HESAP_MUSTERI ON CORE_BANKING.XXX_HESAP(MUSTERI_NO);
CREATE INDEX IDX_HESAP_DURUM   ON CORE_BANKING.XXX_HESAP(HESAP_DURUM_KOD);
CREATE INDEX IDX_HESAP_SUBE    ON CORE_BANKING.XXX_HESAP(SUBE_KOD);
```

---

## Analiz Sorguları

### 1. Hesap Durum Dağılımı (Validation için)
```sql
SELECT HESAP_DURUM_KOD, COUNT(*) as ADET
FROM CORE_BANKING.XXX_HESAP
GROUP BY HESAP_DURUM_KOD
ORDER BY HESAP_DURUM_KOD;
-- Beklenen: 0, 1, 2 — beklenmeyen 3 tespit edilirse alert üretilir
```

### 2. Düşük Kardinalite Kontrolü
```sql
SELECT COUNT(DISTINCT HESAP_TIP_KOD)    AS TIP_DISTINCT,
       COUNT(DISTINCT HESAP_DURUM_KOD)  AS DURUM_DISTINCT,
       COUNT(DISTINCT SUBE_KOD)         AS SUBE_DISTINCT
FROM CORE_BANKING.XXX_HESAP;
```

### 3. Valör-Açılış Tarihi Tutarsızlık Kontrolü
```sql
SELECT COUNT(*) as TUTARSIZ_KAYIT
FROM CORE_BANKING.XXX_HESAP
WHERE VALOR_TARIHI IS NOT NULL
  AND VALOR_TARIHI < ACILIS_TARIHI;
-- Valör tarihi açılış tarihinden önce olamaz
```

### 4. LKP Sube FK Kontrolü (FK tanımlı olmadığı için manuel)
```sql
SELECT h.SUBE_KOD, COUNT(*) as ADET
FROM CORE_BANKING.XXX_HESAP h
LEFT JOIN CORE_BANKING.LKP_SUBE l ON h.SUBE_KOD = l.KOD
WHERE l.KOD IS NULL
GROUP BY h.SUBE_KOD;
-- Sonuç > 0 ise orphan sube_kod var demektir
```
