# LabSınav

Programlama laboratuvarları için sınav ve kod değerlendirme sistemi.
İnternet gerekmez; eğitmen bilgisayarı yerel ağda (LAN/WiFi) sunucu olur, öğrenciler ona bağlanır.

- **Eğitmen uygulaması** — sunucuyu başlatır, soruları/sınavları yönetir, sonuçları gösterir.
- **Öğrenci uygulaması** — sunucuyu ağda otomatik bulur, giriş yapar, sınavı çözer.

Ayrıntılı mimari, protokol ve kurallar için: [CLAUDE.md](CLAUDE.md)

## Kurulum

Python 3.11 veya üstü gerekir.

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

## Çalıştırma

Tüm komutlar proje kök klasöründen çalıştırılır.

```bash
python -m scripts.seed           # örnek veri (DİKKAT: veri tabanını sıfırlar)
python -m instructor_app.main    # eğitmen uygulaması (sunucuyu da başlatır)
python -m student_app.main       # öğrenci uygulaması
pytest                           # testler
```

### Örnek giriş bilgileri (seed)

| Rol | Kullanıcı adı | Şifre |
|---|---|---|
| Eğitmen | `egitmen` | `egitmen123` |
| Öğrenci | `260101001` … `260101030` | öğrenci numarasının kendisi |

`260101001`–`260101015` → "1. Öğretim A", `260101016`–`260101030` → "1. Öğretim B".

## Ağ ayarları

| Port | Protokol | Ne için |
|---|---|---|
| 8765 | TCP (WebSocket) | Öğrenci ↔ sunucu iletişimi |
| 50555 | UDP | Sunucunun ağda otomatik bulunması |

Eğitmen bilgisayarının güvenlik duvarında bu iki port açık olmalıdır (Windows ilk açılışta izin sorar
— "Özel ağlar" için izin verin). Otomatik bulma çalışmazsa öğrenci ekranında eğitmen bilgisayarının
IP adresi elle girilebilir; bu adres eğitmen uygulamasının durum çubuğunda yazar.

## Klasörler

```
shared/          ortak: mesaj protokolü, ayarlar, tema
server/          veri tabanı, ağ ve iş mantığı (servisler)
instructor_app/  eğitmen arayüzü
student_app/     öğrenci arayüzü
evaluator/       C kodu derleme ve değerlendirme (final)
scripts/         seed ve yük testi betikleri
tests/           pytest testleri
data/, logs/     çalışma zamanında oluşur (git'e eklenmez)
```
