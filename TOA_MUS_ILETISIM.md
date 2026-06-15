# TOA Dokümanı: MUS_ILETISIM

**Doküman No:** TOA-CRM-MUS_IL  
**Tablo:** CRM.MUS_ILETISIM  
**Durum:** Sentetik örnek (otomatik üretim)

---

## TOA (Teknik Operasyonel Analiz)

### Boyut Analizi
- Tahmini kayıt sayısı: sentetik ortam örneği
- Partition: Hayır

### Örnek Analiz Sorguları

```sql
SELECT COUNT(*) FROM CRM.MUS_ILETISIM;
```

```sql
SELECT column_name, data_type
FROM all_tab_columns
WHERE owner = 'CRM' AND table_name = 'MUS_ILETISIM';
```
