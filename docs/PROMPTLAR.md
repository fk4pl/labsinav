# LabSınav — Claude Code Prompt Planı (Vize)

**Pilot:** ____ (Claude Code tek onda).
**Modül sahipleri:** A = sunucu/ağ · B = eğitmen ekranları · C = öğrenci ekranları · D = puanlama/sonuçlar
(İsimleri buraya yazın: A = ____ · B = ____ · C = ____ · D = ____)

Kodu pilot yazdırır, ama **her promptun sonucunu o modülün sahibi kontrol eder, test eder ve anlar.**
Demoda hoca herkese kendi kısmını sorabilir.

---

## 0. Kurulum (bir kerelik, pilot)

1. Python 3.11+ ve Git kurulu olsun. Proje için GitHub'da boş bir repo aç (örn. `labsinav`), herkesi ekle.
2. Repoyu klonla, **CLAUDE.md dosyasını kök klasöre koy**, commit + push.
3. Klasörde terminal aç ve `claude` yaz.

### Claude Code kullanım kuralları
- **Her promptu Plan modunda başlat:** `Shift+Tab` ile plan moduna geç → promptu yapıştır →
  Claude planını gösterir → mantıklıysa onayla. Bu, yanlış yöne gidip limit yakmayı önler.
- **Her prompt bitince:** uygulamayı kendin bir kere çalıştır → çalışıyorsa
  `değişiklikleri anlamlı bir mesajla commit et ve push et` yaz.
- **Her yeni promptta `/clear`** yaz (eski konuşma bağlamı temizlensin; CLAUDE.md yine okunur, limit daha az gider).
- **Hata çıkarsa:** hata mesajını olduğu gibi yapıştır + "şunu yaparken oldu" de. Kendin düzeltmeye çalışma.
- **Limit dolarsa:** bekleme süresinde ekip test eder, hata listesi hazırlar; limit açılınca toplu düzeltme promptu atılır.
- Promptlar büyük ve tek parça tasarlandı (az mesaj = az limit). Bölme.

### Paralel çalışma (opsiyonel, hızlandırmak için)
P2 ve P3 birbirinden bağımsızdır; iki terminalde aynı anda çalıştırılabilir:
```
git worktree add ../labsinav-ogrenci -b ogrenci
```
Birinci terminal `labsinav/` (P2), ikinci terminal `labsinav-ogrenci/` (P3). İkisi bitince:
`ogrenci branch'ini main'e merge et, çakışma varsa çöz` promptu.

---

## Takvim

| Gün | Prompt | Sahibi kontrol eder | Claude Code'u olmayanlar o gün |
|---|---|---|---|
| 1 | P0 İskelet | Herkes | Soru içeriği yazmaya başla, rapor iskeleti |
| 2 | P1 Sunucu: sınav oturumu + log | A | Okul bilgisayarı/WiFi ön denemesi |
| 3 | P2 Eğitmen: giriş + soru bankası | B | P0-P1'i test et |
| 3 | P3 Öğrenci: istemci + sınav ekranı | C | |
| 4 | P4 Puanlama + sonuçlar + Excel | D | P2-P3'ü test et |
| 5 | P5 Eğitmen: sınav oluşturma + canlı panel + loglar | B | Akış diyagramı |
| 6 | P6 Dayanıklılık + sınav modu + öğrenci içe aktarma | C, D | |
| 7 | P7 Entegrasyon + yük testi | A | Uçtan uca elle test |
| 8–9 | P8 Paketleme (.exe) + laboratuvar testi + hata düzeltme | Herkes | Labda gerçek deneme |
| 10 | P9 Demo hazırlığı | Herkes | Sunum provası |

---

## P0 — Proje iskeleti (Gün 1)

```
CLAUDE.md dosyasını dikkatlice oku. Projenin iskeletini kuracağız; amaç yarından itibaren
her modülün üstüne inşa edilebileceği, uçtan uca çalışan sağlam bir temel.

Yapılacaklar:
1. requirements.txt (PySide6, websockets, SQLAlchemy>=2, pydantic>=2, bcrypt, openpyxl, pytest),
   .gitignore (data/, logs/, __pycache__/, .venv/, dist/, build/, *.spec), README.md (kurulum + çalıştırma, Türkçe).
2. CLAUDE.md'deki klasör yapısının tamamını oluştur (__init__.py dosyaları dahil).
3. shared/config.py: WS_PORT=8765, DISCOVERY_PORT=50555, DB ve log yolları, diğer sabitler.
4. shared/protocol.py: Envelope modeli, CLAUDE.md'deki TÜM mesaj tipleri için pydantic modelleri,
   encode/decode yardımcıları. İstemciye giden soru modelleri (QuestionForStudent, OptionForStudent)
   cevap anahtarı alanı İÇERMEYECEK.
5. server/db/models.py + session.py: CLAUDE.md'deki şemanın tamamı (FİNAL tabloları dahil, questions'a
   is_archived ekle), SQLite WAL modu, init_db().
6. scripts/seed.py: eğitmen (egitmen/egitmen123), "1. Öğretim A" ve "1. Öğretim B" sınıfları,
   30 öğrenci (2026001-2026030, şifre = öğrenci no, isimler gerçekçi Türkçe), 3 kategori
   (Diziler, İşaretçiler, Döngüler ve Koşullar), C dili hakkında gerçekçi 12 çoktan seçmeli + 8 klasik
   soru (doğru cevaplarıyla), 10 soruluk bir taslak sınav (süre 20 dk). Tekrar çalıştırılınca veriyi sıfırlasın.
7. server/services/auth.py: authenticate(username, password) -> User | None (bcrypt).
8. server/net/ws_server.py: asyncio websockets sunucusu, ayrı thread'de başlatan start_server() fonksiyonu;
   login mesajını işlesin (login_ok / error), bağlı kullanıcıları tutsun, ping/pong'a cevap versin.
   Qt tarafına olay iletmek için basit bir callback/observer arayüzü (on_student_connected,
   on_student_disconnected). Mesaj yönlendirme bir dict ile (type -> handler) yapılsın ki
   sonradan yeni mesaj tipleri kolay eklensin.
9. server/net/discovery.py: UDP broadcast'e sunucu IP ve portuyla cevap veren dinleyici +
   istemcinin kullanacağı discover_server(timeout=2) fonksiyonu.
10. instructor_app/main.py: sunucuyu ve discovery'yi başlatan ana pencere; sekmeler: Soru Bankası, Sınavlar,
    Canlı Panel, Sonuçlar, Öğrenciler, Loglar (şimdilik boş placeholder); durum çubuğunda
    "Sunucu: 192.168.x.x:8765 • Bağlı öğrenci: N". Görünüm temiz ve modern olsun (tutarlı bir QSS teması).
11. student_app/main.py + student_app/net/client.py: açılışta sunucuyu otomatik bulsun (bulamazsa IP girme alanı),
    giriş ekranı (öğrenci no + şifre), başarılı girişte "Merhaba <ad>, sınavın başlaması bekleniyor" ekranı.
    QWebSocket kullan.
12. tests/: protocol encode/decode, auth ve seed için pytest testleri.

Kabul kriteri: `python -m scripts.seed` çalışır; eğitmen uygulaması açılır; aynı bilgisayarda iki
öğrenci uygulaması açılıp farklı öğrencilerle giriş yapar; eğitmen durum çubuğunda "Bağlı öğrenci: 2"
görünür; yanlış şifrede Türkçe hata mesajı çıkar; pytest geçer.

Önce planını göster, onaylayınca başla. Bitince nasıl test edeceğimi adım adım yaz.
```

**Test (herkes):** README'deki adımlarla kendi bilgisayarında çalıştırabiliyor mu? Bir arkadaşının
bilgisayarındaki öğrenci uygulaması, aynı WiFi'daki eğitmen uygulamasını otomatik buluyor mu?

---

## P1 — Sunucu: sınav oturumu ve loglama (Gün 2, sahibi A)

```
CLAUDE.md'yi oku. Şimdi sunucunun sınav yürütme mantığını yazacağız (server/services/exam_session.py,
server/services/event_log.py ve ws_server.py'deki handler'lar).

1. exam_session.py:
   - start_exam(exam_id): sınavı 'running' yap, started_at/ends_at ayarla, o sınıfın bağlı tüm öğrencilerine
     exam_start gönder (soruların sırası exam_questions.order_index'e göre; cevap anahtarı YOK).
     Sınav başladıktan sonra giriş yapan öğrenci de exam_start alsın.
   - save_answer: answers tablosuna upsert; süre dolmuşsa TIME_UP hatası; submitted ise ALREADY_SUBMITTED.
   - submit: submission'ı 'submitted' yap, submitted_at ve ip kaydet, submit_ok dön. Puanlama için
     grading modülündeki grade_submission(submission_id) fonksiyonunu çağır (D yazacak; şimdilik
     server/services/grading.py içinde boş bir stub oluştur).
   - stop_exam(exam_id) ve extend_exam(exam_id, minutes): eğitmen sınavı erken bitirebilsin veya süre ekleyebilsin
     (süre eklenince öğrencilere güncel ends_at gitsin — bunun için protokole `exam_update {ends_at}`
     mesajını ekle).
   - Süre dolunca: gönderilmemiş tüm submission'ları kayıtlı cevaplarla otomatik gönder (auto_submitted=True),
     herkese exam_end gönder, sınavı 'finished' yap. Uygulama kapanıp açılsa bile 'running' sınav
     ends_at'e göre devam etsin.
   - Yeniden bağlanma: gönderilmemiş aktif sınavı olan öğrenci giriş yaparsa exam_start'ı saved_answers ile gönder.
   - Aynı öğrenci ikinci kez bağlanırsa eskisini kapat, duplicate_session logla.
2. event_log.py: log_event(event, username, exam_id, ip, detail) → logs/events.log (JSON Lines) + event_logs tablosu.
   CLAUDE.md'deki tüm olayları ilgili yerlerde logla.
3. Eş zamanlılık: 40 öğrenci aynı anda kaydettiğinde SQLite kilitlenmesin (tek bir yazma kuyruğu veya lock).
4. Eğitmen arayüzünün dinleyebilmesi için observer olayları: student_connected, student_disconnected,
   answer_saved(student, exam, answered_count), submitted, exam_finished.
5. tests/test_exam_session.py: süre dolunca reddetme, otomatik gönderim, yeniden bağlanma, cevap anahtarının
   istemciye gitmediği, iki kez submit edilememe testleri (zamanı mock'la).

Protokole eklediğin her şeyi CLAUDE.md'deki protokol tablosuna da ekle ve "ORTAK DOSYA DEĞİŞTİ" kuralına uy.
Önce planını göster.
```

**Test (A):** Testler geçiyor mu? `pytest -v` çıktısını oku; her testin neyi kontrol ettiğini Claude Code'a açıklat.

---

## P2 — Eğitmen: giriş + soru bankası (Gün 3, sahibi B)

```
CLAUDE.md'yi oku. Eğitmen uygulamasının giriş ekranını ve Soru Bankası sekmesini yazacağız.
İş mantığı server/services/question_bank.py'de, arayüz instructor_app/ui/ altında olsun.

1. instructor_app/ui/login.py: uygulama açılınca önce eğitmen giriş penceresi (sadece role='instructor'
   girebilir). Şifre değiştirme seçeneği (ayarlar menüsünden).
2. Soru Bankası sekmesi:
   - Tablo: no, tür (Test/Klasik/Kod), kategori, soru metninin ilk 80 karakteri, puan, son düzenleme.
   - Üstte filtreler: kategori, tür, metin arama (anlık filtre). Arşivlenenleri göster seçeneği.
   - Ekle/Düzenle diyaloğu: tür seçimi; soru metni (çok satırlı, kod parçası içerebilir — eşit genişlikli
     yazı tipi seçeneği); kategori; varsayılan puan.
     * Test: 2-6 şık, dinamik ekle/sil, tam olarak bir doğru şık (radio). Boş şık olamaz.
     * Klasik: bir veya birden fazla kabul edilen cevap (liste).
     * Kod türü şimdilik pasif ve "Final'de eklenecek" ipucuyla gösterilsin.
   - Silme: soru hiçbir sınavda kullanılmadıysa sil; kullanıldıysa arşivle ve kullanıcıya bunu açıkla.
   - Çoğalt (kopyasını oluştur) butonu.
   - Kategori yönetimi (ekle/yeniden adlandır/sil — içinde soru varsa silinemez).
   - Soru önizleme: öğrencinin göreceği hâliyle.
3. Doğrulama hataları diyalog içinde kırmızı ve Türkçe gösterilsin, kaydetme engellensin.
4. tests/test_question_bank.py: ekleme, düzenleme, arşivleme, doğrulama testleri.

Arayüz temiz ve tutarlı olsun (P0'daki QSS temasını kullan). Önce planını göster.
```

**Test (B):** 5 farklı soru ekle/düzenle/sil. Boş şıkla kaydetmeyi dene. Sınavda kullanılan soruyu silmeyi dene.

---

## P3 — Öğrenci: istemci + sınav ekranı (Gün 3, sahibi C)

```
CLAUDE.md'yi oku. Öğrenci uygulamasının ağ istemcisini ve sınav ekranını yazacağız (student_app/).

1. student_app/net/client.py → ServerClient(QObject):
   - QWebSocket sarmalayıcı; her mesaj tipi için Qt Signal (exam_started, exam_updated, exam_ended,
     save_confirmed, submit_confirmed, error_received, connection_changed).
   - request/response eşleştirme (id ile), 10 sn'de bir ping.
   - Bağlantı koparsa artan bekleme süreleriyle otomatik yeniden bağlan ve kayıtlı bilgilerle tekrar giriş yap.
   - Sunucu saat farkını (server_now) hesapla; geri sayım bu farka göre olsun.
2. Sınav ekranı (student_app/ui/exam_view.py):
   - Üst bar: sınav adı, öğrenci adı/no, büyük geri sayım (son 5 dk turuncu, son 1 dk kırmızı;
     5. ve 1. dakikada uyarı bildirimi), bağlantı durumu ikonu, "Kaydedildi ✓ / Kaydediliyor…" göstergesi.
   - Sol panel: soru numaraları ızgarası — cevaplanmış / cevaplanmamış / "sonra bakacağım" işaretli
     farklı renklerde; tıklayınca o soruya git.
   - Orta: soru metni (kod parçaları eşit genişlikli fontla), Test için radio şıklar, Klasik için metin alanı.
     Önceki/Sonraki butonları, "İşaretle" butonu.
   - Her cevap değişikliğinde 2 sn debounce ile save_answer gönder.
   - "Sınavı Bitir": cevaplanmamış soruları listeleyen onay diyaloğu → submit.
   - Gönderim sonrası ekran: "Sınavın gönderildi — <saat>". exam_end veya TIME_UP gelirse bu ekrana otomatik geç.
   - exam_start'taki saved_answers ile ekran doldurulsun (yeniden bağlanınca kaldığı yerden devam).
3. Sunucu olmadan arayüzü geliştirip denemek için: `python -m student_app.main --demo` örnek bir
   exam_start JSON'u yükleyip ekranı açsın (cevaplar sadece yerelde tutulur).
4. Yazı boyutu büyüt/küçült (Ctrl + / Ctrl -).

Önce planını göster.
```

**Test (C):** `--demo` ile tüm ekranı dene. Sonra gerçek sunucuyla: sınav ortasında WiFi'ı kapat-aç → cevaplar duruyor mu?

---

## P4 — Puanlama + sonuçlar + Excel (Gün 4, sahibi D)

```
CLAUDE.md'yi oku. Puanlamayı ve Sonuçlar sekmesini yazacağız.
Servisler: server/services/grading.py, results.py, import_export.py. Arayüz: instructor_app/ui/results.py.

1. grading.py:
   - grade_submission(submission_id): her cevabı CLAUDE.md'deki kurallara göre puanla (is_correct, points_awarded),
     total_score'u güncelle. Puan exam_questions.points'ten gelir.
   - normalize_answer(text): baş/son boşluk, çoklu boşluk, büyük/küçük harf (Türkçe İ/ı, I/i doğru çevrilmeli),
     sondaki noktalama.
   - regrade_exam(exam_id): cevap anahtarı değişirse tüm sınavı yeniden puanla.
   - set_manual_points(answer_id, points): eğitmenin elle puan vermesi (0 ile soru puanı arasında), toplamı güncelle.
2. results.py: sınav özeti (katılımcı sayısı, ortalama, medyan, en yüksek, en düşük, standart sapma),
   öğrenci bazlı liste (no, ad, puan, doğru/yanlış/boş sayısı, gönderim saati, otomatik gönderildi mi),
   soru bazlı başarı oranı (her sorunun doğru yapılma yüzdesi; test sorularında her şıkkın kaç kez seçildiği).
3. Sonuçlar sekmesi:
   - Sınav seçici, üstte özet kartları (ortalama, medyan, en yüksek, en düşük, katılım).
   - Öğrenci tablosu (sıralanabilir). Çift tıklayınca öğrenci detayı: her soru, verdiği cevap, doğru cevap,
     aldığı puan; klasik sorularda puanı elle değiştirme.
   - "Soru Analizi" alt sekmesi: soru bazlı başarı oranları ve basit bir çubuk grafik (QtCharts veya QPainter).
   - "Excel'e Aktar": öğrenci listesi + özet + soru analizi ayrı sayfalarda, düzgün biçimlendirilmiş .xlsx.
4. tests/test_grading.py: Türkçe normalize ("İSTANBUL" == "istanbul"), boş cevap, elle puan, regrade testleri.

Önce planını göster.
```

**Test (D):** Seed sınavını 3 farklı öğrenciyle çöz, sonuçları elle hesapladığınla karşılaştır. Excel dosyasını aç.

---

## P5 — Eğitmen: sınav oluşturma + canlı panel + loglar (Gün 5, sahibi B)

```
CLAUDE.md'yi oku. Eğitmen uygulamasında Sınavlar, Canlı Panel ve Loglar sekmelerini yazacağız.
İş mantığı server/services/exam_admin.py'de (sınav CRUD); başlatma/durdurma için exam_session.py'yi kullan.

1. Sınavlar sekmesi:
   - Liste: sınav adı, sınıf, soru sayısı, toplam puan, süre, durum (Taslak/Devam ediyor/Bitti).
   - Oluştur/Düzenle: ad, sınıf, süre (dk); solda soru bankası (filtreli), sağda sınavdaki sorular;
     ekle/çıkar, sürükle-bırak veya yukarı/aşağı ile sırala, soru başına puanı değiştir; toplam puan anlık görünsün.
     "Rastgele N soru ekle (kategori seçerek)" butonu.
   - Çoğalt, sil (sadece taslak).
   - "Başlat": onay diyaloğu (sınıf, bağlı öğrenci sayısı / sınıf mevcudu gösterilsin) → start_exam → Canlı Panel'e geç.
   - Bitmiş sınav düzenlenemez (sadece görüntülenir ve çoğaltılabilir).
2. Canlı Panel sekmesi:
   - Büyük geri sayım, sınav adı; "+5 dk", "+10 dk" ve "Sınavı Bitir" (onaylı) butonları.
   - Sınıfın tüm öğrencileri tablosu: no, ad, durum (Çevrimdışı / Bağlı / Sınavda / Gönderdi) renkli rozetle,
     cevaplanan/toplam soru, son etkinlik saati, pencereden çıkma sayısı, IP.
   - Üstte sayaçlar: bağlı, sınavda, gönderdi, bağlı değil.
   - Observer olaylarıyla anlık güncellensin (Qt Signal ile, UI thread'inde).
3. Loglar sekmesi: event_logs tablosu; sınav/öğrenci/olay türü/tarih aralığı filtreleri; olay türüne göre renk;
   "Log dosyasını aç" ve "CSV/Excel'e aktar".
4. Sınav başlamışken yanlışlıkla uygulamayı kapatmaya karşı onay diyaloğu.

Önce planını göster.
```

**Test (B):** 3 öğrenci uygulaması açıp sınav başlat. Canlı panel anlık güncelleniyor mu? +5 dk öğrenci ekranına yansıyor mu?

---

## P6 — Dayanıklılık, sınav modu, öğrenci yönetimi (Gün 6, sahipleri C ve D)

```
CLAUDE.md'yi oku. İki ayrı iş var.

BÖLÜM 1 — Öğrenci uygulaması (student_app/):
1. Sınav modu: sınav başlayınca tam ekran; pencere kapatma, Alt+F4 ve küçültme engellensin (sınav bitene kadar).
   Pencere odağı kaybedilirse focus_lost gönder ve öğrenciye "Pencereden çıkış kaydedildi" uyarısı göster.
2. Bağlantı koparsa: ekranın üstünde sarı şerit "Bağlantı koptu, cevapların bilgisayarında saklanıyor…";
   cevaplar yerel bir JSON yedeğe yazılsın (kullanıcı uygulama veri klasörü) ve bağlantı gelince sırayla gönderilsin.
3. Uygulama çökerse/kapanırsa tekrar açılıp giriş yapınca sınava kaldığı yerden devam etsin (sunucudaki
   saved_answers + yerel yedek; çakışmada en yeni updated_at kazanır).

BÖLÜM 2 — Öğrenci yönetimi (server/services/import_export.py + instructor_app/ui/students.py):
1. Öğrenciler sekmesi: sınıf listesi (ekle/düzenle/sil), seçili sınıfın öğrencileri tablosu.
2. Excel/CSV'den içe aktarma: sütunlar "Öğrenci No, Ad Soyad" (başlık satırı esnek tanınsın), hedef sınıf seçilir;
   önizleme diyaloğu (eklenecek / zaten var / hatalı satır sayıları); başlangıç şifresi = öğrenci no.
3. Tek öğrenci ekleme/düzenleme, şifre sıfırlama, sınıfa taşıma.
4. Örnek içe aktarma dosyası şablonunu indir butonu.
5. Testler: içe aktarmada tekrar eden no, boş satır, hatalı satır.

Önce planını göster.
```

**Test (C):** Sınav sırasında öğrenci uygulamasını görev yöneticisinden kapat → tekrar aç → kaldığı yerden devam mı?
**Test (D):** Sınıf listesini Excel'den içe aktar (okulun gerçek liste formatına benzer bir dosya hazırlayın).

---

## P7 — Entegrasyon + yük testi (Gün 7, sahibi A)

```
CLAUDE.md'yi oku. Sistemin bütününü doğrulayacağız.

1. scripts/fake_students.py: -n parametresiyle N sahte öğrenci (seed'deki 2026001...) aynı anda bağlanıp giriş yapsın,
   sınav başlamasını beklesin, rastgele aralıklarla rastgele cevaplar kaydetsin, bir kısmı erken göndersin,
   bir kısmı bağlantıyı koparıp tekrar bağlansın, kalanı süre dolmasını beklesin. Sonunda özet yazsın
   (bağlanan, gönderen, hata alan, ortalama cevap süresi ms).
2. tests/test_e2e.py: sunucuyu test içinde başlatıp gerçek WebSocket istemcileriyle uçtan uca senaryo:
   giriş → sınav başlat → cevapla → gönder → puan doğru mu → loglar yazıldı mı → süre sonrası gönderim reddediliyor mu.
3. fake_students ile 40 öğrenci çalıştır, darboğaz veya hata varsa bul ve düzelt.
4. Tüm kodu gözden geçir: CLAUDE.md kurallarına aykırı yerler (UI'da doğrudan DB sorgusu, cevap anahtarının
   istemciye sızması, UI thread'ini donduran işler, yakalanmamış hatalar) — bul, listele, düzelt.
5. README'yi güncel hâle getir.

Önce planını göster.
```

---

## P8 — Paketleme + laboratuvar hazırlığı (Gün 8–9)

```
CLAUDE.md'yi oku. Uygulamayı laboratuvara kuracağız.

1. PyInstaller ile iki ayrı Windows uygulaması: LabSinav-Egitmen.exe ve LabSinav-Ogrenci.exe (tek klasör modu,
   ikonlu, konsol penceresi açılmasın). build.bat betiği ile tek komutla derlensin.
2. Eğitmen uygulaması ilk açılışta Windows Güvenlik Duvarı'nda port izni yoksa kullanıcıyı uyarsın ve
   gerekli komutu (netsh) yönetici olarak çalıştırma seçeneği sunsun.
3. data/ ve logs/ klasörleri exe'nin yanında değil kullanıcının uygulama veri klasöründe olsun;
   eğitmen uygulamasında "Veri klasörünü aç" ve "Veri tabanını yedekle" menüleri.
4. Öğrenci uygulaması sunucu IP'sini hatırlasın.
5. Yaygın sorunlar için docs/SORUN_GIDERME.md (sunucu bulunamıyor, güvenlik duvarı, farklı ağ, vb.).

Önce planını göster.
```

Laboratuvar testinde bulunan hatalar için şablon:
```
Laboratuvar testinde şu hatalar bulundu. Her birinin nedenini bul ve düzelt, sonra ne yaptığını listele:
1. [Ne yaparken] → [Ne oldu] → [Ne olmalıydı] (varsa hata mesajı/ekran görüntüsü açıklaması)
2. ...
```

---

## P9 — Demo hazırlığı (Gün 10, herkes kendi modülü için)

Her modül sahibi kendi dosyaları için ayrı ayrı çalıştırır (`/clear` ile):
```
Ben bu projede [A: sunucu / B: eğitmen ekranları / C: öğrenci ekranları / D: puanlama] kısmından sorumluyum.
[dosya yolları] dosyalarını bana, hocama demoda anlatacağım şekilde açıkla:
1. Genel akış (hangi fonksiyon kimi çağırıyor), basit bir dille.
2. En önemli 3 fonksiyonu satır satır.
3. Hocanın sorabileceği 8 zor soru ve kısa cevapları (ör. "süre dolunca ne oluyor?", "iki öğrenci aynı anda
   gönderirse?", "cevap anahtarı neden öğrenciye gitmiyor?").
Kod değiştirme, sadece açıkla.
```

---

## Claude Code'u olmayanların sürekli işleri

- **Soru içeriği (herkes, Gün 1–5):** 20–30 gerçekçi C sorusu (test + klasik), doğru cevaplarıyla.
  P7'den sonra pilot bunları seed'e ekletir:
  `docs/sorular.xlsx dosyasındaki soruları seed.py'ye ekle` (biçim: Tür, Kategori, Soru, Şık A-F, Doğru, Puan).
- **IEEE rapor (kendiniz yazın — yapay zekâ ile yazılan rapor değerlendirilmiyor):** Özet, giriş, yöntem,
  akış diyagramı, UML, class diyagramı, pseudocode, sonuç. Class diyagramını koddan
  `pip install pylint` → `pyreverse -o png server shared` ile çıkarıp düzenleyebilirsiniz.
- **Test:** Her akşam `git pull` → uygulamayı çalıştır → kendi modülünün test maddelerini dene →
  hataları gruba yukarıdaki şablonla yaz.
- **Laboratuvar:** En erken fırsatta okul bilgisayarında Python/exe çalışıyor mu, iki bilgisayar aynı ağda
  birbirini görüyor mu, deneyin.

---

## Final (sonra eklenecek)

Vize bitince bu dosyaya F1–F6 promptları eklenecek: kod sorusu + test case yönetimi, kod editörü,
derleme (taşınabilir MinGW), sandbox'ta test çalıştırma, zaman/yer karmaşıklığı ölçümü, karmaşıklık raporu.
