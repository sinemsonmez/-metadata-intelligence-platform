# Fonksiyonel İhtiyaç Dokümanı: XXX_HESAP

**Doküman No:** FRD-CORE-001  
**Tablo:** CORE_BANKING.XXX_HESAP  
**Hazırlayan:** Core Banking Team  
**Tarih:** 2024-03-15  
**Durum:** Onaylı

---

## 1. Genel Tanım

XXX_HESAP tablosu, bankamız müşterilerine ait tüm hesap bilgilerini merkezi olarak tutan ana tablodur. Bireysel ve ticari müşterilere ait vadesiz, vadeli, döviz, altın ve yatırım hesaplarını kapsar.

## 2. Kolon Açıklamaları ve İş Kuralları

### HESAP_NO
Hesabın benzersiz tanımlayıcısıdır. IBAN formatında 26 karakter olarak tutulur.  
Format: `TR` + 2 kontrol hanesi + 4 banka kodu + 16 hesap numarası

### ACILIS_TARIHI
Ticari veya bireysel hesabın resmi açılış tarihidir.  
**Önemli İş Kuralı:** Valörlü açılan hesaplarda bu tarih, fiziksel açılış tarihi değil valör tarihidir. Hesabın gerçek açılış tarihi ile valör tarihi ayrı tutulmak isteniyorsa `VALOR_TARIHI` kolonuna bakılmalıdır.

### VALOR_TARIHI
Valörlü açılan hesaplarda geçerli olan valör tarihidir. Standart hesaplarda NULL olabilir.

### HESAP_TIP_KOD
LKP_HESAP_TIP tablosundan gelen hesap tipi kodudur. Alabileceği değerler:
- 1: Vadesiz
- 2: Vadeli
- 3: Döviz
- 4: Altın
- 5: Yatırım

### HESAP_DURUM_KOD
**⚠️ DİKKAT:** Bu kolon için LKP tablosu tanımlanmamıştır. Bilinen değerler:
- 0: Aktif
- 1: Pasif
- 2: Kapalı

*Doküman hazırlanırken 3 değerinin de varlığına dair bulgular raporlanmıştır. İncelenmesi gerekmektedir.*

### SUBE_KOD
LKP_SUBE tablosundan gelen şube kodudur. FK ilişkisi veri modelinde tanımlı değildir ancak referans ilişkisi mevcuttur.

## 3. Veri Kalitesi Kuralları

- HESAP_NO NULL olamaz ve UNIQUE olmalıdır.
- ACILIS_TARIHI NULL olamaz.
- Her hesabın geçerli bir MUSTERI_NO ile ilişkilendirilmesi zorunludur.
