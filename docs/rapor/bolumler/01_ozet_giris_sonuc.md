# Özet, I. Giriş, V. Sonuç (TASLAK, Kişi 1)

## Özet

Programlama laboratuvarı sınavlarında kâğıt üzerinde yazılan kod çalıştırılamamakta, çevrimiçi değerlendirme platformları ise internet bağlantısı gerektirmekte ve öğrenci verilerini dış sunucularda tutmaktadır. Bu çalışmada, internet bağlantısı gerektirmeden yerel ağ üzerinde çalışan LabSınav sistemi geliştirilmiştir. Sistemde eğitmen bilgisayarı sunucu olarak çalışmakta, öğrenciler ise masaüstü istemci uygulamasıyla bu sunucuya bağlanmaktadır. Her iki uygulama Python ve PySide6 ile geliştirilmiştir. Öğrenci uygulaması sunucuyu UDP broadcast ile ağda kendisi bulmakta, iletişim WebSocket üzerinden JSON mesajlarıyla sağlanmaktadır. Veriler SQLite veri tabanında saklanmış, sınav süresi sunucuda tutulmuş ve süre dolduğunda gönderilmemiş kâğıtlar kayıtlı cevaplarla otomatik olarak gönderilmiştir. Cevap anahtarı öğrenci bilgisayarına hiçbir zaman gönderilmemekte, bağlantı koptuğunda cevaplar öğrenci bilgisayarında yerel olarak yedeklenmektedir. Çoktan seçmeli sorular cevap anahtarına göre, klasik sorular ise normalize edilen cevabın kabul edilen cevaplarla karşılaştırılmasıyla otomatik olarak puanlanmaktadır. Sistem 317 otomatik testle ve aynı bilgisayarda çalışan 40 eş zamanlı sahte öğrenciyle yapılan yük testiyle sınanmıştır. Yük testinin iki senaryosunda da hata alan öğrenci olmamış, cevap kaydında ortalama yanıt süresi 5,9 ms ölçülmüş ve 40 kâğıdın tamamı puanlanmıştır.

**Anahtar Kelimeler—** elektronik sınav, yerel ağ, WebSocket, otomatik puanlama, masaüstü uygulama

## I. Giriş

Programlama derslerinde uygulanan klasik sınav yöntemleri çeşitli sorunlara yol açmaktadır. Kâğıt üzerinde ya da düz metin olarak yazılan kod derlenip çalıştırılamadığından, kodun gerçekten doğru çalışıp çalışmadığı sınanamamaktadır. Yalnızca çıktının doğruluğuna bakan değerlendirmeler de O(n²) çalışan bir çözümle O(n log n) çalışan bir çözümü aynı şekilde puanlamakta, kodun verimliliğini dikkate almamaktadır. Bu sorunları çözen çevrimiçi kod değerlendirme platformları ise internet bağlantısı gerektirmekte, bazıları ücretli olmakta ve öğrenci verilerini kurum dışındaki sunucularda tutmaktadır. Laboratuvar ağında yaşanan bir internet kesintisi, bu platformlarla yapılan bir sınavın akışını bozabilmektedir. Ayrıca soruların farklı sınavlarda yeniden kullanılması ve sonuçların sınıf bazında takip edilmesi için merkezi bir yapı bulunmamaktadır.

Bu projenin amacı, programlama laboratuvarı sınavlarının hazırlanmasını, uygulanmasını ve değerlendirilmesini internet bağlantısı gerektirmeden yerel ağ (LAN/WiFi) üzerinde gerçekleştiren bir masaüstü sistemi geliştirmektir. Sistem iki bileşenden oluşmaktadır. Eğitmen uygulaması hem eğitmen arayüzünü hem de sunucuyu tek bir programda barındırmaktadır; soru bankası ve sınavlar bu uygulamadan yönetilmekte, sınavlar öğrencilere bu uygulama üzerinden dağıtılmakta, cevaplar burada toplanıp puanlanmaktadır. Öğrenci uygulaması ise sunucunun adresi girilmeden onu ağda kendisi bulan, öğrencinin giriş yapıp sınavı çözdüğü istemcidir. Arayüzler PySide6 [1] ile geliştirilmiş, iki uygulama arasındaki iletişim WebSocket [2] ile sağlanmıştır. Tüm veriler eğitmen bilgisayarındaki bir veri tabanı dosyasında tutulduğundan öğrenci verileri kurum dışına çıkmamaktadır. Sistemin gerçek laboratuvar ortamında kullanılabilmesi hedeflendiğinden bağlantı kopması, uygulamanın kapanması ve sürenin dolması gibi durumlarda öğrenci cevaplarının kaybolmaması tasarımda öncelikli tutulmuştur.

Proje iki aşamada geliştirilmektedir. Vize aşamasında giriş ve oturum yönetimi, yerel ağ iletişimi, soru bankası, sınav oluşturma ve dağıtma, çoktan seçmeli ve klasik soruların çözülmesi, cevapların toplanması, otomatik puanlama ve sonuçların listelenmesi hedeflenmiştir. Final aşamasında ise C dilinde yazılan kodun derlenmesi, test senaryolarıyla doğrulanması ve kodun zaman ve yer karmaşıklığının ölçülerek puana katılması planlanmaktadır. Bu rapor vize aşamasını anlatmaktadır.

Raporun geri kalanı şu şekilde düzenlenmiştir. Bölüm II'de sistem mimarisi, ağ protokolü, veri tabanı tasarımı, süre yönetimi, otomatik puanlama ve dayanıklılık önlemleri, Bölüm III'te sınav sürecinin akış, sıralama ve sınıf diyagramları, Bölüm IV'te otomatik testler ve yük testi sonuçları, Bölüm V'te ise sonuçlar ve gelecek çalışmalar anlatılmaktadır.

## V. Sonuç

Bu çalışmada vize aşamasının sekiz isteri karşılanmıştır: (1) rol tabanlı giriş ve oturum yönetimi `auth.py` ile, (2) yerel ağ iletişimi `ws_server.py` ve `discovery.py` ile, (3) soru bankası ve kategori yönetimi `question_bank.py` ile, (4) sınav oluşturma `exam_admin.py` ile, eş zamanlı dağıtımı ise `exam_start` mesajıyla gerçekleştirilmiştir. (5) Sorular öğrenci uygulamasındaki `exam_view.py` ekranında çözülmekte, (6) cevaplar `exam_session.py` ile toplanıp olaylar `event_log.py` ile loglanmakta, (7) puanlama `grading.py` ile, (8) sonuçların listelenmesi `results.py` ile yapılmaktadır. Sistem internet bağlantısı gerektirmemektedir; 317 otomatik testin tamamı geçmiş, 40 öğrencilik yük testinde hata oluşmamış ve bağlantısı kopan öğrencilerin kayıtlı cevapları kaybolmamıştır. Süre sunucuda tutulduğundan sınav bittikten sonra gelen kayıt istekleri reddedilmiş, gönderilmemiş kâğıtlar otomatik olarak gönderilip puanlanmıştır. Alt+Tab ve Ctrl+Alt+Del gibi işletim sistemi kısayolları engellenememekte, yalnızca pencereden çıkış loglanmaktadır. Sistem okul laboratuvarında gerçek ağ ortamında denenmemiştir; yük testi tek bilgisayarda yapılmıştır. Final aşamasında gerçek laboratuvar ortamında deneme, C kodunun derlenmesi, test senaryolarıyla doğrulanması ve zaman/yer karmaşıklığı analizi eklenecek, bu sonuçlar öğrenci ve sınıf bazında raporlanacaktır.

---

## Notlar (rapora girmez)

### Kelime sayıları (`wc -w`, başlık hariç gövde metni)
- Özet: 161 kelime (hedef 150–200; Anahtar Kelimeler satırı hariç)
- I. Giriş: 326 kelime (hedef ~350)
- V. Sonuç: 153 kelime (hedef ~150)
- Dosya adları (`auth.py` vb.) birer kelime sayılmıştır.

### Sayılarla ilgili uyarı
- İstekte ve şablonda geçen **"ortalama 4,1 ms"** eski bir koşudandır. Güncel ölçüm `07_dayaniklilik_test.md` Tablo II'de:
  ortalama **5,9 ms** (iki senaryoda da), p95 12,8 / 12,9 ms, 0 hata, 40/40 puanlanan kâğıt. Özette 5,9 ms yazıldı.
- Şablondaki Tablo II de eski değerleri içeriyor (640 / ~10.800 / 4,1 / 4,6 / 12 / 52); Word'e aktarılırken
  `07_dayaniklilik_test.md`'deki tabloyla değiştirilmeli.

### Doğrulanan iddialar (dosya:satır)
- Problem tanımı maddeleri ve 8 vize isteri — proje dokümanı `2026-2027_Guz_Yazılım_Geliştirme_proje.pdf` ("Problem Tanımı", "Vize İsterleri").
- 317 otomatik test, 40 öğrenci, 0 hata, 5,9 ms, 40/40, bağlantısı kopan 8/8 öğrencide cevapların geri gelmesi — `docs/rapor/bolumler/07_dayaniklilik_test.md:11-29`.
- Rol tabanlı giriş: eğitmen uygulaması yalnız `role='instructor'` — `instructor_app/ui/login.py:116`; öğrenci uygulaması yalnız öğrenci (`NOT_STUDENT`) — `server/net/ws_server.py:485`; `authenticate` — `server/services/auth.py:32`.
- UDP keşif / WebSocket — `server/net/discovery.py`, `server/net/ws_server.py` (ayrıntı `02_mimari_ag_vt.md` notlarında).
- Soru ekleme/düzenleme/silme/kategori — `server/services/question_bank.py:295`, `:307`, `:342`, `:383-410`.
- Sınav oluşturma — `server/services/exam_admin.py:274`; sınıfa eş zamanlı `exam_start` — `server/net/ws_server.py:317-325`.
- Cevap kaydı ve gönderim — `server/services/exam_session.py:287`, `:301`; süre dolunca otomatik gönderim — `:130`.
- Log: `logs/events.log` (JSON Lines) + `event_logs` tablosu — `server/services/event_log.py:1-4`, `shared/config.py:34`.
- Puanlama — `server/services/grading.py:45`, `:75`; sonuç listesi — `server/services/results.py:183`, `instructor_app/ui/results.py`.
- Alt+Tab / Ctrl+Alt+Del engellenemez — `student_app/main.py:8-10`.
- Final: `evaluator/` dosyaları henüz yalnızca tek satırlık başlık (boş); bu yüzden metinde "hazır" denmedi, "eklenecektir" denildi.

### [DOĞRULANACAK]
- Metne doğrudan [DOĞRULANACAK] işareti gerekmedi; tüm sayılar `07_dayaniklilik_test.md`'den alındı.
- Sonuç'ta "internet bağlantısı gerektirmemektedir" denmiştir (tasarım iddiası). Okul laboratuvarında gerçek deneme yapılırsa
  Sonuç'taki "denenmemiştir; yük testi tek bilgisayarda yapılmıştır" sınırlaması güncellenmelidir.
- Windows'ta çalıştığı henüz denenmedi (`02_mimari_ag_vt.md` notu); bu bölümlerde Windows iddiası yok.
