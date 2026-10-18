"""HaP Harmonik Bot — başlatıcı.  Çalıştır:  python main.py   (ayarlar .env dosyasından okunur)"""
import logging
import signal
import os
import sys
import time
import threading
from logging.handlers import RotatingFileHandler

from hbot.bot import BotApp
from hbot.config import load_env
from hbot.data import DataHub
from hbot.db import DB
from hbot.scanner import Notifier, Scanner
from hbot.telegram_api import Telegram


def main() -> int:
    if "--once" in sys.argv:
        os.environ["RUN_ONCE"] = "1"
    env = load_env()
    logging.basicConfig(level=getattr(logging, env.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(),
                                  RotatingFileHandler(env.data_dir / "bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")])
    log = logging.getLogger("hbot")
    if not env.token:
        log.error("TELEGRAM_BOT_TOKEN tanımlı değil. .env.example dosyasını .env olarak kopyalayıp doldur.")
        return 2
    db = DB(env.data_dir / "harmonic.db")
    hub = DataHub(env)
    tg = Telegram(env.token)
    app = BotApp(tg, db, None, env, hub)                       # tarayıcı oluşunca bağlanır
    scanner = Scanner(db, hub, Notifier(tg, app.chats, env.tz))
    app.sc = scanner
    stop = threading.Event()
    if "--once" in sys.argv or os.environ.get("RUN_ONCE") == "1":
        # GitHub Actions modu: RUN_SECONDS boyunca tara + komutları dinle, sonra temiz kapan
        secs = float(os.environ.get("RUN_SECONDS", "280"))
        deadline = time.time() + secs
        scanner.seed_schedule()
        threading.Thread(target=scanner.run_forever, args=(stop,), name="scanner", daemon=True).start()
        log.info("Tek seferlik mod · %.0f sn", secs)
        try:
            app.poll_until(deadline, stop)
        finally:
            stop.set()
            scanner.finish()
            db.close()
        log.info("Tur bitti")
        logging.shutdown()
        os._exit(0)             # takılı kalmış ağ iş parçacıkları çıkışı geciktirmesin
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    threading.Thread(target=scanner.run_forever, args=(stop,), name="scanner", daemon=True).start()
    log.info("Bot başlıyor · veri klasörü: %s", env.data_dir)
    app.poll_forever(stop)
    log.info("Kapanıyor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
