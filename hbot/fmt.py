"""Biçimlendirme yardımcıları (fiyat, zaman, çubuklar)."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import FX_CODES


def price_decimals(price: float, symbol: str = "") -> int:
    s = symbol.upper()
    if len(s) == 6 and s[:3] in FX_CODES and s[3:] in FX_CODES:
        if s.startswith("XAU"):
            return 2
        if s.startswith("XAG"):
            return 3
        return 3 if "JPY" in s else 5
    p = abs(price)
    if p == 0 or not math.isfinite(p):
        return 2
    return int(max(2, min(8, 4 - math.floor(math.log10(p)))))


def fmt_price(price: float | None, symbol: str = "", decimals: int | None = None) -> str:
    if price is None or not math.isfinite(price):
        return "—"
    d = price_decimals(price, symbol) if decimals is None else decimals
    return f"{price:.{d}f}"


def fmt_pct(v: float, signed: bool = True) -> str:
    return f"{v:+.2f}%" if signed else f"{v:.2f}%"


def bar(v: float, n: int = 5) -> str:
    fl = max(0, min(n, int(round(v * n))))
    return "▰" * fl + "▱" * (n - fl)


MONTHS_TR = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def tz_of(name: str) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def fmt_dt(ts: float, tz: str = "Europe/Istanbul", seconds: bool = False) -> str:
    d = datetime.fromtimestamp(ts, tz_of(tz))
    return f"{d.day} {MONTHS_TR[d.month - 1]} {d.year} · {d.strftime('%H:%M:%S' if seconds else '%H:%M')}"


def fmt_short(ts: float, tz: str, daily: bool) -> str:
    d = datetime.fromtimestamp(ts, tz_of(tz))
    return d.strftime("%d.%m") if daily else d.strftime("%d.%m %H:%M")


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


REASON_TR = {
    "c_exceeded": "C noktası aşıldı (formasyon geçersiz)",
    "timeout": "PRZ'ye ulaşma süresi doldu",
    "escape": "PRZ'ye yaklaşmadan ters yöne kaçtı",
    "stop_before": "Dönüş teyidi gelmeden stop seviyesi kırıldı",
    "expired": "Formasyon tarama penceresinden çıktı",
}


def reason_tr(key: str) -> str:
    return REASON_TR.get(key, key or "")
