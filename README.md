# LabSınav

Programlama laboratuvarları için sınav ve kod değerlendirme sistemi.
İnternet gerekmez; eğitmen bilgisayarı yerel ağda (LAN/WiFi) sunucu olur, öğrenciler ona bağlanır.

- **Eğitmen uygulaması**: sunucuyu başlatır, soruları ve sınavları yönetir, sınavı canlı izler, sonuçları gösterir.
- **Öğrenci uygulaması**: sunucuyu ağda kendisi bulur, giriş yapar, sınavı çözer. Cevaplar her değişiklikte kaydedilir.

Ayrıntılı mimari, protokol ve kurallar için: [CLAUDE.md](CLAUDE.md)

---

## Kurulum

Python **3.11 veya üstü** gerekir. Tüm komutlar proje kök klasöründe (`README.md`'nin olduğu yerde) çalıştırılır.

### Windows

1. <https://www.python.org/downloads/> adresinden Python'u indirip kurun.
   Kurulumun ilk ekranında **"Add python.exe to PATH"** kutusunu işaretleyin.
2. Proje klasöründe PowerShell açın (klasörde boş yere Shift + sağ tık → "PowerShell penceresini burada açın"):

   ```powershell
   py -3 -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

   `Activate.ps1` "betik çalıştırma devre dışı" hatası verirse bir kez şunu çalıştırın, sonra tekrar deneyin:

   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

   (Komut İstemi `cmd` kullanıyorsanız etkinleştirme komutu: `.venv\Scripts\activate.bat`)

### Linux (Ubuntu / Debian / Arch)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Qt pencereleri açılmazsa (`xcb` eklentisi hatası) şu sistem paketini kurun:

```bash
sudo apt install libxcb-cursor0     # Ubuntu / Debian
sudo pacman -S xcb-util-cursor      # Arch
```

> Her yeni terminalde önce sanal ortamı etkinleştirin (`.venv\Scripts\Activate.ps1` veya
> `source .venv/bin/activate`). Satırın başında `(.venv)` görünüyorsa etkindir.

### İlk açılış: eğitmen hesabı

Eğitmen uygulaması ilk kez açıldığında veri tabanında hiç eğitmen yoksa **"İlk kurulum"** penceresi gelir:
ad soyad, kullanıcı adı ve şifreyi (iki kez) girip **Hesabı oluştur**'a basın. Ardından normal giriş
ekranı açılır ve bu bilgilerle giriş yapılır. Şifre daha sonra **Ayarlar → Şifre değiştir** menüsünden değiştirilebilir.

Denemek için hazır örnek veri isterseniz ilk kurulum yerine şunu çalıştırabilirsiniz:

```bash
python -m scripts.seed           # DİKKAT: veri tabanındaki TÜM veriyi siler, örnek veriyi yükler
```

---

## Çalıştırma

```bash
python -m instructor_app.main          # eğitmen uygulaması (sunucuyu da başlatır)
python -m student_app.main             # öğrenci uygulaması
python -m student_app.main --demo      # öğrenci uygulaması, sunucusuz deneme (arayüzü görmek için)
python -m student_app.main --no-kiosk  # tam ekran / sınav kilidi olmadan (geliştirirken)
pytest                                 # tüm testler
```

### Örnek veri (seed)

```bash
python -m scripts.seed                  # 30 öğrenci (15 + 15)
python -m scripts.seed --students 80    # 80 öğrenci (40 + 40), yük testi için
```

| Rol | Kullanıcı adı | Şifre |
|---|---|---|
| Eğitmen | `egitmen` | `egitmen123` |
| Öğrenci | `260101001`, `260101002`, … | öğrenci numarasının kendisi |

Öğrencilerin ilk yarısı **"1. Öğretim A"**, ikinci yarısı **"1. Öğretim B"** sınıfındadır
(varsayılan: `260101001`–`260101015` A, `260101016`–`260101030` B).
Örnek sınav ("C Programlama — Ara Sınav Denemesi", 10 soru, 100 puan) A sınıfına aittir.

---

## Laboratuvarda kullanım

Eğitmen bilgisayarı ve öğrenci bilgisayarları **aynı yerel ağda** (aynı switch veya aynı WiFi) olmalıdır.

1. **Önce eğitmen**: eğitmen uygulamasını açın ve giriş yapın.
   Sunucu ancak giriş yapıldıktan sonra başlar; öğrenciler o zamana kadar bağlanamaz.
2. Pencerenin altındaki durum çubuğunda sunucu adresi yazar, ör. `Sunucu: 192.168.1.20:8765`.
   Bu IP adresini not edin (otomatik bulma çalışmazsa öğrencilere söyleyeceksiniz).
3. **Sonra öğrenciler**: öğrenci uygulamasını açarlar. Uygulama sunucuyu ağda kendisi bulur
   (birkaç saniye sürebilir). Bulamazsa giriş ekranındaki alana eğitmenin IP adresi elle yazılır.
4. Öğrenciler öğrenci numarası ve şifreleriyle giriş yapar; sınav başlayana kadar bekleme ekranında kalırlar.
5. Eğitmen **Sınavlar** sekmesinde sınavı seçip **Başlat**'a basar. Sınav, sınıftaki bağlı tüm öğrencilere
   aynı anda açılır ve **Canlı Panel** sekmesine geçilir.
6. Canlı Panel'de her öğrencinin durumu (bağlı, sınavda, gönderdi), cevapladığı soru sayısı ve
   pencereden çıkma sayısı izlenir. Gerekirse **+5 dk / +10 dk** ile süre eklenir veya **Sınavı Bitir** ile erken bitirilir.
7. Süre dolunca göndermemiş öğrencilerin kayıtlı cevapları **otomatik gönderilir** ve puanlanır.
8. **Sonuçlar** sekmesinde puanlar, istatistikler ve soru analizi görülür; klasik sorularda elle puan verilebilir,
   sonuçlar Excel'e aktarılabilir. **Loglar** sekmesinde giriş, gönderim, pencereden çıkma gibi olaylar listelenir.

Bağlantısı kopan öğrenci tekrar giriş yapınca sınava kaldığı yerden, kayıtlı cevaplarıyla devam eder.
Eğitmen uygulaması sınav sırasında kapanırsa süre işlemeye devam eder; uygulama yeniden açılıp giriş
yapılınca sınav kaldığı yerden sürer.

### Ağ ve güvenlik duvarı

| Port | Protokol | Ne için |
|---|---|---|
| 8765 | TCP (WebSocket) | Öğrenci ↔ sunucu iletişimi |
| 50555 | UDP | Sunucunun ağda otomatik bulunması |

Bu iki port **eğitmen bilgisayarında** gelen bağlantılara açık olmalıdır.

**Windows**: eğitmen uygulaması ilk açıldığında Windows izin sorar; **"Özel ağlar"** için izin verin.
Sormazsa veya yanlışlıkla reddedildiyse **yönetici olarak açılmış** PowerShell'de:

```powershell
netsh advfirewall firewall add rule name="LabSinav WebSocket" dir=in action=allow protocol=TCP localport=8765
netsh advfirewall firewall add rule name="LabSinav Kesif"     dir=in action=allow protocol=UDP localport=50555
```

Ağ bağlantısının profili "Genel" ise **Ayarlar → Ağ ve İnternet → (bağlantı) → Ağ profili: Özel** yapın.

**Linux**:

```bash
sudo ufw allow 8765/tcp && sudo ufw allow 50555/udp                       # ufw (Ubuntu)
sudo firewall-cmd --add-port=8765/tcp --add-port=50555/udp --permanent    # firewalld (Fedora vb.)
sudo firewall-cmd --reload
```

**Otomatik bulma çalışmıyorsa** IP'yi elle girmek her zaman çalışır. Sık sebepler: misafir/okul
WiFi'larında cihazların birbirini görmesinin engellenmesi ("istemci izolasyonu"), farklı alt ağlar
(ör. eğitmen kabloda 10.0.x.x, öğrenciler WiFi'da 192.168.x.x) veya UDP 50555'in kapalı olması.
IP elle girildiğinde de bağlanamıyorsa TCP 8765 kapalıdır ya da cihazlar aynı ağda değildir.

### Log dosyaları

- `logs/events.log`: sınav olayları (JSON Lines). Aynı olaylar Loglar sekmesinde de görülür.
- `logs/instructor.log`, `logs/student.log`: uygulama hataları. Beklenmeyen bir hata olursa kullanıcıya
  Türkçe bir mesaj gösterilir, ayrıntısı bu dosyalara yazılır; sorun bildirirken bu dosyayı ekleyin.

---

## Yük testi (sahte öğrencilerle)

`scripts/fake_students.py`, gerçek öğrenci uygulamasıyla aynı protokolü kullanan N sahte öğrenciyi
aynı anda bağlar. Öğrenciler rastgele aralıklarla rastgele cevap kaydeder; bir kısmı erken gönderir,
bir kısmı bağlantıyı koparıp tekrar bağlanır (kayıtlı cevapların geri geldiği kontrol edilir),
bir kısmı "pencereden çıktı" (`focus_lost`) gönderir, kalanlar sürenin dolmasını bekler.

```bash
python -m scripts.seed --students 80     # A sınıfında 40 öğrenci (260101001…260101040)
python -m instructor_app.main            # egitmen / egitmen123 ile giriş yapın
python -m scripts.fake_students -n 40    # başka bir terminalde (sunucuyu ağda kendisi bulur)
```

Sahte öğrenciler bağlanınca eğitmen uygulamasında örnek sınavı **Başlat**'a basın (süreyi kısaltmak için
önce sınavı düzenleyip süreyi 2-3 dakika yapabilirsiniz). Betik sınav bitince özet yazar:

```
Bağlanan                       : 40
Kendisi gönderen               : 8
Otomatik gönderilen            : 32
Yeniden bağlanan / doğrulanan  : 8 / 8
save_answer ort. / p95 / en yavaş : 4.6 / 9.1 / 52.1 ms
Hata alan öğrenci              : 0
```

- **Hata alan öğrenci 0** olmalı. Süre dolarken yola çıkmış kayıtların aldığı `TIME_UP` "beklenen" olarak ayrı yazılır, hata sayılmaz.
- `save_answer` süreleri birkaç on milisaniyeyi geçmemeli; yüzlerce ms'lik süreler sunucu bilgisayarının zorlandığını gösterir.
- `-n` değeri sınavın sınıfındaki öğrenci sayısını geçmemeli; başka sınıftaki öğrenciler sınav başlamadığı için bekler.

Seçenekler (`python -m scripts.fake_students --help`):

| Seçenek | Varsayılan | Anlamı |
|---|---|---|
| `-n` | 30 | öğrenci sayısı |
| `--host`, `--port` | keşif, 8765 | sunucu adresi (verilmezse UDP keşfiyle bulunur) |
| `--first` | 260101001 | ilk öğrenci numarası |
| `--min-delay`, `--max-delay` | 1, 5 | iki kayıt arası bekleme (sn); yoğun test için ör. `0.05` ve `0.3` |
| `--early`, `--reconnect`, `--focus` | 0.2, 0.2, 0.3 | erken gönderen, bağlantı koparan, pencereden çıkan oranı |
| `--seed` | — | aynı sayı verilirse aynı rastgele davranış (tekrarlanabilir test) |

Başka bilgisayardan çalıştırmak için: `python -m scripts.fake_students -n 40 --host 192.168.1.20`

---

## Klasörler

```
shared/          ortak: mesaj protokolü, ayarlar, tema, hata yakalama
server/          veri tabanı, ağ ve iş mantığı (servisler)
instructor_app/  eğitmen arayüzü
student_app/     öğrenci arayüzü
evaluator/       C kodu derleme ve değerlendirme (final)
scripts/         seed ve yük testi betikleri
tests/           pytest testleri
data/, logs/     çalışma zamanında oluşur (git'e eklenmez)
```
