import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from hbot.bot import BotApp
from hbot.config import Env
from hbot.db import DB
from hbot.demo import synthetic_bars
from hbot.scanner import Notifier, Scanner
from tests.fakes import FakeHub, FakeTG


def make(owner=True):
    tmp = Path(tempfile.mkdtemp())
    db = DB(tmp / "t.db"); tg = FakeTG()
    env = Env(token="x", chat_id="", allowed=set(), crypto_sources=[], fx_sources=[], twelve_key="", twelve_rpm=7,
              tz="Europe/Istanbul", data_dir=tmp, log_level="INFO")
    hub = FakeHub(synthetic_bars("Gartley", 1, "target"))
    app = BotApp(tg, db, None, env, hub)
    sc = Scanner(db, hub, Notifier(tg, app.chats)); app.sc = sc
    if owner:
        app.handle(msg("/start", 111))
    return app, tg, db, sc


def msg(text, uid=111, chat=None):
    return {"update_id": 1, "message": {"message_id": 5, "text": text, "from": {"id": uid}, "chat": {"id": chat or uid, "type": "private"}}}


def cb(data, uid=111, mid=7):
    return {"update_id": 2, "callback_query": {"id": "c1", "data": data, "from": {"id": uid},
                                               "message": {"message_id": mid, "chat": {"id": uid}}}}


def last(tg, kind=None):
    return [m for m in tg.sent if kind is None or m[0] == kind][-1]


def test_owner_claim_and_auth():
    app, tg, db, sc = make(owner=False)
    app.handle(msg("/start", 111))
    assert db.get_meta("owners") == [111] and "Sahip" in last(tg)[2]
    app.handle(msg("/aktif", 999))
    assert "yetkin yok" in last(tg)[2]
    app.handle(msg("/start", 222))                      # sahip varken başkası sahiplenemez
    assert "yetkin yok" in last(tg)[2] and db.get_meta("owners") == [111]


def test_settings_menu_changes():
    app, tg, db, sc = make()
    app.handle(msg("/ayar")); assert "Ayarlar" in last(tg)[2] and last(tg)[5]
    app.handle(cb("m:tf")); assert last(tg, "edit")[5]["inline_keyboard"]
    app.handle(cb("s:tf:30m")); assert "30m" in db.load_settings()["timeframes"]
    app.handle(cb("s:tf:15m")); assert "15m" not in db.load_settings()["timeframes"]
    for t in ("30m", "1h", "4h"):                       # hepsi kapanırsa son biri korunur
        app.handle(cb(f"s:tf:{t}"))
    assert db.load_settings()["timeframes"] == ["1d"]
    app.handle(cb("s:tf:1d")); assert db.load_settings()["timeframes"] == ["1d"]
    app.handle(cb("s:pat:4")); assert db.load_settings()["patterns"]["Crab"] is False
    app.handle(cb("s:dir:bull")); assert db.load_settings()["direction"] == "bull"
    app.handle(cb("s:score:+5")); assert db.load_settings()["min_score"] == 60
    app.handle(cb("s:score:=70")); assert db.load_settings()["min_score"] == 70
    app.handle(cb("s:ntf:cancel")); assert db.load_settings()["notify"]["cancel"] is False
    app.handle(cb("s:ntf:card")); assert db.load_settings()["card"] is False
    app.handle(cb("s:succ:2")); assert db.load_settings()["succ_target"] == 2
    app.handle(cb("s:sym:BTCUSDT")); assert "BTCUSDT" in db.load_settings()["symbols_off"]
    app.handle(cb("s:sym:BTCUSDT")); assert "BTCUSDT" not in db.load_settings()["symbols_off"]
    app.handle(cb("s:pause")); assert db.load_settings()["paused"] is True
    assert sc.tick() == 0                               # duraklatılınca tarama başlamaz
    app.handle(cb("m:close")); assert "kaydedildi" in last(tg, "edit")[2]


def test_symbols_commands():
    app, tg, db, sc = make()
    app.handle(msg("/ekle ınj sui eurjpy btc")); t = last(tg)[2]; print(t)
    S = db.load_settings()
    assert "EURJPY" in S["symbols"] and "SUIUSDT" in S["symbols"] and S["symbols"].count("BTCUSDT") == 1
    app.handle(msg("/cikar eurjpy fil")); S = db.load_settings()
    assert "EURJPY" not in S["symbols"] and "FILUSDT" not in S["symbols"]
    app.handle(msg("/liste")); assert "Kripto" in last(tg)[2] and "XAUUSD" in last(tg)[2]


def test_rule_and_target_commands():
    app, tg, db, sc = make()
    app.handle(msg("/kural")); assert "/kural Gartley" in last(tg)[2]
    app.handle(msg("/kural deep crab")); assert "Deep Crab" in last(tg)[2] and "0.856" in last(tg)[2]
    app.handle(msg("/kural Gartley ab 0.60 0.68")); assert db.load_settings()["rules"]["Gartley"]["ab"] == [0.6, 0.68]
    app.handle(msg("/kural Gartley ab 0.9 0.1")); assert "hatalı" in last(tg)[2]
    app.handle(msg("/kural Cypher ref XA")); assert db.load_settings()["rules"]["Cypher"]["ref"] == "XA"
    app.handle(msg("/kural Gartley sifirla")); assert "Gartley" not in db.load_settings()["rules"]
    app.handle(msg("/hedef 0.5 1 1.618")); assert db.load_settings()["t3"] == 1.618
    app.handle(msg("/hedef 3 2 1")); assert "Kullanım" in last(tg)[2]


def test_status_stats_active_and_demo_card():
    app, tg, db, sc = make()
    B = sc.hub.full
    sc.hub.k = 205; S = db.load_settings(); sc.scan_key("BTCUSDT", "4h", S)
    for k in range(206, len(B) + 1):
        sc.hub.k = k; sc.scan_key("BTCUSDT", "4h", S)
    app.handle(msg("/aktif")); print(last(tg)[2][:300]); assert "BTCUSDT" in last(tg)[2]
    app.handle(msg("/durum")); assert "Durum" in last(tg)[2]
    app.handle(msg("/istatistik")); t = last(tg)[2]; print(t); assert "İstatistik" in t and "Gartley" in t
    app.handle(cb("st:tf:live", mid=9)); assert "Zaman dilimi" in last(tg, "edit")[2]
    app.handle(msg("/istatistik parite canli")); assert "Parite" in last(tg)[2]
    n = len(tg.sent); app.handle(msg("/test"))
    p = last(tg); assert p[0] == "photo" and p[4] > 20000 and "TEST" in p[2]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("OK", name)
