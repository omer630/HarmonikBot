import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import numpy as np
from hbot import data as D
from hbot.config import classify, normalize_symbol


def test_symbols():
    assert normalize_symbol("ınj") == "INJ" and normalize_symbol("fıl") == "FIL"
    assert classify("ınj").symbol == "INJUSDT" and classify("fıl").symbol == "FILUSDT"
    assert classify("btcusdt").symbol == "BTCUSDT" and not classify("btc").is_fx
    assert classify("eurusd").is_fx and classify("XAUUSD").is_fx and classify("xagusd").is_fx
    assert classify("USDTRY").is_fx


def test_parsers():
    now = int(time.time()) // 900 * 900
    bin_rows = [[(now - 900 * (5 - i)) * 1000, "1", "2", "0.5", "1.5", "10"] for i in range(5)]
    ts, o, h, l, c, v = D.parse_binance(bin_rows)
    assert ts[-1] == now - 900 and c[0] == "1.5"
    by = D.parse_bybit([[str((now - 900 * i) * 1000), "1", "2", "0.5", "1.5", "10", "0"] for i in range(5)])
    assert by[0][0] < by[0][-1]                                  # eskiden yeniye
    yj = {"chart": {"result": [{"timestamp": [now - 900, now], "indicators": {"quote": [
        {"open": [1, None], "high": [2, 2], "low": [0.5, 0.5], "close": [1.5, 1.5], "volume": [None, 3]}]}}]}}
    t, *_ = D.parse_yahoo(yj); assert t == [now - 900]           # boş (None) mum atılır
    try:
        D.parse_yahoo({"chart": {"result": None, "error": {"code": "Not Found"}}}); assert False
    except D.SymbolNotFound:
        pass
    try:
        D.parse_twelve({"status": "error", "code": 429, "message": "limit"}); assert False
    except D.RateLimited:
        pass


def test_closed_candle_filter_and_fx_4h():
    tf = 900; now = time.time()
    start = int(now // tf) * tf
    ts = np.array([start - 2 * tf, start - tf, start], dtype=np.int64)   # sonuncusu oluşmakta olan mum
    b = D._bars(ts, [1, 1, 1], [2, 2, 2], [0.5, 0.5, 0.5], [1.5, 1.5, 1.5], [1, 1, 1])
    assert len(D.drop_open(b, tf, now)) == 2
    # FX 4s: 8 saatlik 1s mum -> 4s mumlara dönüşür, OHLC doğru birleşir
    base = 1_760_000_000 // 3600 * 3600
    ts = np.arange(base, base + 24 * 3600, 3600, dtype=np.int64)
    px = np.linspace(1.0, 1.1, 24)
    b1 = D._bars(ts, px, px + 0.01, px - 0.01, px + 0.002, np.ones(24))
    r = D.resample_fx_4h(b1)
    assert 5 <= len(r) <= 7 and (r.h >= r.l).all() and (r.h[1:-1] > r.o[1:-1] - 1).all()


def test_fx_market_hours():
    sat = 1_760_000_000                                          # herhangi bir an
    import calendar
    assert D.fx_market_closed(calendar.timegm((2026, 10, 17, 12, 0, 0)))      # Cumartesi
    assert not D.fx_market_closed(calendar.timegm((2026, 10, 14, 12, 0, 0)))  # Çarşamba


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("OK", name)
