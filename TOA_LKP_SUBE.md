# TOA Dokümanı: LKP_SUBE

**Doküman No:** TOA-CORE-LKP_SU  
**Tablo:** CORE_BANKING.LKP_SUBE  
**Durum:** Sentetik örnek (otomatik üretim)

---

## TOA (Teknik Operasyonel Analiz)

### Boyut Analizi
- Tahmini kayıt sayısı: sentetik ortam örneği
- Partition: Hayır

### Örnek Analiz Sorguları

```sql
SELECT COUNT(*) FROM CORE_BANKING.LKP_SUBE;
```

```sql
SELECT column_name, data_type
FROM all_tab_columns
WHERE owner = 'CORE_BANKING' AND table_name = 'LKP_SUBE';
```
