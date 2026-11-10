# II. Yöntem — A, B, C (TASLAK, Kişi 2)

## A. Sistem Mimarisi

LabSınav, istemci-sunucu modeline göre tasarlanmıştır. Şekil 1'de görüldüğü gibi sistem, sunucu görevini de üstlenen eğitmen uygulaması ile ona yerel ağ üzerinden bağlanan öğrenci uygulamalarından oluşur. Sunucu, arayüzün donmaması için kendi asyncio olay döngüsüyle ayrı bir thread'de çalıştırılmaktadır. Sunucu thread'inde oluşan olaylar `ServerBridge` sınıfındaki Qt sinyalleri üzerinden yayımlanır; Qt bu sinyallere bağlı fonksiyonları ana thread'de çalıştırdığı için arayüz güvenli biçimde güncellenir. Veri tabanı işlemleri `asyncio.to_thread` ile ayrıca arka plana aktarıldığından sunucunun mesaj alma döngüsü bu işlemlerin bitmesini beklemez. Öğrenci tarafında Qt'nin `QWebSocket` sınıfı kullanılmakta olup bu sınıf Qt olay döngüsüyle çalıştığından ayrı thread gerektirmemektedir.

Sistem üç katmandan oluşur: arayüz (`instructor_app`, `student_app`), servisler (`server/services`) ve veri tabanı (`server/db`). Arayüz kodu veri tabanına doğrudan sorgu yazmaz; tüm işlemler servis fonksiyonları aracılığıyla yapılır.

Kullanılan teknolojiler ve seçilme nedenleri şunlardır:

- **Python 3.11+:** Ekibin ortak bildiği, ağ ve veri tabanı kütüphaneleri zengin bir dildir.
- **PySide6 (≥ 6.10) [1]:** Aynı kodla çok platformlu masaüstü arayüzü ve thread'ler arası güvenli sinyal mekanizması sağlar.
- **websockets (≥ 13):** asyncio tabanlı olduğundan çok sayıda eş zamanlı bağlantı az kodla yönetilebilir.
- **SQLAlchemy (≥ 2.0) + SQLite:** Tablolar Python sınıflarıyla tanımlanır, SQL elle yazılmaz; SQLite ayrı kurulum gerektirmez.
- **pydantic (≥ 2.6):** Gelen her mesajın alanları ve tipleri otomatik olarak doğrulanır.
- **bcrypt (≥ 4.1):** Şifreler geri çevrilemeyen, tuzlanmış özetler olarak saklanır.
- **openpyxl (≥ 3.1):** Öğrenci listeleri Office kurulumu gerekmeden Excel'den içe aktarılır, sonuçlar ve loglar Excel'e aktarılır.

## B. Ağ İletişimi ve Protokol

Öğrenci uygulaması açıldığında sunucu UDP broadcast ile aranır: 50555 numaralı porta `LABSINAV_DISCOVER` içerikli bir paket gönderilir. Eğitmen bilgisayarında çalışan keşif dinleyicisi `{"service": "labsinav", "host": ..., "port": 8765}` biçiminde cevap verir; öğrenci uygulaması, cevabın geldiği IP adresini ve cevaptaki portu sunucu adresi olarak kullanır. Her denemede cevap 2 saniye beklenir; sunucu bulunamazsa arama 3 saniyede bir otomatik olarak tekrarlanır. Ağ broadcast'e izin vermiyorsa eğitmen bilgisayarının IP adresi giriş ekranına elle yazılabilir.

Bağlantı, 8765 numaralı port üzerinde WebSocket [2] ile kurulur. HTTP'de istemci sormadan sunucu mesaj gönderemez; bu sistemde ise sunucunun sınıftaki tüm öğrencilere aynı anda mesaj itebilmesi (sınav başladı, süre uzatıldı, sınav bitti) gerekmektedir. WebSocket tek ve sürekli açık bir bağlantı üzerinden iki yönlü iletişim sağladığı için tercih edilmiştir.

Her mesaj `{type, id, payload}` alanlarından oluşan bir JSON zarfıdır. Öğrenci uygulamasının ürettiği `id`, sunucu cevabında aynen döndürülür; böylece cevap hangi isteğe aitse onunla eşleştirilir:

```json
{"type": "save_answer", "id": "a1b2c3d4",
 "payload": {"exam_id": 3, "question_id": 12, "selected_option_id": 41}}
```

Güvenlik için üç önlem alınmıştır. Birincisi, öğrenciye giden sorular ayrı bir `QuestionForStudent` modeliyle gönderilir; bu modelde doğru şık, kabul edilen cevaplar gibi cevap anahtarı alanları bulunmaz ve modele tanımsız alan eklenmesi engellenmiştir. İkincisi, süreyi sunucu belirler (bkz. Bölüm II-D). Üçüncüsü, şifreler bcrypt [3] ile özetlenerek saklanır. Tablo I'de temel mesajlar verilmiştir.

**Tablo I. Temel protokol mesajları**

| Mesaj | Yön | Açıklama |
|---|---|---|
| `login` | İ → S | Öğrenci numarası ve şifreyle giriş isteği |
| `login_ok` | S → İ | Giriş başarılı; öğrenci adı ve sınıfı |
| `exam_start` | S → İ | Sorular, bitiş zamanı ve kayıtlı cevaplar |
| `save_answer` | İ → S | Değişen cevabın otomatik kaydı (2 sn gecikmeli) |
| `submit` | İ → S | Öğrencinin sınavı bitirmesi |
| `exam_end` | S → İ | Süre doldu veya eğitmen sınavı durdurdu |
| `exam_update` | S → İ | Eğitmen süre ekledi; yeni bitiş zamanı |
| `error` | S → İ | Hata kodu ve Türkçe açıklama |

## C. Veri Tabanı Tasarımı

Veri tabanı olarak SQLite seçilmiştir; ayrı bir veri tabanı sunucusu kurulumu gerektirmez, tüm veriler tek bir dosyada (`data/labsinav.db`) tutulur ve dosya kopyalanarak kolayca yedeklenebilir.

Veri modeli Bölüm III'te sınıf diyagramı olarak verilmiştir. `users` tablosu eğitmen ve öğrencileri rolleriyle tutar; öğrenciler `classes` tablosundaki bir sınıfa bağlıdır. Sorular `questions` tablosunda tutulur ve `categories` tablosundaki bir kategoriye bağlanabilir; çoktan seçmeli soruların şıkları `question_options`, klasik sorularda kabul edilen cevaplar ise `classic_accepted_answers` tablosunda bulunur. `exams` tablosu bir sınıfa ait sınavları, `exam_questions` ise sınavla soruları sıra ve puan bilgisiyle eşleştirir. Her öğrencinin bir sınavdaki kâğıdı `submissions`, soru bazındaki cevapları `answers` tablosunda tutulur; bir öğrenci aynı sınav için tek kâğıda sahip olabilir. Olaylar `event_logs` tablosuna yazılır. Final aşaması için `test_cases` ve `code_results` tabloları hazırdır.

Veri tabanı WAL modunda açılır; böylece yazma sürerken okuma yapılabilir [4]. Ayrıca yazan tüm işlemler `write_session()` ile tek bir kilit altında sırayla yapılır; bu sayede 40 öğrenci aynı anda cevap kaydettiğinde "database is locked" hatası oluşmaz. Bir sınavda kullanılmış soru silinmez, `is_archived` ile arşivlenir; böylece eski sınav sonuçları bozulmaz.

---

## Notlar (rapora girmez)

**Kelime sayıları** (`wc -w`, başlıklar hariç): A = 239 (hedef ~200; uzunsa QWebSocket cümlesi çıkarılabilir, −22), B = 215 (Tablo I hariç; JSON örneği de hariç 202, hedef ~250), C = 157 (hedef ~150).

**Koddan doğrulanan sabitler / iddialar:**

- WebSocket portu 8765 — `shared/config.py:9`; sunucu `0.0.0.0` dinler — `server/net/ws_server.py:135`
- Keşif portu 50555 — `shared/config.py:10`; keşif mesajı `LABSINAV_DISCOVER` — `shared/config.py:11`; servis adı `labsinav` — `shared/config.py:12`
- Keşifte cevap bekleme 2 sn — `shared/config.py:13`
- Keşif cevabı `{service, host, port}` — `server/net/discovery.py:60`; istemci cevabın geldiği adresi kullanır — `server/net/discovery.py:103-105`
- 3 sn'de bir tekrar — `student_app/main.py:60`, `student_app/main.py:171`; keşif ayrı QThread'de — `student_app/main.py:72-78`
- IP'yi elle girme — `student_app/ui/login.py:23`, `student_app/ui/login.py:69`; keşif portu açılamazsa uygulama yine açılır — `instructor_app/main.py:172-178`
- Sunucu ayrı thread + asyncio — `server/net/ws_server.py:3`, `server/net/ws_server.py:158-165`, `server/net/ws_server.py:212-213`; DB işleri `asyncio.to_thread` ile — `server/net/ws_server.py:9`, `server/net/ws_server.py:318`
- Signal köprüsü — `instructor_app/server_bridge.py:1-5`, `instructor_app/server_bridge.py:14-19`
- Öğrenci istemcisi QWebSocket — `student_app/net/client.py:3`, `student_app/net/client.py:24`
- Zarf `{type, id, payload}` — `shared/protocol.py:72-75`; `id` üretimi — `shared/protocol.py:218-220`; tanımsız alan yasağı (`extra="forbid"`) — `shared/protocol.py:67-69`
- `QuestionForStudent` / `OptionForStudent` (cevap anahtarı yok) — `shared/protocol.py:128-145`
- Sunucunun ittiği mesajlar: `exam_start` sınıfa — `server/net/ws_server.py:325-331`, `exam_update` — `server/net/ws_server.py:333-346`, `exam_end` — `server/net/ws_server.py:375-377`
- `TIME_UP` — `shared/protocol.py:52`; süre kontrolü 1 sn'de bir — `server/net/ws_server.py:68`
- Otomatik kayıt gecikmesi 2 sn — `shared/config.py:18`; ping 10 sn — `shared/config.py:17`
- bcrypt (12 tur) — `server/services/auth.py:3`, `server/services/auth.py:19-20`, `shared/config.py:27`
- WAL — `server/db/session.py:39`; tek yazma kilidi — `server/db/session.py:31`, `server/db/session.py:117-125`
- DB dosyası `data/labsinav.db` — `shared/config.py:32`
- Tablolar — `server/db/models.py`: classes:62, users:71, categories:89, questions:96, question_options:125, classic_accepted_answers:139, test_cases:170, exams:188, exam_questions:211, submissions:225 (UNIQUE:227), answers:249, code_results:276, event_logs:297
- `is_archived` — `server/db/models.py:107`; kullanılmış soruyu arşivleme — `server/services/question_bank.py:342-350`
- openpyxl: öğrenci içe aktarma — `server/services/import_export.py:267`, `server/services/import_export.py:340`; sonuç dışa aktarma — `server/services/import_export.py:52`; log dışa aktarma — `server/services/event_query.py:170`
- Sürümler — `requirements.txt`; Python 3.11+ — `README.md:15`

**[DOĞRULANACAK]:** Windows'ta çalıştığı henüz denenmedi (P8 planlı, `docs/PROMPTLAR.md:45`). Windows testi yapılmadan rapor teslim edilirse PySide6 maddesindeki "Windows ve Linux'ta" ifadesi gözden geçirilmeli.
