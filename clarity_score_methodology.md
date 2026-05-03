# Clarity Score Metodolojisi

**Doküman No:** TOA-METHOD-001  
**Hazırlayan:** Data Architecture Team  

---

## Amaç

Kolon açıklamalarının kalitesini sayısal olarak ölçmek için Clarity Score metodolojisi tanımlanmıştır. Bu skor 0-100 arasında bir değer alır.

## Değerlendirme Kriterleri

| Kriter | Açıklama | Maks Puan |
|---|---|---|
| Tablo bağlamı | Kolon hangi tabloya ait, tablo ne anlama geliyor | 25 |
| Değer aralığı | Düşük kardinaliteli kolonlarda değerler açıklanmış mı | 20 |
| Referans bütünlüğü | Lookup / FK tablosuna atıf var mı | 15 |
| İş kuralı | Varsa iş kuralı dahil edilmiş mi | 20 |
| Dil tutarlılığı | Şema diliyle (TR) tutarlı mı | 10 |
| Uzunluk & netlik | Çok kısa ya da belirsiz değil | 10 |

## Risk Sınıflandırması

- **Clarity Score < 40** → `HIGH_RISK`
- **Clarity Score 40-70** → `MEDIUM` (dikkat gerektirir)
- **Clarity Score > 70** → `LOW_RISK`

## Popup Uyarı Mekanizması

HIGH_RISK olarak etiketlenen kolonlar için dashboard'da popup uyarısı gösterilir. Popup'ta:
- Risk seviyesi
- Mevcut açıklama
- Tespit edilen sorunlar

görünür. Müşteri bilgisi açığa çıkarılmadan uyarı mekanizması çalışır.
