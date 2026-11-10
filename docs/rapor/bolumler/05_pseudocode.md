# II. Yöntem — Algoritma 1 ve 2 (TASLAK, Kişi 3)

Bu dosyadaki iki algoritma II-D ve II-E bölümlerinde (`04_sure_puanlama.md`) "Algoritma 1'de" ve
"Algoritma 2'de" diye atıf yapılan pseudocode'lardır. Her algoritma için iki sürüm verilmiştir:

- **Açıklamalı sürüm:** sağda `▷` ile yorumlar vardır (ekip içi okuma ve demo için).
- **Word için düz metin:** yorumsuzdur, Courier New 9 pt ile IEEE tek sütun genişliğine sığar
  (satır başına en fazla 45 karakter, numara ve girinti dahil). Word'e olduğu gibi yapıştırılır.

---

## Algoritma 1. Süresi dolan sınavların otomatik gönderimi

### Açıklamalı sürüm

```
Algoritma 1. Süresi dolan sınavların otomatik gönderimi
GİRDİ: sunucu saati, sınavlar
ÇIKTI: bitirilen sınavlar, exam_end, loglar
 1 HER saniye İÇİN
 2   şimdi ← sunucu saati
 3   adaylar ← "running" VE bitiş ≤ şimdi      ▷ kilitsiz okuma
 4   adaylardaki HER sınav İÇİN
 5     KİLİT AL; sınavı tekrar oku
 6     EĞER "running" VE bitiş ≤ şimdi İSE     ▷ tekrar kontrol: kilit beklenirken
                                               ▷ süre eklenmiş / sınav durdurulmuş olabilir
 7       gönderilmemiş HER öğrenciKaydı İÇİN
 8         öğrenciKaydı.durum ← "submitted"
 9         öğrenciKaydı.zaman ← sınav.bitiş    ▷ gönderim zamanı = bitiş saati, "şimdi" değil
10         öğrenciKaydı.otomatik ← DOĞRU       ▷ auto_submitted
11       BİTİR
12       sınav.durum ← "finished"
13     BİTİR
14     KİLİDİ BIRAK                            ▷ değişiklikler kaydedilir (commit)
15   BİTİR
16   bu turda bitirilen HER sınav İÇİN
17     auto_submitted logla; exam_end yolla    ▷ sınıftaki bağlı öğrencilere
18     kâğıtları arka planda PUANLA            ▷ her kâğıt ayrı yazma işleminde
19   BİTİR
20 BİTİR
```

### Açıklama (rapor metni)

Sunucu bu işlemi saniyede bir çalıştırır. Süresi dolmuş sınavlar önce kilit alınmadan okunur; böylece
bitecek sınav olmadığında yazma kilidi boşuna alınmaz. Kilit alındıktan sonra koşul yeniden kontrol edilir,
çünkü kilit beklenirken eğitmen süre eklemiş ya da sınavı durdurmuş olabilir. Gönderilmemiş kâğıtlara
gönderim zamanı olarak sınavın bitiş saati yazılır.

### Word için düz metin

```
Algoritma 1. Süresi dolan sınavların
otomatik gönderimi
GİRDİ: sunucu saati, sınavlar
ÇIKTI: bitirilen sınavlar, exam_end, loglar
 1 HER saniye İÇİN
 2   şimdi ← sunucu saati
 3   adaylar ← "running" VE bitiş ≤ şimdi
 4   adaylardaki HER sınav İÇİN
 5     KİLİT AL; sınavı tekrar oku
 6     EĞER "running" VE bitiş ≤ şimdi İSE
 7       gönderilmemiş HER öğrenciKaydı İÇİN
 8         öğrenciKaydı.durum ← "submitted"
 9         öğrenciKaydı.zaman ← sınav.bitiş
10         öğrenciKaydı.otomatik ← DOĞRU
11       BİTİR
12       sınav.durum ← "finished"
13     BİTİR
14     KİLİDİ BIRAK
15   BİTİR
16   bu turda bitirilen HER sınav İÇİN
17     auto_submitted logla; exam_end yolla
18     kâğıtları arka planda PUANLA
19   BİTİR
20 BİTİR
```

Not: Satır 7–12'deki gönderim adımları, eğitmen sınavı "Durdur" ile erken bitirdiğinde de aynı
fonksiyonla (`_finish_exam`) yapılır; o durumda `exam_end` nedeni `instructor_stopped` olur.

---

## Algoritma 2. Klasik soru puanlama

### Açıklamalı sürüm

```
Algoritma 2. Klasik soru puanlama
FONKSİYON NORMALIZE(metin)
GİRDİ: metin
ÇIKTI: karşılaştırmaya hazır metin
 1 EĞER metin boş İSE
 2   DÖNDÜR ""
 3 BİTİR
 4 metin ← NFC(metin)                         ▷ aynı harfin farklı kodlamaları tek biçime
 5 "I" → "ı" ve "İ" → "i" değiştir            ▷ Türkçe kural (lower() bunu bilmez)
 6 metin ← KÜÇÜK_HARF(metin)
 7 çoklu boşlukları tek boşluğa indir         ▷ baş/son boşluk, sekme, satır sonu dahil
 8 sondaki noktalama ve boşlukları sil        ▷ . , ; : ! ? …
 9 DÖNDÜR metin
FONKSİYON GRADE_CLASSIC(cevap, soru, tamPuan)
GİRDİ: cevap, soru, tamPuan (sınavdaki puan)
ÇIKTI: cevap.doğru, cevap.puan
10 EĞER cevap.elle İSE                        ▷ is_manual: eğitmen puanı korunur
11   DÖNDÜR
12 BİTİR
13 verilen ← NORMALIZE(cevap.metin)
14 kabuller ← NORMALIZE(soru.kabulEdilenler)  ▷ her biri ayrı ayrı
15 cevap.doğru ← verilen ≠ "" VE              ▷ boş cevap asla doğru sayılmaz
16   verilen kabuller içinde
17 cevap.puan ← 0
18 EĞER cevap.doğru İSE
19   cevap.puan ← tamPuan
20 BİTİR
```

Örnek: `NORMALIZE("  İSTANBUL.  ")` → `"istanbul"`.

### Açıklama (rapor metni)

NORMALIZE fonksiyonu, öğrenci cevabını ve kabul edilen cevapları aynı biçime getirir. GRADE_CLASSIC, eğitmenin elle puan verdiği cevaplara dokunmaz; diğer cevaplarda normalize edilmiş cevap
kabul edilenlerden biriyle eşleşirse tam puan, eşleşmezse 0 verilir ve boş cevap hiçbir zaman doğru sayılmaz.

### Word için düz metin

```
Algoritma 2. Klasik soru puanlama
FONKSİYON NORMALIZE(metin)
GİRDİ: metin
ÇIKTI: karşılaştırmaya hazır metin
 1 EĞER metin boş İSE
 2   DÖNDÜR ""
 3 BİTİR
 4 metin ← NFC(metin)
 5 "I" → "ı" ve "İ" → "i" değiştir
 6 metin ← KÜÇÜK_HARF(metin)
 7 çoklu boşlukları tek boşluğa indir
 8 sondaki noktalama ve boşlukları sil
 9 DÖNDÜR metin
FONKSİYON GRADE_CLASSIC(cevap, soru, tamPuan)
GİRDİ: cevap, soru, tamPuan (sınavdaki puan)
ÇIKTI: cevap.doğru, cevap.puan
10 EĞER cevap.elle İSE
11   DÖNDÜR
12 BİTİR
13 verilen ← NORMALIZE(cevap.metin)
14 kabuller ← NORMALIZE(soru.kabulEdilenler)
15 cevap.doğru ← verilen ≠ "" VE
16   verilen kabuller içinde
17 cevap.puan ← 0
18 EĞER cevap.doğru İSE
19   cevap.puan ← tamPuan
20 BİTİR
```

Not: Kodda puan tek satırda `tam puan if doğru else 0` biçiminde verilir. Pseudocode'da 45 karakter
sınırında 20 satıra sığması için "önce 0, doğruysa tam puan" kalıbı kullanılmıştır; sonuç aynıdır.

---

## Pseudocode satırlarının koddaki karşılıkları

### Algoritma 1

| Satır | Pseudocode | Kod (dosya:satır) |
|---|---|---|
| 1 | HER saniye İÇİN | `server/net/ws_server.py:358` (`while True`), `:365` (bekleme), `:68` (`EXAM_TICK_SEC = 1.0`); döngü açılışta başlar `:223` |
| 2 | şimdi ← sunucu saati | `server/net/ws_server.py:360` (`self.clock()`) |
| 3 | adaylar ← … (kilitsiz) | `server/services/exam_session.py:135-139` (`get_session`, kilit yok) |
| 4 | adaylardaki HER sınav | `server/services/exam_session.py:141` |
| 5 | KİLİT AL; tekrar oku | `server/services/exam_session.py:142-143`; kilit: `server/db/session.py:31`, `:117-125` |
| 6 | tekrar kontrol | `server/services/exam_session.py:144-145` |
| 7 | gönderilmemiş HER öğrenciKaydı | `server/services/exam_session.py:152-157` (`status == "in_progress"`) |
| 8 | durum ← "submitted" | `server/services/exam_session.py:158` |
| 9 | zaman ← sınav.bitiş | `server/services/exam_session.py:159`; bitiş saati verilir: `:146` |
| 10 | otomatik ← DOĞRU | `server/services/exam_session.py:160` |
| 12 | sınav.durum ← "finished" | `server/services/exam_session.py:161` |
| 14 | KİLİDİ BIRAK (commit) | `server/db/session.py:109` (commit, iç `get_session` bloğu `:124` biter), ardından `:123` `with _write_lock` bloğundan çıkılınca kilit bırakılır |
| 16 | bitirilen HER sınav | `server/net/ws_server.py:361-362`; liste: `server/services/exam_session.py:140`, `:146-147` |
| 17 | logla; exam_end yolla | `server/net/ws_server.py:369-373` (log), `:375-377` (exam_end); arayüze bildirim `:374`, `:378` → `instructor_app/server_bridge.py:30-34` |
| 18 | arka planda PUANLA | `server/net/ws_server.py:379` → `:393-396` → `:418-423` → `server/services/grading.py:75` (`grade_submission`) |

### Algoritma 2

| Satır | Pseudocode | Kod (dosya:satır) |
|---|---|---|
| 1-3 | metin boşsa "" | `server/services/grading.py:50-51` |
| 4 | NFC | `server/services/grading.py:54` |
| 5-6 | Türkçe I/İ + küçük harf | `server/services/grading.py:55` → `server/services/question_bank.py:450-452` (`turkish_lower`) |
| 7 | boşlukları sadeleştir | `server/services/grading.py:56` |
| 8 | sondaki noktalama + boşluk | `server/services/grading.py:57`; işaretler `:27` |
| 9 | DÖNDÜR metin | `server/services/grading.py:57` |
| 10-12 | is_manual ise dokunma | `server/services/grading.py:88-90` (`grade_submission` içinde; `_grade_answer` sadece elle puanlanmamış cevaplar için çağrılır) |
| 13 | verilen ← NORMALIZE | `server/services/grading.py:65` |
| 14 | kabuller ← NORMALIZE | `server/services/grading.py:66` |
| 15-16 | cevap.doğru | `server/services/grading.py:67`; yazılması `:96-97` |
| 17-20 | puan | `server/services/grading.py:98-101` |
