"""Veri sağlayıcıları — OANDA gerekmez.

Kripto : Binance spot → Binance futures → Bybit linear → Bybit spot (sıra .env'den ayarlanır)
Forex  : Yahoo Finance (anahtarsız) → Twelve Data (ücretsiz anahtar, opsiyonel)
Hepsi sadece KAPANMIŞ mumları döndürür.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

from .config import TF_SECONDS, TV_INTERVAL, Env, Instrument
from .models import Bars

log = logging.getLogger("hbot.data")

# Test için değiştirilebilir taban adresler
BASES = {
    "binance_spot": ["https://api.binance.com", "https://data-api.binance.vision"],
    "binance_futures": ["https://fapi.binance.com"],
    "bybit": ["https://api.bybit.com", "https://api.bytick.com"],
    "gate": ["https://api.gateio.ws"],
    "yahoo": ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"],
    "twelvedata": ["https://api.twelvedata.com"],
}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


class DataError(Exception):
    pass


class SymbolNotFound(DataError):
    pass


class Blocked(DataError):
    pass


class RateLimited(DataError):
    def __init__(self, msg: str = "", retry_after: float = 5.0):
        super().__init__(msg)
        self.retry_after = retry_after


class Transient(DataError):
    pass


# ═════════════════════════════ yardımcılar ═════════════════════════════
def _bars(ts, o, h, l, c, v, source: str = "", tv: str = "") -> Bars:
    ts = np.asarray(ts, dtype=np.int64)
    o, h, l, c = (np.asarray(x, dtype=float) for x in (o, h, l, c))
    v = np.asarray(v, dtype=float)
    order = np.argsort(ts, kind="stable")
    ts, o, h, l, c, v = ts[order], o[order], h[order], l[order], c[order], v[order]
    ok = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c) & (h >= l)
    # tekrar eden zaman damgalarını at
    keep = np.concatenate(([True], np.diff(ts) > 0)) & ok
    return Bars(ts[keep], o[keep], h[keep], l[keep], c[keep], np.nan_to_num(v[keep]), source, tv)


def drop_open(b: Bars, tf_s: int, now: float | None = None) -> Bars:
    """Henüz kapanmamış (oluşmakta olan) mumu at."""
    now = time.time() if now is None else now
    m = (b.ts + tf_s) <= now + 1
    if m.all():
        return b
    return Bars(b.ts[m], b.o[m], b.h[m], b.l[m], b.c[m], b.v[m], b.source, b.tv)


def resample_fx_4h(b1h: Bars) -> Bars:
    """1 saatlik FX mumlarından, TradingView FX ile uyumlu 4 saatlik mumlar üretir (17:00 New York çıpası)."""
    if len(b1h) == 0:
        return b1h
    idx = pd.to_datetime(b1h.ts, unit="s", utc=True)
    local = idx.tz_convert("America/New_York")
    off = np.asarray((local.tz_localize(None) - idx.tz_localize(None)).total_seconds(), dtype=np.int64)
    ts = b1h.ts.astype(np.int64)
    start = ts - (((ts + off) - 17 * 3600) % 14400)
    df = pd.DataFrame({"s": start, "o": b1h.o, "h": b1h.h, "l": b1h.l, "c": b1h.c, "v": b1h.v})
    g = df.groupby("s", sort=True)
    out = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(), "v": g["v"].sum()})
    return _bars(out.index.values, out.o, out.h, out.l, out.c, out.v, b1h.source, b1h.tv)


def fx_market_closed(now: float | None = None) -> bool:
    """Cuma ~22:00 UTC → Pazar ~21:00 UTC arası forex kapalı (yaklaşık)."""
    t = time.gmtime(time.time() if now is None else now)
    wd, hr = t.tm_wday, t.tm_hour     # Pzt=0 … Paz=6
    if wd == 5:
        return True
    if wd == 4 and hr >= 22:
        return True
    if wd == 6 and hr < 21:
        return True
    return False


def tv_link(tv_symbol: str, tf: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol={quote(tv_symbol, safe='')}&interval={TV_INTERVAL[tf]}"


# ═════════════════════════════ ayrıştırıcılar (saf fonksiyonlar) ═════════════════════════════
def parse_binance(rows: list) -> tuple:
    ts = [int(r[0]) // 1000 for r in rows]
    return ts, [r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows], [r[4] for r in rows], [r[5] for r in rows]


def parse_bybit(rows: list) -> tuple:
    rows = list(reversed(rows))        # Bybit en yeniyi başa koyar
    ts = [int(r[0]) // 1000 for r in rows]
    return ts, [r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows], [r[4] for r in rows], [r[5] for r in rows]


def parse_yahoo(j: dict) -> tuple:
    res = (j.get("chart") or {}).get("result")
    if not res:
        err = (j.get("chart") or {}).get("error")
        raise SymbolNotFound(str(err))
    r = res[0]
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    cols = [q.get(k) or [None] * len(ts) for k in ("open", "high", "low", "close", "volume")]
    rows = [(t, *vals) for t, *vals in zip(ts, *cols) if None not in vals[:4]]
    if not rows:
        return [], [], [], [], [], []
    t, o, h, l, c, v = zip(*[(a, b, c_, d, e, f if f is not None else 0) for a, b, c_, d, e, f in rows])
    return list(t), list(o), list(h), list(l), list(c), list(v)


def parse_twelve(j: dict) -> tuple:
    if j.get("status") == "error" or "values" not in j:
        code = j.get("code")
        msg = str(j.get("message", ""))
        if code == 429:
            raise RateLimited(msg, 20.0)
        if code in (400, 404):
            raise SymbolNotFound(msg)
        if code in (401, 403):
            raise Blocked(msg)
        raise Transient(msg)
    vals = j["values"]
    dt = pd.to_datetime([v["datetime"] for v in vals], utc=True)
    ts = [int(x.timestamp()) for x in dt]
    return (ts, [v["open"] for v in vals], [v["high"] for v in vals], [v["low"] for v in vals],
            [v["close"] for v in vals], [v.get("volume", 0) or 0 for v in vals])


# ═════════════════════════════ HTTP ═════════════════════════════
class Http:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json"})
        adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16)
        self.s.mount("https://", adapter)
        self.s.mount("http://", adapter)

    def get_json(self, url: str, params: dict | None = None, timeout: float = 20.0, attempts: int = 3):
        last: Exception | None = None
        for k in range(attempts):
            try:
                r = self.s.get(url, params=params, timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                last = Transient(f"{type(e).__name__}: {e}")
                time.sleep(0.8 * (2 ** k))
                continue
            if r.status_code in (418, 429):
                ra = float(r.headers.get("Retry-After", "5") or 5)
                raise RateLimited(f"HTTP {r.status_code}", ra)
            if r.status_code in (403, 451):
                raise Blocked(f"HTTP {r.status_code}")
            if r.status_code in (400, 404):
                raise SymbolNotFound(f"HTTP {r.status_code}: {r.text[:160]}")
            if r.status_code >= 500:
                last = Transient(f"HTTP {r.status_code}")
                time.sleep(0.8 * (2 ** k))
                continue
            try:
                return r.json()
            except ValueError as e:
                raise Transient(f"JSON çözülemedi: {e}")
        raise last or Transient("bilinmeyen ağ hatası")


# ═════════════════════════════ kaynaklar ═════════════════════════════
TF_BINANCE = {"15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"}
TF_BYBIT = {"15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D", "1w": "W"}
TF_YAHOO = {"15m": ("15m", "30d"), "30m": ("30m", "60d"), "1h": ("60m", "6mo"), "4h": ("60m", "1y"),
            "1d": ("1d", "5y"), "1w": ("1wk", "10y")}
TF_TWELVE = {"15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1day", "1w": "1week"}


class Source:
    name = ""

    def tv_symbol(self, inst: Instrument) -> str:
        raise NotImplementedError

    def fetch(self, http: Http, inst: Instrument, tf: str, limit: int) -> Bars:
        raise NotImplementedError


class BinanceSpot(Source):
    name = "binance_spot"

    def tv_symbol(self, inst): return f"BINANCE:{inst.symbol}"

    def fetch(self, http, inst, tf, limit):
        last: Exception | None = None
        for base in BASES["binance_spot"]:
            try:
                rows = http.get_json(f"{base}/api/v3/klines",
                                     {"symbol": inst.symbol, "interval": TF_BINANCE[tf], "limit": limit + 1})
                break
            except (Blocked, Transient) as e:
                last = e
        else:
            raise last or Transient("binance spot")
        if not rows:
            raise SymbolNotFound(inst.symbol)
        return _bars(*parse_binance(rows), self.name, self.tv_symbol(inst))


class BinanceFutures(Source):
    name = "binance_futures"

    def tv_symbol(self, inst): return f"BINANCE:{inst.symbol}.P"

    def fetch(self, http, inst, tf, limit):
        last: Exception | None = None
        for base in BASES["binance_futures"]:
            try:
                rows = http.get_json(f"{base}/fapi/v1/klines",
                                     {"symbol": inst.symbol, "interval": TF_BINANCE[tf], "limit": limit + 1})
                break
            except (Blocked, Transient) as e:
                last = e
        else:
            raise last or Transient("binance futures")
        if not rows:
            raise SymbolNotFound(inst.symbol)
        return _bars(*parse_binance(rows), self.name, self.tv_symbol(inst))


class GateSpot(Source):
    """Gate.io spot — ABD IP'lerinde (GitHub Actions) engellenmeyen yedek kaynak."""
    name = "gate_spot"

    def tv_symbol(self, inst): return f"GATEIO:{inst.symbol}"

    def fetch(self, http, inst, tf, limit):
        sym = inst.symbol
        if not sym.endswith("USDT"):
            raise SymbolNotFound(sym)
        pair = f"{sym[:-4]}_USDT"
        last: Exception | None = None
        for base in BASES["gate"]:
            try:
                rows = http.get_json(f"{base}/api/v4/spot/candlesticks",
                                     {"currency_pair": pair, "interval": TF_BINANCE[tf], "limit": min(limit + 1, 1000)})
                break
            except (Blocked, Transient) as e:
                last = e
        else:
            raise last or Transient("gate")
        if not isinstance(rows, list) or not rows:
            raise SymbolNotFound(pair)
        # Gate: [ts, quote_vol, close, high, low, open, base_vol, closed]
        ts = [int(r[0]) for r in rows]
        return _bars(ts, [r[5] for r in rows], [r[3] for r in rows], [r[4] for r in rows],
                     [r[2] for r in rows], [r[6] for r in rows], self.name, self.tv_symbol(inst))


class Bybit(Source):
    def __init__(self, category: str):
        self.category = category
        self.name = "bybit_linear" if category == "linear" else "bybit_spot"

    def tv_symbol(self, inst): return f"BYBIT:{inst.symbol}.P" if self.category == "linear" else f"BYBIT:{inst.symbol}"

    def fetch(self, http, inst, tf, limit):
        last: Exception | None = None
        for base in BASES["bybit"]:
            try:
                j = http.get_json(f"{base}/v5/market/kline", {"category": self.category, "symbol": inst.symbol,
                                                              "interval": TF_BYBIT[tf], "limit": min(1000, limit + 1)})
                break
            except (Blocked, Transient) as e:
                last = e
        else:
            raise last or Transient("bybit")
        code = j.get("retCode")
        if code == 10006:
            raise RateLimited("bybit", 5.0)
        if code != 0:
            raise SymbolNotFound(f"bybit retCode={code} {j.get('retMsg')}")
        rows = (j.get("result") or {}).get("list") or []
        if not rows:
            raise SymbolNotFound(inst.symbol)
        return _bars(*parse_bybit(rows), self.name, self.tv_symbol(inst))


class Yahoo(Source):
    name = "yahoo"
    _lock = threading.Lock()
    _last = 0.0

    def tv_symbol(self, inst): return f"OANDA:{inst.symbol}"

    @staticmethod
    def ysym(inst: Instrument) -> str:
        return f"{inst.symbol}=X"

    def fetch(self, http, inst, tf, limit):
        interval, rng = TF_YAHOO[tf]
        with Yahoo._lock:                       # Yahoo'yu nazik kullan
            wait = 1.5 - (time.time() - Yahoo._last)
            if wait > 0:
                time.sleep(wait)
            Yahoo._last = time.time()
        last: Exception | None = None
        j = None
        for base in BASES["yahoo"]:
            try:
                j = http.get_json(f"{base}/v8/chart/{quote(self.ysym(inst))}",
                                  {"interval": interval, "range": rng, "includePrePost": "false"})
                break
            except (Blocked, Transient, RateLimited) as e:
                last = e
        if j is None:
            raise last or Transient("yahoo")
        b = _bars(*parse_yahoo(j), self.name, self.tv_symbol(inst))
        if len(b) == 0:
            raise SymbolNotFound(inst.symbol)
        if tf == "4h":
            b = resample_fx_4h(drop_open(b, 3600))
        return b


class TwelveData(Source):
    name = "twelvedata"
    _lock = threading.Lock()
    _last = 0.0

    def __init__(self, key: str, rpm: int):
        self.key, self.gap = key, 60.0 / max(1, rpm)

    def tv_symbol(self, inst): return f"OANDA:{inst.symbol}"

    def fetch(self, http, inst, tf, limit):
        if not self.key:
            raise Blocked("TWELVEDATA_API_KEY yok")
        with TwelveData._lock:
            wait = self.gap - (time.time() - TwelveData._last)
            if wait > 0:
                time.sleep(wait)
            TwelveData._last = time.time()
        sym = f"{inst.symbol[:3]}/{inst.symbol[3:]}"
        j = http.get_json(f"{BASES['twelvedata'][0]}/time_series",
                          {"symbol": sym, "interval": TF_TWELVE[tf], "outputsize": min(limit + 1, 5000),
                           "order": "ASC", "timezone": "UTC", "apikey": self.key})
        return _bars(*parse_twelve(j), self.name, self.tv_symbol(inst))


# ═════════════════════════════ merkez ═════════════════════════════
class DataHub:
    def __init__(self, env: Env):
        self.env = env
        self.http = Http()
        self.sources: dict[str, Source] = {
            "binance_spot": BinanceSpot(), "binance_futures": BinanceFutures(),
            "bybit_linear": Bybit("linear"), "bybit_spot": Bybit("spot"), "gate_spot": GateSpot(),
            "yahoo": Yahoo(), "twelvedata": TwelveData(env.twelve_key, env.twelve_rpm),
        }
        self.resolved: dict[str, str] = {}
        self.fail: dict[str, int] = {}
        self.cache: dict[tuple, tuple[float, Bars]] = {}
        self.lock = threading.Lock()
        self.errors: list[tuple[float, str, str]] = []
        self.cool: dict[str, float] = {}               # hız sınırına takılan kaynak → ne zamana kadar dinlendir

    # ── kaynak sırası ──
    def _chain(self, inst: Instrument) -> list[str]:
        names = self.env.fx_sources if inst.is_fx else self.env.crypto_sources
        names = [n for n in names if n in self.sources]
        if inst.is_fx and "twelvedata" in names and not self.env.twelve_key:
            names.remove("twelvedata")
        now = time.time()
        rested = [n for n in names if self.cool.get(n, 0) <= now]
        if rested:                                     # hepsi dinleniyorsa yine de hepsini dene
            names = rested
        r = self.resolved.get(inst.symbol)
        if r in names:
            names = [r] + [n for n in names if n != r]
        return names

    def _log_err(self, sym: str, msg: str) -> None:
        self.errors.append((time.time(), sym, msg))
        del self.errors[:-50]

    def get_bars(self, inst: Instrument, tf: str, limit: int = 800, ttl: float = 20.0) -> Bars:
        key = (inst.symbol, tf)
        now = time.time()
        with self.lock:
            hit = self.cache.get(key)
            if hit and now - hit[0] < ttl and len(hit[1]) >= min(limit, 50):
                return hit[1]
        chain = self._chain(inst)
        if not chain:
            raise DataError("Kullanılabilir veri kaynağı yok (.env kaynak listesini kontrol et)")
        errs: list[str] = []
        pinned = self.resolved.get(inst.symbol)
        for idx, name in enumerate(chain):
            src = self.sources[name]
            try:
                b = src.fetch(self.http, inst, tf, limit)
                b = drop_open(b, TF_SECONDS[tf])
                if len(b) < 30:
                    raise SymbolNotFound(f"çok az mum ({len(b)})")
                b = b.tail(limit)
                self.resolved[inst.symbol] = name
                self.fail[inst.symbol] = 0
                with self.lock:
                    self.cache[key] = (time.time(), b)
                return b
            except RateLimited as e:
                errs.append(f"{name}: hız sınırı")
                self.cool[name] = time.time() + max(300.0, min(e.retry_after, 900.0))
                if idx + 1 < len(chain):                 # sıradaki kaynağa geç
                    continue
                time.sleep(min(e.retry_after, 15))
                break
            except (SymbolNotFound, Blocked) as e:
                errs.append(f"{name}: {e}")
                continue
            except Transient as e:
                errs.append(f"{name}: {e}")
                if name == pinned:                       # sabit kaynak geçici hata verdiyse hemen değiştirme
                    self.fail[inst.symbol] = self.fail.get(inst.symbol, 0) + 1
                    if self.fail[inst.symbol] < 3:
                        break
                continue
        msg = " | ".join(errs)
        self._log_err(inst.symbol, msg)
        raise DataError(f"{inst.symbol} {tf}: {msg}")

    def tv_symbol(self, inst: Instrument) -> str:
        name = self.resolved.get(inst.symbol)
        if name:
            return self.sources[name].tv_symbol(inst)
        return f"OANDA:{inst.symbol}" if inst.is_fx else f"BINANCE:{inst.symbol}"
