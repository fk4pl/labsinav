# Sorun Giderme

Sık karşılaşılan sorunlar ve çözümleri. Sorun burada yoksa log dosyalarını
(bkz. [Log ve veri dosyaları nerede?](#log-ve-veri-dosyaları-nerede)) geliştirici ekibe iletin.

- [Python 3.15: "'lazy_import' object is not callable"](#python-315-lazy_import-object-is-not-callable)
- [Öğrenci uygulaması sunucuyu bulamıyor](#öğrenci-uygulaması-sunucuyu-bulamıyor)
- [Güvenlik duvarı](#güvenlik-duvarı)
- [Misafir WiFi / istemci izolasyonu](#misafir-wifi--istemci-izolasyonu)
- [SmartScreen: "Windows bilgisayarınızı korudu"](#smartscreen-windows-bilgisayarınızı-korudu)
- [Antivirüs uyarısı](#antivirüs-uyarısı)
- [Log ve veri dosyaları nerede?](#log-ve-veri-dosyaları-nerede)

---

## Python 3.15: "'lazy_import' object is not callable"

**Belirti:** Eğitmen uygulaması açılırken (ya da öğrenci bağlanınca) sunucu çalışmıyor; log dosyasında

```
TypeError: 'lazy_import' object is not callable
```

hatası var ve hata `asyncio.to_thread` içinden, Python'un kendi dosyalarından geliyor.

**Sebep:** Hata bizim kodumuzda değil, Python 3.15'in standart kütüphanesinde. LabSınav
**Python 3.11–3.14** ile test edildi. Uygulamalar 3.15 veya üstünde açılınca bu yüzden bir uyarı gösterir.

**Çözüm:** Python 3.14'ü kurun ve sanal ortamı onunla yeniden oluşturun.

Windows (PowerShell, proje klasöründe):

```powershell
py install 3.14                # Python kurulum yöneticisiyle 3.14'ü kurar
Remove-Item -Recurse -Force .venv
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python --version               # "Python 3.14.x" yazmalı
pip install -r requirements.txt
```

Linux: dağıtımın paket yöneticisinden veya `pyenv` ile 3.14 kurup `python3.14 -m venv .venv`.

> Hazır .exe sürümü kendi Python'unu (3.13) içinde taşır; bu sorun .exe'de olmaz.

---

## Öğrenci uygulaması sunucuyu bulamıyor

Sırayla kontrol edin:

1. **Eğitmen uygulaması açık ve giriş yapılmış mı?** Sunucu ancak eğitmen giriş yaptıktan sonra başlar.
2. **Aynı ağdalar mı?** Eğitmen ve öğrenci bilgisayarları aynı WiFi'ya / aynı switch'e bağlı olmalı.
   Eğitmen kabloda `10.0.x.x`, öğrenciler WiFi'da `192.168.x.x` gibi farklı ağlardaysa birbirlerini görmezler.
3. **IP'yi elle girin.** Eğitmen penceresinin altındaki durum çubuğunda `Sunucu: 192.168.1.20:8765` yazar.
   Öğrenci giriş ekranında "Sunucu bulunamadı" çıkınca bu IP'yi kutuya yazıp giriş yapar.
   Öğrenci uygulaması **son bağlandığı sunucuyu hatırlar**: bir sonraki açılışta otomatik bulma
   başarısız olursa önce o adresi dener ve IP kutusuna hazır yazar.
4. IP elle girildiğinde de bağlanamıyorsa: [Güvenlik duvarı](#güvenlik-duvarı) ve
   [Misafir WiFi](#misafir-wifi--istemci-izolasyonu) bölümlerine bakın.

Hızlı deneme: öğrenci bilgisayarında PowerShell'de `Test-NetConnection 192.168.1.20 -Port 8765`
→ `TcpTestSucceeded : True` görünmeli.

---

## Güvenlik duvarı

Eğitmen bilgisayarında şu portlar **gelen** bağlantılara açık olmalı:

| Port | Protokol | Ne için |
|---|---|---|
| 8765 | TCP | Öğrenci ↔ sunucu iletişimi |
| 50555 | UDP | Sunucunun ağda otomatik bulunması |

**Windows:** Eğitmen uygulaması giriş yaptıktan sonra kuralların olup olmadığını kendisi kontrol eder.
Kural yoksa uyarı gösterir; **"Kuralları ekle (yönetici)"** düğmesine basıp Windows'un yönetici izni
penceresinde **Evet** deyin. Elle eklemek isterseniz **yönetici olarak açılmış** PowerShell'de:

```powershell
netsh advfirewall firewall add rule name="LabSinav WebSocket" dir=in action=allow protocol=TCP localport=8765
netsh advfirewall firewall add rule name="LabSinav Kesif"     dir=in action=allow protocol=UDP localport=50555
```

Ağ profili "Genel" ise **Ayarlar → Ağ ve İnternet → (bağlantı) → Ağ profili türü: Özel** yapın.
Okul bilgisayarında yönetici yetkiniz yoksa bilgi işlem birimine bu iki komutu çalıştırmalarını söyleyin.

**Linux:**

```bash
sudo ufw allow 8765/tcp && sudo ufw allow 50555/udp                       # ufw (Ubuntu)
sudo firewall-cmd --add-port=8765/tcp --add-port=50555/udp --permanent    # firewalld
sudo firewall-cmd --reload
```

---

## Misafir WiFi / istemci izolasyonu

**Belirti:** Herkes aynı WiFi'da, güvenlik duvarı kuralları tamam, IP elle girildiği hâlde bağlanılamıyor.

**Sebep:** Misafir ve okul WiFi'larının çoğunda "istemci izolasyonu" (client/AP isolation) açıktır:
cihazlar internete çıkabilir ama **birbirini göremez**. LabSınav'ın internete ihtiyacı yoktur,
ama cihazların birbirini görmesine ihtiyacı vardır.

**Çözümler (kolaydan zora):**

1. **Telefon hotspot'u:** Eğitmen telefonunda kişisel erişim noktasını açar; eğitmen bilgisayarı ve
   öğrenci bilgisayarları bu ağa bağlanır. Mobil veri harcanmaz (LabSınav internete çıkmaz).
   Çoğu telefon 10–15 cihaza kadar izin verir; kalabalık sınıfta yetmeyebilir.
2. Laboratuvarın kablolu ağını veya izolasyonu kapalı bir WiFi'yı (ör. personel ağı) kullanın.
3. Ucuz bir WiFi router'ı internete bağlamadan açın; herkes ona bağlansın.
4. Bilgi işlem biriminden laboratuvar ağı için istemci izolasyonunu kapatmasını isteyin.

---

## SmartScreen: "Windows bilgisayarınızı korudu"

**Belirti:** İndirilen `LabSinav-Egitmen.exe` veya `LabSinav-Ogrenci.exe` ilk açılışta mavi bir
"Windows bilgisayarınızı korudu" penceresi çıkıyor ve sadece "Çalıştırma" düğmesi görünüyor.

**Sebep:** Uygulama dijital olarak imzalı değil (imza sertifikası ücretli); Windows tanımadığı her
programda bu uyarıyı gösterir. Virüs bulunduğu anlamına gelmez.

**Çözüm:** Penceredeki **"Ek bilgi"** bağlantısına tıklayın → **"Yine de çalıştır"**.
Her bilgisayarda bir kez yapmak yeterlidir.

Zip'i çıkarmadan önce zip dosyasına sağ tık → **Özellikler** → altta **"Engellemeyi kaldır"**
kutusunu işaretleyip **Tamam** derseniz uyarı hiç çıkmayabilir.

---

## Antivirüs uyarısı

**Belirti:** Antivirüs programı .exe'yi "şüpheli" bularak siliyor veya karantinaya alıyor.

**Sebep:** PyInstaller ile paketlenmiş Python programları bazı antivirüslerde **yanlış alarm**
(false positive) verir; program kendini açılışta geçici olarak çözdüğü için şüpheli görünür.

**Çözüm:**

1. .exe'yi sadece bu projenin GitHub Actions sayfasından indirin (README → "Hazır .exe'yi indirme").
2. Windows Güvenliği → **Virüs ve tehdit koruması** → **Koruma geçmişi**: LabSınav'ı seçip **"İzin ver"**.
3. Gerekirse LabSınav klasörünü dışlamalara ekleyin: **Virüs ve tehdit koruması ayarları** →
   **Dışlamalar** → **Dışlama ekle** → Klasör.
4. Okul bilgisayarlarında kurumsal antivirüs varsa bilgi işlem biriminden klasör için istisna isteyin.

---

## Log ve veri dosyaları nerede?

| Çalıştırma şekli | Veri tabanı | Loglar |
|---|---|---|
| Python ile (`python -m ...`) | proje klasöründe `data/labsinav.db` | proje klasöründe `logs/` |
| Hazır .exe (Windows) | `%LOCALAPPDATA%\LabSinav\data\labsinav.db` | `%LOCALAPPDATA%\LabSinav\logs\` |

`%LOCALAPPDATA%` genellikle `C:\Users\<kullanıcı adı>\AppData\Local` klasörüdür.
Eğitmen uygulamasında **Ayarlar → Veri klasörünü aç** bu klasörü doğrudan açar.
Öğrencinin cevap yedekleri ve son bağlandığı sunucu (`last_server.json`) her iki durumda da
`%LOCALAPPDATA%\LabSinav\` altındadır (Linux: `~/.local/share/LabSinav/`).

- `events.log`: sınav olayları (giriş, gönderim, pencereden çıkma…)
- `instructor.log`, `student.log`: uygulama hataları; sorun bildirirken bu dosyayı ekleyin.
