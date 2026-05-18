# Clarity Score Metodolojisi

## Amaç

Kolon açıklamalarının kalitesini sayısal olarak ölçmek için Clarity Score metodolojisi tanımlanmıştır. Bu skor 0-100 arasında bir değer alır.

## Değerlendirme Kriterleri

| Kriter | Açıklama | Maks Puan |
|---|---|---|
| Tablo bağlamı | Kolon hangi tabloya ait, tablo ne anlama geliyor | 25 |
| Değer aralığı | Düşük kardinaliteli kolonlarda değerler açıklanmış mı | 20 |
| Referans bütünlüğü | Lookup / FK tablosuna atıf var mı | 15 |
| İş kuralı | Varsa iş kuralı dahil edilmiş mi | 20 |
| Dil tutarlılığı | Şema diliyle TR tutarlı mı | 10 |
| Uzunluk & netlik | Çok kısa ya da belirsiz değil | 10 |

## Kabul Eşiği

Sistem artık kolonları `HIGH_RISK` veya `LOW_RISK` olarak sınıflandırmaz. Bunun yerine her kolon için 0-100 arasında sayısal bir kalite puanı üretir.

- **Clarity Score >= 80** → Kabul edilir.
- **Clarity Score < 80** → Güncelleme / yeniden zenginleştirme gerektirir.

## Popup / UI Mekanizması

UI tarafında her kolon için:
- İlk açıklama
- Güncellenmiş açıklama
- Clarity Score
- Kabul durumu
- Tespit edilen eksikler

gösterilir.