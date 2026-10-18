# Harmonik Bot — GitHub ile Kurulum (sunucusuz)

Bu rehber botu **GitHub Actions** üzerinde çalıştırır. Sunucu, bilgisayar veya ödeme gerekmez.
Bot her 5 dakikada bir tur başlatır; tur boyunca (~4,5 dk) mumları tarar ve Telegram komutlarını dinler.

> **Önemli:** 7/24 çalışması için depo **Public (herkese açık)** olmalı. Private depoda ücretsiz
> dakika kotası (ayda 2000 dk) birkaç günde biter. Public depoda kod görünür ama **token ve
> kişisel veriler görünmez** (Secrets ve önbellekte tutulur). Kodda sır yok.

---

## 0) Gerekenler
- Bir GitHub hesabı (github.com, ücretsiz)
- Telegram hesabın
- Bu zip dosyasını bilgisayarında/telefonunda açılmış hâlde (içinden `harmonik-bot` klasörü çıkar)

## 1) Telegram botunu oluştur (BotFather)
1. Telegram'da **@BotFather**'ı aç → `/newbot` yaz.
2. Bota bir ad ve `...bot` ile biten bir kullanıcı adı ver.
3. BotFather sana **token** verir (`123456789:AA...` biçiminde). **Kopyala, kimseyle paylaşma.**
4. Oluşan botunu aç ve **Start** (Başlat) tuşuna bas. (Bunu yapmazsan bot sana mesaj atamaz.)

## 2) Chat ID'ni öğren
1. Telegram'da **@userinfobot**'u aç → Start.
2. Sana `Id: 123456789` gibi bir sayı verir. **Bu senin chat ID'in.**

## 3) GitHub'da depo (repository) oluştur
1. github.com → sağ üstte **+** → **New repository**.
2. Ad: `harmonik-bot` (istediğin ad olur).
3. **Public** seç. "Add a README" kutusunu **işaretleme**.
4. **Create repository**.

## 4) Dosyaları yükle
Zip'ten çıkan `harmonik-bot` klasörünün **içindekileri** yükleyeceksin.
1. Yeni deponun sayfasında **uploading an existing file** bağlantısına tıkla.
2. Klasörün içindeki şunları sürükleyip bırak: `hbot` klasörü, `tests` klasörü, `deploy` klasörü,
   `main.py`, `requirements.txt`, `.env.example`, `README.md`, `Dockerfile`, `docker-compose.yml`,
   `.gitignore`, `KURULUM_GITHUB.md`.
3. Alta **Commit changes** de.

> `.github` klasörü (gizli klasör olduğu için) sürükle-bırakta görünmeyebilir. Bunu **5. adımda** elle oluşturacağız.
> Dosyaları yüklerken yan yana `hbot` klasörünün içinde `bot.py`, `engine.py` vb. dosyaların olduğundan emin ol.

## 5) İş akışı dosyalarını oluştur (`.github`)
Bu klasör zip'te `.github/workflows/` içinde hazır. Yüklenmediyse elle ekle:
1. Deponda **Add file → Create new file**.
2. Dosya adı kutusuna tam olarak şunu yaz: `.github/workflows/bot.yml`
   (`/` yazdıkça klasörler otomatik oluşur).
3. Zip'teki `.github/workflows/bot.yml` dosyasının **tüm içeriğini** kopyalayıp yapıştır → **Commit changes**.
4. Aynısını `.github/workflows/keepalive.yml` için tekrarla.

## 6) Gizli bilgileri (Secrets) ekle
Deponda **Settings → Secrets and variables → Actions → New repository secret**:

| Ad | Değer | Zorunlu |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather'ın verdiği token | Evet |
| `TELEGRAM_CHAT_ID` | @userinfobot'tan aldığın sayı | Evet (botu sadece sen kullanırsın) |
| `TWELVEDATA_API_KEY` | twelvedata.com'dan ücretsiz anahtar | Hayır (forex için yedek kaynak) |

Adları **birebir aynı** yaz (büyük harf, alt çizgi).

## 7) Actions'ı aç ve başlat
1. Deponda **Actions** sekmesi → çıkarsa **"I understand my workflows, enable them"** tuşuna bas.
2. Soldan **Harmonik Bot** → sağda **Run workflow** → **Run workflow**.
3. 1 dakika içinde bir tur başlar. Tıklayıp **run** → **Tur çalıştır** adımının günlüğünü izleyebilirsin.
   `Tek seferlik mod` ve `tarayıcı başladı` satırlarını görmelisin.
4. Telegram'da botuna **"✅ Bot başladı"** mesajı gelir. Sonra `/test` yaz; örnek kart gelirse her şey tamam.

Bundan sonra kendiliğinden her 5 dakikada bir devam eder; senin bir şey yapmana gerek yok.

## 8) Günlük kullanım
- `/ayar` → pariteler, zaman dilimleri, formasyonlar, yön, skor, bildirimler.
- `/istatistik` → başarı tablosu. `/aktif` → şu an izlenen formasyonlar. `/durum` → bot durumu.
- `/ekle SOLUSDT`, `/cikar SOLUSDT`, `/kural Gartley ab 0.60 0.68` (oranları elle yaz). Tüm liste: `/yardim`.

---

## Bilmen gerekenler (dürüst notlar)
1. **Komut gecikmesi:** Bot turlar arasında kısa süre "uykuda" olabilir. Komutuna cevap genelde
   birkaç saniye, bazen 1–2 dakika içinde gelir. Sinyaller kapanmış mumlara bağlı olduğundan
   (15 dk ve üzeri) bu gecikme sinyal kalitesini etkilemez.
2. **GitHub zamanlayıcısı garanti vermez:** Yoğun saatlerde turlar birkaç dakika gecikebilir veya
   atlanabilir. Bot kaldığı yerden devam eder; kapanmış mumları kaçırmaz.
3. **Veri kaynağı engelleri:** GitHub sunucuları ABD'dedir. Binance ana adresi ABD'den engelli olabilir;
   bu yüzden sıra `binance_spot (binance.vision yedeğiyle) → gate_spot → bybit_spot` şeklindedir.
   Forex/altın/gümüş Yahoo'dan alınır; Yahoo bazen bulut IP'lerini sınırlar, bu durumda `TWELVEDATA_API_KEY`
   ekle. Bunların hiçbirini gerçek ağla ben deneyemedim; ilk turun günlüğünü kontrol et (aşağıya bak).
4. **Hafıza:** Veritabanı (ayarların, açık formasyonlar, istatistik) GitHub önbelleğinde saklanır.
   GitHub önbelleği 7 gün hiç kullanılmazsa siler; bot her 5 dakikada kullandığı için normalde sorun olmaz.
   Silinirse bot ayarları varsayılana döner ve ilk taramayı sessiz yapar.
5. **60 gün kuralı:** Public depolarda zamanlanmış işler uzun süre hareketsizlikte kapatılabilir.
   `keepalive.yml` haftada bir bunu önlemeye çalışır. Yine de bir gün durursa Actions sekmesinden
   **Run workflow** ile yeniden başlat.
6. **Bu bir analiz aracıdır, yatırım tavsiyesi değildir.**

## Sorun giderme
| Belirti | Çözüm |
|---|---|
| Bot hiç mesaj atmıyor | Önce botuna Telegram'da **Start** bastın mı? `TELEGRAM_CHAT_ID` doğru mu? |
| Actions kırmızı ✘ | Run'a tıkla, hatalı adımın günlüğünü oku. `pip install` hatası → `requirements.txt` yüklendi mi? |
| `TELEGRAM_BOT_TOKEN tanımlı değil` | Secret adı yanlış veya eksik (Adım 6). |
| `/durum` "veri alınamıyor" diyor | Günlükte `HTTP 451/403` varsa o kaynak engelli; sıradaki kaynağa geçer. Hepsi hatalıysa günlüğü bana gönder. |
| Bir parite için uyarı geliyor | Parite o borsada yok demektir: `/cikar HYPEUSDT` |
| Hiç sinyal gelmiyor | Normal olabilir; harmonikler seyrektir. `/ayar` → skoru düşür (ör. 45) veya `/aktif` bak. |
| Token'ı yanlışlıkla paylaştım | BotFather → `/revoke` ile yenile, Secret'ı güncelle. |

## Botu durdurmak
Actions → Harmonik Bot → sağ üstte **⋯ → Disable workflow**. Telegram'dan geçici durdurmak için `/duraklat`, devam için `/devam`.
