# II. Yöntem — D, E (TASLAK, Kişi 3)

## D. Sınav Yürütme ve Süre Yönetimi

Eğitmen sınavı başlattığında sınavın durumu "running" yapılır ve bitiş zamanı (`ends_at`), başlangıç anına sınav süresi eklenerek veri tabanına yazılır. Ardından sınavın atandığı sınıfta o anda bağlı olan tüm öğrencilere `exam_start` mesajı gönderilir. Sınav başladıktan sonra giriş yapan öğrenciye de aynı mesaj giriş sırasında iletilir.

Cevaplar her değişiklikte otomatik olarak kaydedilir. Kayıt isteği 2 saniyelik gecikmeyle (debounce) gönderilir: her yeni değişiklikte zamanlayıcı baştan başlatılır ve istek, öğrenci 2 saniye boyunca değişiklik yapmadığında gönderilir. Soru değiştirildiğinde ve sınav bitirilirken bekleyen kayıtlar beklenmeden gönderilir.

Süre sunucuda tutulur ve süresi dolan sınavlar saniyede bir kontrol edilir. Süre geçtikten sonra gelen kayıt ve gönderim istekleri `TIME_UP` hatasıyla reddedilir. Öğrenci uygulaması, sunucudan gelen `server_now` değerini kendi monotonik saatiyle birlikte saklar; böylece geri sayım öğrenci bilgisayarının saatinden bağımsız olarak sunucu saatine göre gösterilir.

Süre dolduğunda sınavı göndermemiş öğrencilerin kâğıtları kayıtlı cevaplarıyla otomatik olarak gönderilir, `auto_submitted` olarak işaretlenir ve arka planda puanlanır; öğrencilere `exam_end` mesajı yollanır (Algoritma 1). Bitiş zamanı veri tabanında tutulduğundan, eğitmen uygulaması kapalıyken süresi dolan sınav uygulama açıldığında ilk kontrolde bitirilir.

Bağlantısı kopan öğrenci tekrar giriş yaptığında `exam_start` kayıtlı cevaplarla (`saved_answers`) yeniden gönderilir ve öğrenci kaldığı yerden devam eder. Aynı hesapla ikinci bir yerden giriş yapılırsa eski bağlantı kapatılır ve `duplicate_session` olayı loglanır.

## E. Otomatik Puanlama

Kâğıtlar, öğrenci sınavı gönderdiğinde ya da sınav otomatik olarak bitirildiğinde puanlanır. Çoktan seçmeli sorularda seçilen şık doğruysa sorunun sınavdaki puanı, değilse 0 verilir. Klasik sorularda öğrenci cevabı ve kabul edilen cevaplar önce normalize edilir: metin Unicode NFC biçimine getirilir, Türkçe kurallarına göre küçük harfe çevrilir, baştaki, sondaki ve tekrarlanan boşluklar temizlenir, sondaki noktalama işaretleri atılır. Örneğin "  İSTANBUL.  " cevabı "istanbul" biçimine dönüştürülür. Normalize edilmiş cevap kabul edilen cevaplardan biriyle eşleşirse tam puan verilir (Algoritma 2).

Ayrı bir normalize işlemine gerek duyulmasının nedeni, Python'un `str.lower()` fonksiyonunun Türkçe harfleri doğru çevirmemesidir: "İ" harfi, üzerinde ayrı bir birleşik nokta işareti kalan bir "i" olarak (iki karakter), "I" harfi ise "ı" yerine "i" olarak çevrilir. Bu durumda "İSTANBUL" cevabı "istanbul" ile eşleşmez. Bu nedenle önce "I" → "ı" ve "İ" → "i" dönüşümü yapılmakta, ardından `lower()` uygulanmaktadır.

Eğitmen, klasik soruların puanını sonuç ekranından elle değiştirebilir. Elle verilen puan `is_manual` alanıyla işaretlenir ve yeniden puanlamada korunur. Çoktan seçmeli soruların puanı elle değiştirilemez.

## Kelime sayıları
- D: 197 kelime (hedef ~200)
- E: 154 kelime (hedef ~150)
- Ölçüm: `wc -w` (başlık hariç, gövde metni); Algoritma 1 ve 2 Prompt 5'te ayrı yazılacak.

## Doğrulanan davranışlar (dosya:satır)
- Başlatma: running + ends_at = şimdi + süre — `server/services/exam_session.py:97-105`
- Sınıftaki bağlı öğrencilere exam_start (arka planda) — `server/net/ws_server.py:317-331`, sınıf filtresi `:306-311`
- Sonradan giren / yeniden bağlanan öğrenciye exam_start — `server/net/ws_server.py:501-507`, `server/services/exam_session.py:193-212`
- saved_answers ile exam_start — `server/services/exam_session.py:227-251`, `:272-280`
- Debounce 2 sn — `shared/config.py:18`, `student_app/ui/exam_view.py:83-86`, `:350`; soru değişince/bitirirken hemen gönderim — `exam_view.py:306-307`, `:471`
- Saniyede bir kontrol — `server/net/ws_server.py:68`, `:352-365`
- TIME_UP reddi (`now >= ends_at` veya finished) — `server/services/exam_session.py:321-322`, `:373-374`; rejected_late logu — `server/net/ws_server.py:554-564`
- İstemci saati: server_now + monotonic — `student_app/net/server_clock.py:23-35`; exam_start/exam_update/pong'da güncelleme — `student_app/net/client.py:278-279`; geri sayım — `student_app/ui/exam_view.py:414-425`
- Otomatik gönderim (auto_submitted=True, submitted_at=ends_at) — `server/services/exam_session.py:130-163`
- auto_submitted logu, exam_end, arka plan puanlama — `server/net/ws_server.py:367-379`
- Uygulama kapalıyken dolan süre açılışta — `server/services/exam_session.py:133`, ticker açılışta başlar `server/net/ws_server.py:223`; açılışta puanlanmamış kâğıtlar — `ws_server.py:224`, `:398-407`, `server/services/grading.py:121-132`
- Duplicate session: eski bağlantı 4001 ile kapatılır + log — `server/net/ws_server.py:64-65`, `:277-293`
- Arayüze Signal ile bildirim — `instructor_app/server_bridge.py:13-37`
- mcq puanlama — `server/services/grading.py:62-63`, `:94-101`; puan exam_questions'tan — `grading.py:185-190`
- Normalize (NFC, turkish_lower, boşluk, noktalama) — `server/services/grading.py:26-27`, `:45-57`; örnek `:48`; classic eşleşme — `:64-67`
- turkish_lower — `server/services/question_bank.py:450-452`
- is_manual korunur — `server/services/grading.py:88-90`, `:139-154`; sadece classic/code elle — `:30`, `:175-176`; arayüz — `instructor_app/ui/result_detail.py:160`, yeniden puanla `instructor_app/ui/results.py:434`


**[DOĞRULANACAK]:** Yok — metindeki her iddia koddan doğrulandı. Not: istemci saat düzeltmesi ağ gecikmesini (RTT) hesaba katmaz; bu ayrıntı metne yazılmadı.
