import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from hbot.db import DB
from hbot.demo import synthetic_bars
from hbot.scanner import Notifier, Scanner
from tests.fakes import FakeHub, FakeTG


def _setup(bars, k):
    db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
    tg = FakeTG()
    hub = FakeHub(bars, k)
    sc = Scanner(db, hub, Notifier(tg, lambda: [111]))
    return db, tg, hub, sc


def kinds(tg):
    return [m[2].split("\n")[0] for m in tg.sent if m[0] in ("msg", "photo")]


def feed(sc, hub, S, a, b):
    for k in range(a, b + 1):
        hub.k = k
        sc.scan_key("BTCUSDT", "4h", S)


def test_live_flow_armed_zone_target():
    B = synthetic_bars("Gartley", 1, "target")
    db, tg, hub, sc = _setup(B, 205)
    S = db.load_settings()
    sc.scan_key("BTCUSDT", "4h", S)                 # ilk (sıcak) tarama: C henüz yok → sessiz
    assert kinds(tg) == []
    feed(sc, hub, S, 206, len(B))
    ks = kinds(tg)
    print(ks)
    assert any("PRZ BELİRLENDİ" in x for x in ks), ks
    assert any("PRZ'YE ULAŞTI" in x for x in ks), ks
    assert any("TP1 VURULDU" in x for x in ks), ks
    assert ks.index([x for x in ks if "PRZ BELİRLENDİ" in x][0]) < ks.index([x for x in ks if "PRZ'YE" in x][0])
    assert sum("PRZ BELİRLENDİ" in x for x in ks) == 1 and sum("PRZ'YE ULAŞTI" in x for x in ks) == 1
    # görselli gitti ve zincir (reply) kuruldu
    photos = [m for m in tg.sent if m[0] == "photo"]
    assert photos and all(m[4] > 20000 for m in photos)
    assert photos[1][3] == photos[0][6]             # 2. mesaj ilkine yanıt


def test_cancel_flow():
    B = synthetic_bars("Bat", -1, "cancel")
    db, tg, hub, sc = _setup(B, 205)
    S = db.load_settings()
    sc.scan_key("BTCUSDT", "4h", S)
    feed(sc, hub, S, 206, len(B))
    ks = kinds(tg)
    print(ks)
    assert any("PRZ BELİRLENDİ" in x for x in ks) and any("FORMASYON İPTAL" in x for x in ks), ks


def test_cold_start_is_silent_but_tracked():
    B = synthetic_bars("Gartley", 1, "armed")
    db, tg, hub, sc = _setup(B, len(B))
    S = db.load_settings()
    sc.scan_key("BTCUSDT", "4h", S)
    sc.scan_key("BTCUSDT", "4h", S)                 # aynı mum: tekrar işlenmez
    print(kinds(tg), len(db.active_patterns()))
    assert len(db.active_patterns()) >= 1           # /aktif'te görünür
    n1 = len(tg.sent)
    sc.scan_key("BTCUSDT", "4h", S)
    assert len(tg.sent) == n1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("OK", name)
