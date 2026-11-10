# II-F ve IV. Bölüm (TASLAK)

## F. Dayanıklılık ve Sınav Güvenliği

Öğrenci uygulamasında cevaplar her değişiklikte sunucuya gönderilmenin yanı sıra öğrenci bilgisayarındaki bir JSON yedek dosyasına da yazılmaktadır. Dosya önce geçici bir dosyaya yazılıp tek adımda asıl dosyanın yerine konduğundan, yazma yarıda kesilse bile eski yedek bozulmamaktadır. Bağlantı koptuğunda sunucunun onaylamadığı cevaplar işaretli tutulmakta ve bağlantı yeniden kurulunca gönderilmektedir. Uygulama çöküp yeniden açıldığında yerel yedek, sunucudan gelen kayıtlı cevaplarla birleştirilir; aynı soru için iki cevap varsa değişiklik zamanı daha yeni olan kazanır. Yedek yazılamazsa öğrenci uyarılır ve sınav kesintisiz sürer. Sınav gönderildiğinde yedek silinir.

Sınav başladığında pencere tam ekrana geçer ve sınav bitene kadar kapatma ve küçültme istekleri reddedilir. Alt+Tab ve Ctrl+Alt+Del kısayolları işletim sistemi düzeyinde olduğundan engellenememektedir; bu nedenle pencereden her çıkış sunucuya `focus_lost` mesajıyla bildirilip loglanır ve pencere kısa bir süre sonra yeniden öne getirilmeye çalışılır. Sunucu çöker ve süre 15 saniyelik payla birlikte dolarsa sınav modu kilidi kendiliğinden kalkar; öğrenci kilitli kalmaz, yedek silinmez ve dosyanın yeri ekranda gösterilir.

## IV. Test ve Değerlendirme

Sistem 317 otomatik testle (pytest) sınanmıştır ve testlerin tamamı geçmektedir. Bunların 292'si birim ve bileşen testi, 25'i gerçek bir WebSocket sunucusuna gerçek bağlantılarla bağlanan uçtan uca testtir. Uçtan uca senaryoda giriş, cevap kaydı, gönderim ve puanlama gerçek bileşenlerle doğrulanmakta; yalnızca saat sahte tutulmaktadır.

Yük testi `scripts/fake_students.py` betiğiyle, gerçek öğrenci uygulamasıyla aynı protokolü kullanan 40 sahte öğrenciyle yapılmıştır. Sunucu ve 40 sahte öğrenci aynı bilgisayarda çalıştırılmıştır; bu nedenle ölçülen yanıt süreleri gerçek ağ gecikmesini içermemektedir. Varsayılan olarak öğrencilerin %20'si erken gönderir, %20'si bağlantıyı koparıp döner; ayrıca her öğrenci %30 olasılıkla pencereden çıkar. Öğrenciler iki cevap arasında 1–5 saniye (yoğun senaryoda 0,05–0,3 saniye) bekler. Her iki senaryoda 8 öğrenci sınavı kendisi göndermiş, bağlantısı kopan 8 öğrencinin 8'inde kayıtlı cevapların geri geldiği doğrulanmış, 7 öğrenci `focus_lost` göndermiştir. Sınav yaklaşık 1 dakika sonra eğitmence bitirilmiş, kalan 32 kâğıt otomatik gönderilmiştir. Başlat işlemi sırasında sınav başlangıç mesajlarının gönderilmesi eğitmen arayüzünü bekletmekteydi; gönderim arka plana alınarak arayüzün beklemesi önlenmiştir.

Tablo II'de görüldüğü gibi yoğun senaryoda kaydedilen cevap sayısı yaklaşık 16,6 kat artmış, ancak hata alan öğrenci olmamış, ortalama yanıt ve p95 değişmemiş; yalnızca en yavaş yanıt 20,2 ms'den 79,5 ms'ye yükselmiştir. İki senaryoda da 40 kâğıdın tamamı puanlanmıştır. Girişin yaklaşık 0,4 saniye sürmesi, bcrypt'in bilerek yavaş olmasından ve girişlerin eş zamanlı gelmesinden kaynaklanmaktadır; ikisinin payı ayrı ölçülmemiştir. Sınav bitirilirken yolda olan 13 kayıt (yoğun senaryo) `TIME_UP` ile reddedilmiştir; bu, sürenin sunucuda belirlenmesinin beklenen sonucudur ve hata sayılmamıştır.

**Tablo II.** 40 eş zamanlı öğrenci ile yük testi sonuçları

|                      | Normal (1–5 sn) | Yoğun (0,05–0,3 sn) |
|----------------------|:---------------:|:-------------------:|
| Test süresi          | ~1 dk           | ~1 dk               |
| Hata alan öğrenci    | 0               | 0                   |
| Kaydedilen cevap     | 652             | 10.835              |
| Ortalama yanıt (ms)  | 5,9             | 5,9                 |
| p95 (ms)             | 12,8            | 12,9                |
| En yavaş yanıt (ms)  | 20,2            | 79,5                |
| Puanlanan kâğıt      | 40/40           | 40/40               |

> Ölçüm: `python -m scripts.fake_students -n 40 --seed 1` (normal) ve `... --min-delay 0.05 --max-delay 0.3 --seed 1` (yoğun). Yanıt süreleri `save_answer` isteğinden `save_ok` cevabına kadar geçen süredir; ortalama = `ort.`, en yavaş = en büyük değer. Puanlanan kâğıt sayısı eğitmen uygulamasının Sonuçlar sekmesinden okunur.

---

## Kelime sayıları
- F: 149 kelime (hedef ~150)
- IV: 212 kelime (hedef ~200), Tablo II hariç
- Ölçüm: `wc -w`, başlık ve tablo hariç gövde metni.

## Ölçümler (bu taslak için çalıştırıldı, 2026-11-10)
- `pytest --collect-only -q` → **317 tests collected** (şablondaki 317 ile aynı).
- `pytest --collect-only -q tests/test_e2e.py tests/test_ws_*.py` → **25** (uçtan uca, gerçek WebSocket). Kalan 317 − 25 = **292**.
  - Not: 292'nin içindeki `tests/test_student_client.py` (6 test) de gerçek `WsServer`'a gerçek `QWebSocket` ile bağlanır. Bunlar istemci sınıfını sınadığı için birim/bileşen grubunda sayıldı; istenirse "31 test gerçek WebSocket kullanır" diye yazılabilir.
- `pytest -q` → **317 passed in 24.07s**, başarısız/atlanan yok.

## Yük testini yeniden üretme (Tablo II)
Arayüzlü sunucu Claude tarafından başlatılamadığı için komutlar elle çalıştırılmalıdır:

```bash
# 1. koşu — Normal
python -m scripts.seed --students 80     # veri tabanını SIFIRLAR; A sınıfında 40 öğrenci
python -m instructor_app.main            # egitmen / egitmen123; örnek sınavın süresini not edin
python -m scripts.fake_students -n 40 --seed 1     # ayrı terminal; öğrenciler bağlanınca "Başlat"

# 2. koşu — Yoğun (önce eğitmen uygulamasını kapatın; sınav bittiği için tekrar seed gerekir)
python -m scripts.seed --students 80
python -m instructor_app.main
python -m scripts.fake_students -n 40 --min-delay 0.05 --max-delay 0.3 --seed 1
```

Her koşudan yapıştırılacaklar:
- Özetin tamamı; özellikle `Kaydedilen cevap (save_ok)`, `save_answer ort. / p95 / en yavaş` (tabloda ortalama = ort., en yavaş = son değer), `Hata alan öğrenci` ve varsa `(beklenen, hata sayılmaz) TIME_UP` satırları.
- **Puanlanan kâğıt**: fake_students çıktısında yoktur; eğitmen uygulamasının Sonuçlar sekmesinden okunmalıdır.
- **Sınav süresi** (dakika): kaydedilen cevap sayısı doğrudan süreye bağlıdır, metinde belirtilmelidir.
- Not (2026-11-10 ölçümü): her iki koşu ~1 dk sürmüş, sınav eğitmen tarafından Canlı Panel'deki "Sınavı Bitir" ile sonlandırılmıştır (`instructor_app/ui/live_panel.py:143`, `:401`; `exam_end.reason = "instructor_stopped"`).

## Doğrulanan iddialar (dosya:satır)
**F**
- JSON yedek, her değişiklikte yazılır — `student_app/ui/exam_view.py:340-347`, `:384-388`; yer: `student_app/local_backup.py:33` (platformdirs)
- Geçici dosya + `os.replace` — `student_app/local_backup.py:10-11`, `:50-62`
- Onaylanmamış (dirty) cevaplar; bağlantı kopunca `forget_sent`, gelince `flush_saves` — `student_app/exam_state.py:6-7`, `:95-97`; `student_app/ui/exam_view.py:214-227`; yeniden girişte `:204`
- Çökme sonrası birleştirme, daha yeni `updated_at` kazanır — `student_app/exam_state.py:99-121` (karşılaştırma `:113`); çağrı `student_app/ui/exam_view.py:374-382`
- Yedek yazılamazsa uyarı, sınav sürer — `student_app/ui/exam_view.py:389-393`
- Gönderilince yedek silinir — `student_app/ui/exam_view.py:251-258`, `student_app/local_backup.py:82`
- Tam ekran, kapatma ve küçültme engeli — `student_app/main.py:284-287`, `:302-306`, `:310-315`
- Alt+Tab / Ctrl+Alt+Del engellenemez — `student_app/main.py:8-10`
- `focus_lost` gönderimi ve sunucuda loglanması — `student_app/ui/exam_view.py:498-502`; `server/net/ws_server.py:543-551`
- Sunucu yokken süre + 15 sn → kilit kalkar, yedek silinmez, yeri gösterilir — `student_app/ui/exam_view.py:49`, `:432-439`, `:251-258`; `student_app/main.py:11`, `:267-275`
- Pencere 500 ms sonra yeniden öne getirilmeye çalışılır — `student_app/main.py:69`, `:293-300`

**IV**
- Uçtan uca testte yalnız saat sahte, puanlama gerçek — `tests/test_e2e.py:1-10`
- Oranlar: erken 0,2 / bağlantı koparan 0,2 / pencereden çıkan 0,3; bekleme 1–5 sn — `scripts/fake_students.py:428-432` (ayrıca `:54-56`); yeniden bağlanma denetimi — `scripts/fake_students.py:1-13`
- Not: erken gönderen ve bağlantı koparan gruplar ayrıdır (`:102-108`); pencereden çıkma her öğrenciye rastgele (%30 olasılıkla) atanır, yani diğer gruplarla çakışabilir.
- Darboğaz düzeltmesi — commit `3b0275b` (P7, 6 Kasım 2026): `server/net/ws_server.py:317-331` (`_start_exam` → `self._spawn(self._send_exam_start_to_class(...))`, yorum `:320-321` "yük testinde bulunan bekleme"). Commit mesajı: "exam_start gönderimi arka planda (eğitmen arayüzü beklemiyor)".

## [DOĞRULANACAK]
1. **Normal senaryodaki TIME_UP sayısı**: verilen "1" değeri önceki bir koşudan; Tablo II'deki koşuya ait olmadığı için metne yazılmadı. Bu koşunun çıktısındaki `(beklenen, hata sayılmaz) TIME_UP` satırı varsa eklenebilir.
2. **Giriş süresi ~0,4 sn ve bcrypt**: maliyet çarpanı 12 (`shared/config.py:27`, `server/services/auth.py:20-27`), doğrulama ayrı thread'de (`server/net/ws_server.py:468-469`). Sürenin ne kadarının bcrypt'ten, ne kadarının 40 girişin aynı anda gelip sırada beklemesinden kaynaklandığı ayrıca ölçülmedi.
3. **16,6 kat**: 10.835 / 652 = 16,62. "Yaklaşık 16 kat" yerine bu değer yazıldı (yuvarlanırsa 17).
