"""Telegram kart görseli (PNG).

Sol üstte BÜYÜK parite adı + zaman dilimi + yön + harmonik adı, sağ üstte durum rozeti.
Ortada mum grafiği üzerine XABCD / PRZ kutusu / giriş-stop-TP çizgileri (grafik görseli),
sağda sadeleştirilmiş harmonik şekil paneli (harmonik görseli), altta seviye kutuları."""
from __future__ import annotations

import datetime as dt
import io
import threading
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import numpy as np  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle  # noqa: E402

from .config import TF_SECONDS  # noqa: E402
from .fmt import fmt_price as _fp  # noqa: E402
from .fmt import reason_tr  # noqa: E402
from .models import Bars, Pat  # noqa: E402

_LOCK = threading.Lock()

BG, PANEL, GRID = "#070B12", "#0D1420", "#172033"
TXT, MUTED, DIM = "#E8EEF8", "#7F8EA8", "#4A5670"
GREEN, RED, AMBER, BLUE, ORANGE = "#2EBD85", "#F6465D", "#F5A524", "#4C8DF6", "#FF9F43"
UP, DOWN = "#1FA67A", "#D9485F"
TF_TXT = {"15m": "15 DK", "30m": "30 DK", "1h": "1 SAAT", "4h": "4 SAAT", "1d": "GÜNLÜK", "1w": "HAFTALIK"}

# tür -> (rozet, alt yazı, renk)
STATUS = {
    "armed":    ("PRZ BELİRLENDİ", "İHTİMAL · fiyat henüz PRZ'ye ulaşmadı", AMBER),
    "zone":     ("PRZ'YE ULAŞTI", "giriş bölgesi · seviyeler aşağıda", GREEN),
    "cancel":   ("FORMASYON İPTAL", "", RED),
    "target":   ("HEDEF VURULDU", "hedef seviyesine ulaşıldı", BLUE),
    "complete": ("TÜM HEDEFLER", "TP3 vuruldu", GREEN),
    "stop":     ("STOP OLDU", "stop seviyesine gelindi", RED),
    "be":       ("MALİYETTE KAPANDI", "TP1 sonrası stop maliyete çekilmişti", MUTED),
    "timeout":  ("SÜRE DOLDU", "azami bekleme süresi bitti", MUTED),
}
_MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def fp(v: float | None, p: Pat) -> str:
    s = _fp(v, p.symbol)
    if v is not None and abs(v) >= 1000 and s != "—":
        a, _, b = s.partition(".")
        s = f"{int(a):,}" + ("." + b if b else "")
    return s


def bar_idx(B: Bars, ts: int | None) -> int:
    if ts is None:
        return len(B) - 1
    j = int(np.searchsorted(B.ts, ts, side="left"))
    return min(max(j, 0), len(B) - 1)


def _fmt_time(ts: float, tz: str) -> str:
    t = dt.datetime.fromtimestamp(ts, ZoneInfo(tz))
    off = (t.utcoffset().total_seconds() / 3600) if t.utcoffset() else 0
    return f"{t.day:02d} {_MONTHS[t.month - 1]} {t.year}  ·  {t:%H:%M}  (UTC{'+' if off >= 0 else '-'}{abs(int(off))})"


def _spread(items: list[tuple[float, str, str]], gap: float):
    """Fiyat etiketleri üst üste binmesin."""
    order = sorted(range(len(items)), key=lambda i: items[i][0])
    pos = [items[i][0] for i in order]
    for j in range(1, len(pos)):
        if pos[j] - pos[j - 1] < gap:
            pos[j] = pos[j - 1] + gap
    res = [None] * len(items)
    for j, i in enumerate(order):
        res[i] = (items[i][0], pos[j], items[i][1], items[i][2])
    return res


def _chip(fig, x, y, text, fs, fc, tc, r, ec="none"):
    t = fig.text(x, y, text, fontsize=fs, fontweight="bold", color=tc, va="center",
                 bbox=dict(boxstyle="round,pad=0.38", fc=fc, ec=ec))
    bb = t.get_window_extent(r)
    return bb.x1 / fig.bbox.width + 0.022


def _schematic(fig, rect, p: Pat, acc: str, kind: str):
    """Sağ panel: gerçek oranlarla sadeleştirilmiş X-A-B-C-D şekli."""
    ax = fig.add_axes(rect, facecolor="none")
    ax.set_zorder(5)          # panel arka planının (zorder=1) üstünde kalsın
    ax.axis("off")
    bull = p.dir > 0
    xi, ai, bi, ci = 0.0, p.at - p.xt, p.bt - p.xt, p.ct - p.xt
    span = max(ci - bi, 1)
    pts = [(xi, p.xP, "X"), (ai, p.aP, "A"), (bi, p.bP, "B"), (ci, p.cP, "C"), (ci + span * 0.95, p.ent, "D")]
    # x ekseni: zaman damgalarından (eşit aralıklı değil) → görsel denge için sıralı indekse çevir
    order = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    ys = np.array([q[1] for q in pts])
    ylo, yhi = min(ys.min(), p.zLo, p.zHi), ys.max()
    pad = (yhi - ylo) * 0.16
    ax.set_xlim(-0.35, 4.55)
    ax.set_ylim(ylo - pad, yhi + pad)
    P = [(order[k], ys[k]) for k in range(5)]
    X, A, B, C, D = P
    ax.add_patch(Polygon([X, A, B], closed=True, fc=acc, alpha=0.10, ec="none"))
    ax.add_patch(Polygon([B, C, D], closed=True, fc=acc, alpha=0.10, ec="none"))
    ax.plot([X[0], A[0], B[0], C[0]], [X[1], A[1], B[1], C[1]], color=acc, lw=2.0, solid_capstyle="round")
    ax.plot([C[0], D[0]], [C[1], D[1]], color=acc, lw=2.0, ls=(0, (4, 3)) if kind == "armed" else "-")
    for a_, b_ in ((X, B), (A, C), (B, D), (X, D)):
        ax.plot([a_[0], b_[0]], [a_[1], b_[1]], color=acc, lw=0.9, ls=":", alpha=0.6)
    zc, zh = (p.zLo + p.zHi) / 2, max(abs(p.zHi - p.zLo), (yhi - ylo) * 0.05)
    ax.add_patch(Rectangle((3.3, zc - zh / 2), 1.25, zh, fc=AMBER, alpha=0.30, ec="none"))
    hi_pts = {"A", "C"} if bull else {"X", "B", "D"}
    for (x, y), nm in zip(P, "XABCD"):
        ax.plot([x], [y], "o", ms=4.5, color=acc, zorder=5)
        ax.annotate(nm, (x, y), xytext=(0, 11 if nm in hi_pts else -11), textcoords="offset points", ha="center",
                    va="center", fontsize=10, fontweight="bold", color=TXT, zorder=6)
    for (a_, b_), txt in (((X, B), f"{p.rAB:.3f}"), ((A, C), f"{p.rBC:.3f}"), ((B, D), f"{p.rCD:.3f}"),
                          ((X, D), f"{p.rDref:.3f}")):
        ax.text((a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2, txt, fontsize=7.8, color=MUTED, ha="center", va="center",
                zorder=7, bbox=dict(boxstyle="round,pad=0.2", fc=BG, ec=DIM, lw=0.5, alpha=0.92))


def render_card(B: Bars, p: Pat, kind: str, *, tz: str = "Europe/Istanbul", reason: str = "", tp_j: int = 0,
                prob: float | None = None, samples: int = 0) -> bytes:
    title, sub, scol = STATUS[kind]
    if kind == "target":
        title = f"TP{tp_j or p.thit} VURULDU"
    if kind == "cancel":
        sub = reason_tr(reason or p.cancel_reason)
    bull = p.dir > 0
    acc = GREEN if bull else RED
    n = len(B)
    tf_sec = TF_SECONDS[p.tf]
    reached = p.zone_ts is not None
    dim = 0.55 if kind in ("cancel", "timeout", "be") else 1.0

    with _LOCK:
        fig = Figure(figsize=(12.8, 8.4), dpi=100, facecolor=BG)
        FigureCanvasAgg(fig)
        r = fig.canvas.get_renderer()

        # ── başlık ──
        fig.add_artist(Rectangle((0, 0.985), 1, 0.015, transform=fig.transFigure, color=acc, zorder=1))
        fig.text(0.035, 0.905, p.symbol.upper(), fontsize=40, fontweight="bold", color=TXT, va="baseline")
        y2, x = 0.852, 0.037
        x = _chip(fig, x, y2, TF_TXT.get(p.tf, p.tf.upper()), 14, "#1B2740", TXT, r)
        x = _chip(fig, x, y2, ("▲ BULLISH" if bull else "▼ BEARISH"), 14, acc, "#06130E" if bull else "#FFFFFF", r)
        _chip(fig, x, y2, p.rule.upper(), 14, "#2A2314", AMBER, r)

        bx, bw, bh, by = 0.965, 0.255, 0.062, 0.865
        fig.add_artist(FancyBboxPatch((bx - bw, by), bw, bh, boxstyle="round,pad=0.0,rounding_size=0.012",
                                      transform=fig.transFigure, fc=scol, ec="none", zorder=2))
        fig.text(bx - bw / 2, by + bh / 2, title, fontsize=16, fontweight="bold",
                 color=TXT if scol == MUTED else "#0A0F18", ha="center", va="center", zorder=3)
        fig.text(bx, by - 0.016, sub, fontsize=9.5, color=MUTED, ha="right", va="top")
        meta = f"SKOR {p.score:.0f}"
        if prob is not None:
            meta += f"   ·   GEÇMİŞ BAŞARI %{prob:.0f} (n={samples})"
        fig.text(bx, by + bh + 0.012, meta, fontsize=10.5, color=MUTED, ha="right", va="bottom")

        # ── mum grafiği ──
        ax = fig.add_axes([0.035, 0.245, 0.625, 0.545], facecolor=PANEL)
        xi, ai, bi, ci = (bar_idx(B, t) for t in (p.xt, p.at, p.bt, p.ct))
        start = max(0, min(xi, ai, bi, ci) - 6)
        start = max(start, n - 230)
        ri = bar_idx(B, p.zone_ts) if reached else None
        d_x = ri if reached else (n - 1 + max(3, min(40, ci - bi)))
        xmax = max(d_x, n - 1) + max(8, int((max(d_x, n - 1) - start) * 0.10))
        idx = np.arange(start, n)
        o, h, l, c = B.o[start:], B.h[start:], B.l[start:], B.c[start:]
        cols = np.where(c >= o, UP, DOWN)
        ax.vlines(idx, l, h, colors=cols, linewidth=1.0, zorder=3)
        body = np.maximum(np.abs(c - o), (h.max() - l.min()) * 0.0015)
        ax.bar(idx, body, bottom=np.minimum(o, c), width=0.68, color=cols, zorder=3, linewidth=0)

        pts = [(xi, p.xP, "X"), (ai, p.aP, "A"), (bi, p.bP, "B"), (ci, p.cP, "C"), (d_x, p.ent, "D")]
        ys_all = [l.min(), h.max(), p.zLo, p.zHi, p.stp, p.tg3] + [q[1] for q in pts]
        ymin, ymax = min(ys_all), max(ys_all)
        pad = (ymax - ymin) * 0.07
        ymin, ymax = ymin - pad, ymax + pad
        yr = ymax - ymin
        ax.set_xlim(start - 1, xmax)
        ax.set_ylim(ymin, ymax)

        zcol = AMBER if kind == "armed" else acc
        zh = max(abs(p.zHi - p.zLo), yr * 0.012)
        zc = (p.zHi + p.zLo) / 2
        ax.add_patch(Rectangle((ci, zc - zh / 2), xmax - ci, zh, fc=zcol, alpha=0.13, ec="none", zorder=1))
        ax.text(ci + 1.5, zc + zh / 2 + yr * 0.008, "PRZ", fontsize=9, color=zcol, fontweight="bold",
                va="bottom", ha="left", zorder=6)

        Xp, Ap, Bp, Cp, Dp = ([q[0], q[1]] for q in pts)
        ax.add_patch(Polygon([Xp, Ap, Bp], closed=True, fc=acc, alpha=0.10 * dim, ec="none", zorder=2))
        ax.add_patch(Polygon([Bp, Cp, Dp], closed=True, fc=acc, alpha=0.10 * dim, ec="none", zorder=2))
        ax.plot([Xp[0], Ap[0], Bp[0], Cp[0]], [Xp[1], Ap[1], Bp[1], Cp[1]], color=acc, lw=2.2, alpha=dim, zorder=5,
                solid_capstyle="round")
        ax.plot([Cp[0], Dp[0]], [Cp[1], Dp[1]], color=acc, lw=2.2, alpha=dim, zorder=5, ls="-" if reached else (0, (4, 3)))
        for a_, b_ in ((Xp, Bp), (Ap, Cp), (Bp, Dp), (Xp, Dp)):
            ax.plot([a_[0], b_[0]], [a_[1], b_[1]], color=acc, lw=1.0, ls=":", alpha=0.55 * dim, zorder=4)
        hi_pts = {"A", "C"} if bull else {"X", "B", "D"}
        for xx, yy, nm in pts:
            ax.annotate(nm, (xx, yy), xytext=(0, 15 if nm in hi_pts else -15), textcoords="offset points", ha="center",
                        va="center", fontsize=11, fontweight="bold", color="white", zorder=9,
                        bbox=dict(boxstyle="round,pad=0.28", fc=(zcol if nm == "D" else acc), ec="none", alpha=0.95 * dim),
                        arrowprops=dict(arrowstyle="-", color=acc, lw=0.8, alpha=0.7 * dim, shrinkA=0, shrinkB=2))
        for (a_, b_), txt in (((Xp, Bp), f"AB/XA {p.rAB:.3f}"), ((Ap, Cp), f"BC/AB {p.rBC:.3f}"),
                              ((Bp, Dp), f"CD/BC {p.rCD:.3f}")):
            ax.text((a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2, txt, fontsize=8, color=MUTED, ha="center", va="center",
                    zorder=8, bbox=dict(boxstyle="round,pad=0.22", fc=BG, ec=DIM, lw=0.6, alpha=0.9))

        x0 = ri if reached else n - 1
        levels = [(p.ent, "GİRİŞ", BLUE), (p.stp, "STOP", ORANGE), (p.tg1, "TP1", "#5BD18B"),
                  (p.tg2, "TP2", "#43C076"), (p.tg3, "TP3", "#2EBD85")]
        for val, name, col in levels:
            ax.plot([x0, xmax], [val, val], color=col, lw=1.4, ls="--" if name in ("GİRİŞ", "STOP") else ":",
                    alpha=0.9 if dim == 1 else 0.5, zorder=4)
        for real, yy, txt, col in _spread([(v, f"{nm}  {fp(v, p)}", col) for v, nm, col in levels], yr * 0.052):
            ax.text(xmax - 0.4, yy, txt, fontsize=9, fontweight="bold", color="#0A0F18", ha="right", va="center", zorder=10,
                    bbox=dict(boxstyle="round,pad=0.25", fc=col, ec="none"))
        ax.plot([n - 1], [B.c[-1]], marker="o", ms=5, color="white", zorder=9)
        if kind == "cancel":
            ax.text(0.5, 0.5, "İPTAL", transform=ax.transAxes, fontsize=84, fontweight="bold", color=RED, alpha=0.12,
                    rotation=18, ha="center", va="center", zorder=7)

        ax.yaxis.tick_right()
        ax.tick_params(axis="y", colors=MUTED, labelsize=9, length=0)
        ax.tick_params(axis="x", colors=MUTED, labelsize=9, length=0)
        ax.grid(axis="y", color=GRID, lw=0.8)
        for s in ax.spines.values():
            s.set_visible(False)
        ticks = np.linspace(start, n - 1, 5).round().astype(int)
        fm = "%d %b" if tf_sec >= 86400 else "%d.%m %H:%M"
        z = ZoneInfo(tz)
        ax.set_xticks(ticks)
        ax.set_xticklabels([dt.datetime.fromtimestamp(int(B.ts[t]), z).strftime(fm) for t in ticks])
        ax.yaxis.set_major_formatter(lambda v, _: _fp(v, p.symbol))

        # ── sağ panel: harmonik şekil ──
        fig.add_artist(FancyBboxPatch((0.685, 0.245), 0.28, 0.545, boxstyle="round,pad=0.0,rounding_size=0.01",
                                      transform=fig.transFigure, fc=PANEL, ec=GRID, lw=1, zorder=1))
        fig.text(0.700, 0.768, "HARMONİK ŞEKİL", fontsize=9.5, fontweight="bold", color=MUTED, va="center")
        _schematic(fig, [0.695, 0.500, 0.262, 0.245], p, acc, kind)
        sc = max(0.0, min(1.0, p.score / 100))
        fig.text(0.700, 0.462, "SKOR", fontsize=9.5, fontweight="bold", color=MUTED, va="center")
        fig.text(0.950, 0.462, f"{p.score:.0f} / 100", fontsize=12, fontweight="bold", color=TXT, va="center", ha="right")
        fig.add_artist(Rectangle((0.700, 0.432), 0.250, 0.011, transform=fig.transFigure, color="#18233A", zorder=2))
        fig.add_artist(Rectangle((0.700, 0.432), 0.250 * sc, 0.011, transform=fig.transFigure, color=AMBER, zorder=3))
        lines = []
        lines.append((f"Geçmiş başarı  %{prob:.0f}  (n={samples})" if prob is not None else "Geçmiş başarı: yeterli örnek yok", MUTED))
        lines.append((f"Ölçek {p.scale + 1}" + ("  ·  çoklu ölçek ✔" if p.ms else ""), MUTED))
        if p.htf_ok:
            lines.append(("Üst periyot trend uyumu ✔", GREEN))
        if p.div_ok:
            lines.append(("RSI uyumsuzluğu ✔", GREEN))
        if p.vol_ok:
            lines.append(("PRZ'de hacim artışı ✔", GREEN))
        for k, (txt, col) in enumerate(lines[:6]):
            fig.text(0.700, 0.395 - k * 0.032, txt, fontsize=9.5, color=col, va="center")

        # ── alt kutular ──
        ent = p.fill if p.fill is not None else p.ent
        risk = abs(ent - p.stp)
        rr = abs(p.tg2 - ent) / risk if risk > 0 else float("nan")

        def pct(v):
            return f"{(v - ent) / ent * 100:+.2f}%"

        tiles = [
            ("GİRİŞ (D)", fp(p.ent, p), BLUE, f"PRZ {fp(p.zLo, p)} – {fp(p.zHi, p)}"),
            ("STOP", fp(p.stp, p), ORANGE, pct(p.stp)),
            ("TP1", fp(p.tg1, p), "#5BD18B", ("✔ " if p.thit >= 1 else "") + pct(p.tg1)),
            ("TP2", fp(p.tg2, p), "#43C076", ("✔ " if p.thit >= 2 else "") + pct(p.tg2)),
            ("TP3", fp(p.tg3, p), "#2EBD85", ("✔ " if p.thit >= 3 else "") + pct(p.tg3)),
            ("R:R (TP2)", "-" if rr != rr else f"1 : {rr:.2f}", TXT, f"risk {abs(risk / ent * 100):.2f}%"),
        ]
        gap, left, total = 0.011, 0.035, 0.93
        w = (total - gap * (len(tiles) - 1)) / len(tiles)
        for i, (lab, val, col, sub_) in enumerate(tiles):
            xx = left + i * (w + gap)
            fig.add_artist(FancyBboxPatch((xx, 0.092), w, 0.118, boxstyle="round,pad=0.0,rounding_size=0.01",
                                          transform=fig.transFigure, fc=PANEL, ec=GRID, lw=1, zorder=2))
            fig.add_artist(Rectangle((xx, 0.092), 0.0035, 0.118, transform=fig.transFigure, color=col, zorder=3))
            fig.text(xx + 0.013, 0.192, lab, fontsize=9.5, color=MUTED, va="center", fontweight="bold")
            fig.text(xx + 0.013, 0.150, val, fontsize=15.5, color=col, va="center", fontweight="bold")
            fig.text(xx + 0.013, 0.108, sub_, fontsize=8.6, color=MUTED, va="center")

        fig.text(0.035, 0.045, "HaP Harmonik Bot   ·   kapanış bazlı sinyal", fontsize=10, color=MUTED, va="center")
        fig.text(0.965, 0.045, "mum kapanışı · " + _fmt_time(float(B.ts[-1] + tf_sec), tz)
                 + "     ·     Yatırım tavsiyesi değildir", fontsize=9.5, color=DIM, ha="right", va="center")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=BG)
        return buf.getvalue()
