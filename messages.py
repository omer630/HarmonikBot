"""Telegram mesaj metinleri (HTML). Başlık fotoğrafın altına caption olarak gider (≤1024 karakter)."""
from __future__ import annotations

import html
from typing import Optional

from .config import TV_INTERVAL
from .data import tv_link
from .fmt import fmt_price, reason_tr
from .models import Pat

TF_TXT = {"15m": "15 DK", "30m": "30 DK", "1h": "1 SAAT", "4h": "4 SAAT", "1d": "GÜNLÜK", "1w": "HAFTALIK"}
LINE = "━━━━━━━━━━━━━━"


def _head(p: Pat) -> str:
    side = "Bullish" if p.dir > 0 else "Bearish"
    return f"<b>{html.escape(p.symbol)}</b> · {TF_TXT.get(p.tf, p.tf)} · {side} {html.escape(p.rule)}"


def _pf(p: Pat, v: float) -> str:
    return fmt_price(v, p.symbol)


def _pct(p: Pat, v: float) -> str:
    base = p.fill if p.fill is not None else p.ent
    return f"{(v - base) / base * 100:+.2f}%"


def _score(p: Pat, prob: Optional[float], n: int) -> str:
    s = f"⭐ Skor: <b>{p.score:.0f}</b>/100"
    s += f" · Geçmiş başarı: <b>%{prob:.0f}</b> (n={n})" if prob is not None else " · Geçmiş başarı: yeterli örnek yok"
    return s


def _link(p: Pat, tv: str) -> str:
    sym = tv or (f"OANDA:{p.symbol}" if len(p.symbol) == 6 else f"BINANCE:{p.symbol}")
    url = html.escape(tv_link(sym, p.tf) if p.tf in TV_INTERVAL else "https://www.tradingview.com", quote=True)
    return f'📈 <a href="{url}">TradingView\'de aç</a>'


def build(kind: str, p: Pat, *, tv: str = "", prob: Optional[float] = None, samples: int = 0,
          reason: str = "", tp_j: int = 0) -> str:
    ratios = f"📐 AB/XA {p.rAB:.3f} · BC/AB {p.rBC:.3f} · CD/BC {p.rCD:.3f}"
    link = _link(p, tv)
    if kind == "armed":
        return "\n".join([
            "🟡 <b>PRZ BELİRLENDİ · İHTİMAL</b>", _head(p), LINE,
            f"📍 PRZ: <b>{_pf(p, p.zone_bottom)} – {_pf(p, p.zone_top)}</b>",
            f"🎯 Planlanan giriş (D): {_pf(p, p.ent)}",
            f"🛑 Geçersizlik / stop: {_pf(p, p.stp)}",
            _score(p, prob, samples), ratios,
            "⚠️ Fiyat henüz PRZ'ye ulaşmadı; bu yalnızca bir ihtimaldir.", link])
    if kind == "zone":
        risk = abs(p.ent - p.stp)
        rr = abs(p.tg2 - p.ent) / risk if risk > 0 else float("nan")
        lines = [
            "🟢 <b>PRZ'YE ULAŞTI</b>", _head(p), LINE,
            f"🎯 Giriş: <b>{_pf(p, p.ent)}</b>   <i>(PRZ {_pf(p, p.zone_bottom)} – {_pf(p, p.zone_top)})</i>",
            f"🛑 Stop: <b>{_pf(p, p.stp)}</b> ({_pct(p, p.stp)})",
            f"✅ TP1: <b>{_pf(p, p.tg1)}</b> ({_pct(p, p.tg1)})",
            f"✅ TP2: <b>{_pf(p, p.tg2)}</b> ({_pct(p, p.tg2)})",
            f"✅ TP3: <b>{_pf(p, p.tg3)}</b> ({_pct(p, p.tg3)})",
            "⚖️ R:R (TP2): " + ("—" if rr != rr else f"1 : {rr:.2f}"),
            _score(p, prob, samples), ratios]
        if p.div_ok:
            lines.append("📉 RSI uyumsuzluğu ✔")
        lines += ["⚠️ Kapanış bazlı sinyaldir; işlem kararı size aittir.", link]
        return "\n".join(lines)
    if kind == "cancel":
        return "\n".join(["🔴 <b>FORMASYON İPTAL</b>", _head(p), LINE,
                          f"❌ Neden: {html.escape(reason_tr(reason or p.cancel_reason))}", link])
    if kind == "target":
        j = tp_j or p.thit
        v = (p.tg1, p.tg2, p.tg3)[max(1, min(3, j)) - 1]
        extra = "Stop maliyete çekilebilir." if j == 1 else ""
        return "\n".join(x for x in [f"🎯 <b>TP{j} VURULDU</b>", _head(p), LINE,
                                     f"Seviye: <b>{_pf(p, v)}</b> ({_pct(p, v)})", extra, link] if x)
    if kind == "complete":
        return "\n".join(["🏁 <b>TÜM HEDEFLER VURULDU</b>", _head(p), LINE, link])
    if kind == "stop":
        return "\n".join(["🛑 <b>STOP OLDU</b>", _head(p), LINE, f"Stop seviyesi: {_pf(p, p.stp)}", link])
    if kind == "be":
        return "\n".join(["⚪ <b>MALİYETTE KAPANDI</b>", _head(p), LINE, f"TP{p.thit} sonrası fiyat girişe döndü.", link])
    if kind == "timeout":
        return "\n".join(["⏱ <b>SÜRE DOLDU</b>", _head(p), LINE,
                          f"Giriş sonrası azami süre doldu · {p.thit}/3 hedef.", link])
    raise ValueError(kind)
