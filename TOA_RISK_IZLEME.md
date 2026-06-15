# TOA Dokümanı: RISK_IZLEME

**Doküman No:** TOA-RISK-RISK_I  
**Tablo:** RISK.RISK_IZLEME  
**Durum:** Sentetik örnek (otomatik üretim)

---

## TOA (Teknik Operasyonel Analiz)

### Boyut Analizi
- Tahmini kayıt sayısı: sentetik ortam örneği
- Partition: Evet — RAPOR_TARIHI

### Örnek Analiz Sorguları

```sql
SELECT COUNT(*) FROM RISK.RISK_IZLEME;
```

```sql
SELECT column_name, data_type
FROM all_tab_columns
WHERE owner = 'RISK' AND table_name = 'RISK_IZLEME';
```
