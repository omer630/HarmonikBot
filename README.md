# HaP Harmonik Bot

Kripto ve forex'te **harmonik formasyonları 7/24 tarar**, Telegram'a görselli mesaj gönderir.
Mantık, `HaP Harmonik PRO` Pine indikatörünün Python karşılığıdır (3 ölçekli pivot, PRZ'nin D noktası beklenmeden
projeksiyonu, kalite skoru, ampirik başarı olasılığı). Tüm hesap **kapanmış mumlarla** yapılır (repaint yok).

## Mesaj akışı
| | Ne zaman | İçerik |
|---|---|---|
| 🟡 **PRZ belirlendi** | XABC oluştu ve fiyat B seviyesini geçti | PRZ aralığı, planlanan giriş, stop, skor, oranlar |
| 🟢 **PRZ'ye ulaştı** | Mum kapanışında fiyat PRZ'ye değdi | **Giriş, stop, TP1-2-3**, R:R, skor |
| 🔴 **İptal** | C aşıldı · süre doldu · PRZ'ye yaklaşmadan ters yöne kaçtı | Neden |
| 🎯 Sonuç | TP1/TP2/TP3 · stop · maliyette kapanış · süre doldu | (Ayarlardan kapatılabilir) |

Her mesajda **kart görseli** (büyük parite adı, zaman dilimi, yön ve formasyon adı; mum grafiği üzerinde XABCD, PRZ
kutusu, giriş/stop/TP çizgileri; sağda harmonik şekil paneli) ve **TradingView linki** vardır.
Aynı formasyonun mesajları birbirine **yanıt (reply)** olarak zincirlenir.

## Varsayılan izleme
- Kripto (24): BTC ETH ZEC SOL XRP HYPE BNB NEAR ADA SUI UNI DOGE ENA PUMP WLD TAO AVAX LTC ARB DOT HBAR INJ ONDO FIL
- Forex/emtia (9): EURUSD GBPUSD AUDUSD NZDUSD USDCAD USDJPY USDCHF XAUUSD XAGUSD
- Zaman dilimleri: 15 dk · 1 saat · 4 saat · günlük (30 dk da seçilebilir)
- Formasyonlar: Gartley, Bat, Alt Bat, Butterfly, Crab, Deep Crab, Shark, Cypher (+ kendi kuralın: "Özel")

## Kurulum
1. **Bot oluştur:** Telegram'da @BotFather → `/newbot` → token'ı al.
2. **Kur:** Python 3.10+ gerekir.
   ```bash
   python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env                                   # içine TELEGRAM_BOT_TOKEN'ı yaz
   python main.py
   ```
3. Telegram'da botu aç, `/start` yaz. (`.env` içinde `TELEGRAM_CHAT_ID` yoksa ilk `/start` yazan sahip olur.)
4. `/test` ile örnek bir kart gelmeli. Geldiyse görsel ve mesaj hattı çalışıyordur.

> İlk tarama geçmişi **sessizce** işler (istatistik ve olasılık için). Mesajlar yalnızca yeni kapanan mumlarla gelir.

## 7/24 çalıştırma
Bilgisayar kapanınca bot durur. Sürekli çalışması için ucuz bir VPS veya her zaman açık bir makine gerekir.
- **systemd:** `deploy/hbot.service` dosyasını kullan.
- **Docker:** `docker compose up -d --build` (veriler `./data` içinde kalır).

## Komutlar
`/aktif` · `/istatistik [formasyon|tf|parite] [canli|gecmis|hepsi]` · `/ayar` · `/ekle BTC SOL EURUSD` · `/cikar BTC` ·
`/kural` · `/hedef 0.382 0.618 1.0` · `/liste` · `/durum` · `/duraklat` · `/devam` · `/tara` · `/test` · `/yardim`

**/ayar menüsü:** pariteleri aç/kapat, zaman dilimi seç, formasyon aç/kapat, yön (bullish/bearish/ikisi), minimum skor,
bildirim türleri, görsel kart, başarı hedefi (TP1/2/3), giriş modu (limit / dönüş mumu), iptal kuralları.

**/kural:** her formasyonun AB/XA, XC/XA, BC/AB, CD/BC ve D oranı aralıkları, giriş ve stop oranı elle yazılır:
`/kural Gartley ab 0.60 0.68` · `/kural Bat giris 0.886` · `/kural Cypher ref XC` · `/kural Bat sifirla`

## Veri kaynakları (OANDA gerekmez)
- **Kripto:** Binance spot → Binance futures → Bybit linear → Bybit spot (otomatik yedekli; hangisinde varsa onu kullanır).
- **Forex/altın/gümüş:** Yahoo Finance (anahtarsız). İstersen `FX_SOURCES=twelvedata,yahoo` ve ücretsiz Twelve Data anahtarı.
- Yahoo 4 saatlik mum vermez; bot saatlikten TradingView FX ile uyumlu (17:00 New York hizalı) 4 saatlik mum üretir.
- Forex hafta sonu kapalıyken taranmaz.

## Bilinmesi gerekenler
- **Veri farkı:** Yahoo forex verisi TradingView/OANDA ile birebir aynı olmayabilir (özellikle fitiller); sinyal seviyeleri küçük farklar gösterebilir.
- **Kapanış bazlı:** "PRZ'ye ulaştı" mum kapanışında anlaşılır; mum içi anlık değmeler beklenir.
- **İstatistik** ilk kurulumda geçmiş taramadan beslenir; örneklem azken "yeterli örnek yok" yazar. Geçmiş başarı gelecek garantisi değildir.
- Bazı kripto paraları (ör. HYPE, PUMP) her borsada olmayabilir; bulunamazsa bot uyarır, `/cikar` ile kaldırabilirsin.
- Bu bir **analiz aracıdır, yatırım tavsiyesi değildir.**

## Test
```bash
python tests/run_all.py     # ağ gerektirmez: motor, veri ayrıştırıcılar, tarayıcı akışı, komutlar
```

---
## Sunucusuz kurulum (GitHub Actions)
Sunucun yoksa **KURULUM_GITHUB.md** dosyasındaki adımları izle: `.github/workflows/bot.yml` botu her 5 dakikada
bir `python main.py --once` ile çalıştırır, veritabanı GitHub önbelleğinde saklanır.
