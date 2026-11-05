# LabSınav — Programlama Laboratuvarı Sınav ve Kod Değerlendirme Sistemi

Yazılım Geliştirme I dersi projesi (2026-2027 Güz). 4 kişilik ekip. Okul, en iyi projeyi
gerçek laboratuvarlarda kullanmaya başlayacak: **kod gerçek kullanıma uygun, sağlam ve
anlaşılır olmalı.** Demoda her ekip üyesi kendi kodunu açıklayabilmeli; bu yüzden basit,
okunur çözümleri "akıllı" çözümlere tercih et.

## Sistem özeti

- **Eğitmen uygulaması** (masaüstü) aynı zamanda **sunucudur**: LAN/WiFi üzerinde WebSocket
  sunucusu açar, SQLite veri tabanını tutar, sınavı öğrencilere dağıtır, cevapları toplar, puanlar.
- **Öğrenci uygulaması** (masaüstü) **istemcidir**: sunucuyu ağda bulur, giriş yapar, sınavı çözer.
- Soru tipleri: `mcq` (çoktan seçmeli), `classic` (kısa cevaplı klasik), `code` (C programlama — FİNAL).
- İnternet bağlantısı GEREKMEZ. Her şey yerel ağda çalışır.

## Teknoloji

- Python 3.11+
- Arayüz: **PySide6** (her iki uygulama)
- Ağ: tek kanal **WebSocket** + JSON. Sunucu: `websockets` kütüphanesi (asyncio), eğitmen
  uygulamasında ayrı bir thread içinde çalışır; Qt tarafına **Signal** ile haber verir.
  İstemci: `PySide6.QtWebSockets.QWebSocket` (Qt event loop ile uyumlu, thread gerekmez).
- Sunucu keşfi: **UDP broadcast** (port 50555). Yedek: IP elle girilebilir.
- Veri tabanı: **SQLite + SQLAlchemy 2.x** (ORM). Dosya: `data/labsinav.db`
- Mesaj modelleri: **pydantic v2**
- Şifreler: **bcrypt**
- Excel içe/dışa aktarma: **openpyxl**
- Test: **pytest**
- Paketleme: **PyInstaller** (en sonda)
- FİNAL: C derleme için `gcc` (Windows'ta taşınabilir MinGW, `tools/mingw/` altında)

## Klasör yapısı ve sahiplik

```
shared/            protocol.py (mesaj tipleri), config.py (port, sabitler)      → A (değişiklik = ekip onayı)
server/
  db/              models.py, session.py                                       → A (şema değişikliği = ekip onayı)
  net/             ws_server.py, discovery.py                                  → A
  services/        auth.py, exam_session.py, event_log.py                      → A
                   question_bank.py, exam_admin.py                             → B
                   grading.py, results.py, import_export.py                    → D
instructor_app/    main.py, ui/ (login, question_bank, exam_builder,
                   live_panel, logs)                                           → B
                   ui/results.py, ui/students.py                               → D
student_app/       main.py, net/client.py, ui/ (login, waiting, exam_view)     → C
evaluator/         compiler.py, runner.py, complexity.py  (FİNAL)              → D
scripts/           seed.py (örnek veri), fake_students.py (yük testi)
tests/
data/, logs/       çalışma zamanı dosyaları (gitignore)
```

**Kural:** Kullanıcı açıkça istemedikçe başka bir ekip üyesinin klasöründeki dosyaları
değiştirme. `shared/protocol.py` veya `server/db/models.py` değişmesi gerekiyorsa değişikliği
yap ama cevabında **büyük harfle "ORTAK DOSYA DEĞİŞTİ"** diye belirt ve ne değiştiğini yaz.

## İletişim protokolü

Her mesaj bir JSON zarfıdır:
```json
{"type": "login", "id": "a1b2", "payload": {...}}
```
`id` istek-cevap eşleştirmek içindir; sunucu cevabında aynı `id`'yi döner.

İstemci → Sunucu:
| type | payload | Not |
|---|---|---|
| `login` | `{username, password}` | Öğrenci kullanıcı adı = öğrenci no |
| `save_answer` | `{exam_id, question_id, selected_option_id?, text_answer?, code?}` | Otomatik kayıt (her değişiklikte, debounce 2 sn) |
| `submit` | `{exam_id}` | Sınavı bitir |
| `focus_lost` | `{exam_id, at}` | Öğrenci pencereden çıktı (loglanır) |
| `ping` | `{}` | Bağlantı canlılığı, 10 sn'de bir |

Sunucu → İstemci:
| type | payload |
|---|---|
| `login_ok` | `{user: {id, username, full_name, class_name}}` |
| `error` | `{code, message}` (message Türkçe, kullanıcıya gösterilebilir) |
| `exam_start` | `{exam: {id, title, questions: [...]}, ends_at, server_now, saved_answers: {...}}` |
| `save_ok` | `{question_id, saved_at}` |
| `submit_ok` | `{submitted_at}` |
| `exam_end` | `{exam_id, reason: "time_up" \| "instructor_stopped"}` |
| `exam_update` | `{exam_id, ends_at, server_now}` — eğitmen süre ekledi; istemci geri sayımı yeni `ends_at`'e göre günceller |
| `pong` | `{server_now}` |

`error.code` değerleri: `BAD_REQUEST`, `UNKNOWN_TYPE`, `INVALID_CREDENTIALS`, `NOT_STUDENT`,
`NOT_AUTHENTICATED`, `TIME_UP`, `ALREADY_SUBMITTED` (sınav zaten gönderilmiş),
`EXAM_NOT_ACTIVE` (sınav yok / başlamadı / bu öğrenciye ait değil), `INTERNAL`.
`focus_lost` mesajına cevap dönmez (sadece loglanır).

Kritik kurallar:
1. **Cevap anahtarı ASLA istemciye gönderilmez** (`is_correct`, kabul edilen cevaplar, gizli test case'ler).
   İstemciye giden soru modelleri ayrı pydantic modelleridir (`QuestionForStudent`).
2. **Süreyi sunucu belirler.** `ends_at` sunucuda tutulur; süre geçtikten sonra gelen `save_answer`/`submit`
   `error {code: "TIME_UP"}` ile reddedilir. İstemci `server_now` ile kendi saat farkını hesaplayıp geri sayımı gösterir.
3. **Yeniden bağlanma:** Öğrenci tekrar giriş yaparsa ve gönderilmemiş aktif sınavı varsa sunucu
   `exam_start`'ı `saved_answers` ile tekrar gönderir; öğrenci kaldığı yerden devam eder.
4. Aynı öğrenci aynı anda iki yerden bağlanırsa eski bağlantı kapatılır ve loglanır.
5. Süre dolunca sunucu tüm gönderilmemiş sınavları kaydedilmiş cevaplarla **otomatik gönderir** ve `exam_end` yollar.

## Veri tabanı şeması

```
classes(id, name)
users(id, username UNIQUE, full_name, password_hash, role['instructor'|'student'], class_id NULL)
categories(id, name UNIQUE)
questions(id, type['mcq'|'classic'|'code'], text, category_id, default_points, created_at, updated_at)
question_options(id, question_id, text, is_correct, order_index)
classic_accepted_answers(id, question_id, answer)          -- normalize edilerek karşılaştırılır
code_questions(question_id PK, starter_code, expected_time_complexity, expected_space_complexity,
               input_generator, sizes_json, time_limit_ms, memory_limit_mb)        -- FİNAL
test_cases(id, question_id, input, expected_output, is_hidden, order_index)         -- FİNAL
exams(id, title, class_id, duration_minutes, status['draft'|'running'|'finished'],
      started_at, ends_at, weight_tests, weight_complexity, created_by)
exam_questions(exam_id, question_id, points, order_index)
submissions(id, exam_id, student_id, status['in_progress'|'submitted'], started_at,
            submitted_at, ip, auto_submitted, total_score)  UNIQUE(exam_id, student_id)
answers(id, submission_id, question_id, selected_option_id, text_answer, code,
        updated_at, is_correct, points_awarded, is_manual)  UNIQUE(submission_id, question_id)
code_results(id, answer_id, compiled, compile_output, passed, total,
             time_complexity, space_complexity, measurements_json, created_at)      -- FİNAL
event_logs(id, at, event, username, exam_id, ip, detail)
```
- Tüm zamanlar veri tabanında **UTC ISO 8601**; arayüzde yerel saate çevrilir.
- `answers.is_manual`: puanı eğitmen elle verdiyse 1; otomatik (yeniden) puanlama bu cevaba dokunmaz.
- Var olan tabloya yeni sütun eklenirse `server/db/session.py` içindeki `ADDED_COLUMNS` listesine de
  eklenir; `init_db()` eski veri tabanı dosyalarına eksik sütunu kendisi ekler.
- Silinen soru, geçmiş sınavlarda kullanılmışsa gerçekten silinmez (`is_archived` ekle) — eski sonuçlar bozulmamalı.

## Puanlama

- `mcq`: seçilen şık doğruysa sorunun puanı, değilse 0.
- `classic`: cevap normalize edilir (baş/son boşluk, büyük-küçük harf, Türkçe İ/ı dahil, çoklu boşluk, sondaki noktalama)
  ve kabul edilen cevaplardan biriyle eşleşirse tam puan. Eğitmen sonuç ekranından elle puan değiştirebilir.
- `code` (FİNAL): `puan × (weight_tests × geçen/toplam + weight_complexity × uygunluk)`;
  uygunluk: beklenen veya daha iyi = 1, bir sınıf kötü = 0.5, daha kötü = 0.
  Karmaşıklık sırası: O(1) < O(log n) < O(n) < O(n log n) < O(n²) < O(n³) < O(2ⁿ).

## Loglama

- `logs/events.log` — JSON Lines (her satır bir olay): `{at, event, username, exam_id, ip, detail}`
  Olaylar: `login`, `login_failed`, `exam_started`, `submitted`, `auto_submitted`, `rejected_late`,
  `focus_lost`, `disconnected`, `duplicate_session`, `exam_stopped`, `exam_extended`.
  (`save_answer` çok sık geldiği için loglanmaz; cevabın kendisi zaten `answers.updated_at` ile tutulur.)
- Aynı olaylar `event_logs` tablosuna da yazılır (eğitmen arayüzünde filtrelenebilir liste için).

## Kod standartları

- Kod tanımlayıcıları (değişken, fonksiyon, sınıf) **İngilizce**; arayüz metinleri ve hata mesajları **Türkçe**; yorumlar Türkçe olabilir.
- Arayüz ile iş mantığı ayrı: UI dosyaları veri tabanına doğrudan sorgu yazmaz, `server/services/` fonksiyonlarını çağırır.
- Uzun süren işler (ağ, derleme) UI thread'ini dondurmamalı.
- Veri tabanına **yazan** kod `server.db.session.write_session()` kullanır (tek yazma kilidi; 40 öğrenci
  aynı anda kaydedince SQLite kilitlenmesin). Sadece okuyan kod `get_session()` kullanabilir.
  Kilidin içinde uzun iş (derleme vb.) yapma.
- Her servis fonksiyonu için en az bir pytest testi.
- Type hint kullan. Fonksiyonlar kısa ve tek iş yapan olsun.
- Hata durumunda kullanıcıya anlaşılır Türkçe mesaj göster; asla ham traceback gösterme.

## Komutlar

```
pip install -r requirements.txt
python -m scripts.seed                 # örnek eğitmen, sınıf, 30 öğrenci, 20 soru
python -m instructor_app.main          # eğitmen uygulaması (sunucuyu da başlatır)
python -m student_app.main             # öğrenci uygulaması
python -m scripts.fake_students -n 30  # 30 sahte öğrenciyle yük testi
pytest
```
Seed giriş bilgileri: eğitmen `egitmen / egitmen123`, öğrenciler `260101001`…`260101030` / şifre = öğrenci no
(ilk 15 "1. Öğretim A", son 15 "1. Öğretim B").

## Çalışma şekli

- Büyük bir işe başlamadan önce kısa bir plan sun ve onay bekle.
- İş bitince: ne yaptığını, hangi dosyaları değiştirdiğini ve **nasıl test edileceğini** madde madde yaz.
- Kodu açıklarken öğrenci seviyesinde, sade Türkçe kullan (ekip demoda kodu anlatacak).
