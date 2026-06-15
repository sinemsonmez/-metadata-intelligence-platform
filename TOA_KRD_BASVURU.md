# TOA Dokümanı: KRD_BASVURU

**Doküman No:** TOA-CRED-KRD_BA  
**Tablo:** CREDIT.KRD_BASVURU  
**Durum:** Sentetik örnek (otomatik üretim)

---

## TOA (Teknik Operasyonel Analiz)

### Boyut Analizi
- Tahmini kayıt sayısı: sentetik ortam örneği
- Partition: Hayır

### Örnek Analiz Sorguları

```sql
SELECT COUNT(*) FROM CREDIT.KRD_BASVURU;
```

```sql
SELECT column_name, data_type
FROM all_tab_columns
WHERE owner = 'CREDIT' AND table_name = 'KRD_BASVURU';
```
