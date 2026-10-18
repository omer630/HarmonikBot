"""Harmonik motoru — "HaP Harmonik PRO" Pine indikatörünün Python karşılığı.

Mantık (Pine ile aynı):
  • 3 ölçekli ZigZag pivot iskeleti (ATR gürültü filtresi, pencere kaydırma)
  • XABC oluşunca D noktası PİVOT BEKLENMEDEN projekte edilir → PRZ aralığı
  • PRZ = (D oranı aralığı) ∩ (CD/BC aralığı); giriş/stop/hedefler hesaplanır
  • Kalite skoru (oran isabeti, PRZ darlığı, trend, hacim, konum, ampirik olasılık)
  • Yaşam döngüsü: B bekleniyor → İHTİMAL (live) → PRZ'ye ulaştı (zone) → giriş → T1/T2/T3 / stop
  • İptal: C aşıldı · süre doldu · PRZ'ye hiç yaklaşmadan ters yöne kaçış · stop önce kırıldı
Tüm hesap KAPANMIŞ mumlarla yapılır (repaint yok).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .config import DEFAULT_RULES, PATTERN_NAMES, TF_SECONDS
from .models import Bars, Ev, Pat

NAN = float("nan")


# ═════════════════════════════ ayarlar ═════════════════════════════
@dataclass
class Rule:
    name: str
    on: bool
    ab: tuple[float, float]
    xc: tuple[float, float]
    bc: tuple[float, float]
    cd: tuple[float, float]
    d: tuple[float, float]
    ref: str
    ent: float
    stp: float


def build_rules(user_rules: dict | None, enabled: dict[str, bool]) -> list[Rule]:
    out: list[Rule] = []
    for name in PATTERN_NAMES:
        base = dict(DEFAULT_RULES[name])
        if user_rules and name in user_rules:
            base.update({k: v for k, v in user_rules[name].items() if k in base})
        out.append(Rule(
            name=name, on=bool(enabled.get(name, False)),
            ab=tuple(base["ab"]), xc=tuple(base["xc"]), bc=tuple(base["bc"]), cd=tuple(base["cd"]), d=tuple(base["d"]),
            ref=str(base["ref"]).upper(), ent=float(base["ent"]), stp=float(base["stp"])))
    return out


@dataclass
class EngineSettings:
    pivot_len: int = 3
    scales: int = 2
    piv_atr: float = 0.4
    shift: int = 1
    max_age: int = 40
    min_xa: float = 4.5
    min_bc: float = 1.5
    need_b: bool = True
    best_only: bool = True
    tol: float = 0.005
    wait: int = 80
    hold: int = 150
    min_score: int = 55
    entry_mode: str = "limit"
    t1: float = 0.382
    t2: float = 0.618
    t3: float = 1.0
    succ_target: int = 1
    be_after_t1: bool = True
    stop_buf_atr: float = 0.0
    cancel_c: bool = True
    cancel_timeout: bool = True
    cancel_escape: bool = True
    escape_atr: float = 3.0
    near_atr: float = 1.0
    c_vol: bool = True
    vol_z: float = 1.0
    c_div: bool = True
    div_min: float = 1.5
    c_htf: bool = True
    c_ema: bool = True
    with_trend: bool = True
    c_loc: bool = True
    ms_bonus: int = 8
    use_prob: bool = True
    min_samp: int = 8
    direction: str = "both"

    @classmethod
    def from_dict(cls, d: dict) -> "EngineSettings":
        names = cls.__dataclass_fields__.keys()
        return cls(**{k: d[k] for k in names if k in d})


# ═════════════════════════════ göstergeler ═════════════════════════════
def _rma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = np.nanmean(x[:n])
    a = 1.0 / n
    for i in range(n, len(x)):
        out[i] = out[i - 1] + a * (x[i] - out[i - 1])
    return out


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.empty(len(x))
    if len(x) == 0:
        return out
    a = 2.0 / (n + 1)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = out[i - 1] + a * (x[i] - out[i - 1])
    return out


def _sma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def _rolling_std(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = np.lib.stride_tricks.sliding_window_view(x, n)
        out[n - 1:] = w.std(axis=1)
    return out


def _rolling_ext(x: np.ndarray, n: int, fn) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = np.lib.stride_tricks.sliding_window_view(x, n)
        out[n - 1:] = fn(w, axis=1)
    return out


@dataclass
class Ind:
    atr: np.ndarray
    rsi: np.ndarray
    unit: np.ndarray
    vdry: np.ndarray
    volz: np.ndarray
    trup: np.ndarray
    trdn: np.ndarray
    loc: np.ndarray
    htfup: np.ndarray
    htfdn: np.ndarray


def compute_indicators(B: Bars, htf: Bars | None, htf_tf: str | None) -> Ind:
    n = len(B)
    h, l, c, v = B.h, B.l, B.c, B.v
    prev_c = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])
    tr[0] = h[0] - l[0]
    atr = _rma(tr, 14)
    # RSI
    d = np.diff(c, prepend=c[0])
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    ag, al = _rma(gain, 14), _rma(loss, 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ag / al
        rsi = np.where(al == 0, 100.0, 100.0 - 100.0 / (1.0 + rs))
    rsi = np.where(np.isnan(ag), np.nan, rsi)
    # ortalama mum boyu: son 50 mumun medyanı (nearest-rank, 25. sıradaki)
    rng = h - l
    unit = np.full(n, np.nan)
    if n >= 50:
        w = np.lib.stride_tricks.sliding_window_view(rng, 50)
        unit[49:] = np.sort(w, axis=1)[:, 24]
    vs, vl = _sma(v, 10), _sma(v, 30)
    with np.errstate(invalid="ignore"):
        vdry = np.where(np.isnan(vs) | np.isnan(vl), False, vs < vl)
    vm, vsd = _sma(v, 50), _rolling_std(v, 50)
    with np.errstate(divide="ignore", invalid="ignore"):
        volz = np.where((vsd > 0) & ~np.isnan(vsd), (v - vm) / vsd, 0.0)
    emaf, emas = _ema(c, 50), _ema(c, 200)
    hi100 = _rolling_ext(h, 100, np.max)
    lo100 = _rolling_ext(l, 100, np.min)
    with np.errstate(divide="ignore", invalid="ignore"):
        loc = np.where((hi100 - lo100) > 0, (c - lo100) / (hi100 - lo100), 0.5)
    loc = np.where(np.isnan(loc), 0.5, loc)
    # üst periyot trendi: base mumun açılışından ÖNCE kapanmış son HTF mumunun EMA21 / EMA55 değeri
    htfup = np.zeros(n, dtype=bool)
    htfdn = np.zeros(n, dtype=bool)
    if htf is not None and htf_tf and len(htf) >= 60:
        e21, e55 = _ema(htf.c, 21), _ema(htf.c, 55)
        ends = htf.ts + TF_SECONDS[htf_tf]
        j = np.searchsorted(ends, B.ts, side="right") - 1
        ok = j >= 55
        jj = np.clip(j, 0, len(htf) - 1)
        htfup = ok & (e21[jj] > e55[jj])
        htfdn = ok & (e21[jj] < e55[jj])
    return Ind(atr=atr, rsi=rsi, unit=unit, vdry=vdry, volz=volz, trup=emaf > emas, trdn=emaf < emas, loc=loc,
               htfup=htfup, htfdn=htfdn)


def _pivot_arrays(h: np.ndarray, l: np.ndarray, L: int) -> tuple[np.ndarray, np.ndarray]:
    """Pivot, onay anında (i = pivot + L) fiyatıyla işaretlenir. Sol taraf kesin, sağ taraf ≥."""
    n = len(h)
    ph = np.full(n, np.nan)
    pl = np.full(n, np.nan)
    if n < 2 * L + 1:
        return ph, pl
    wh = np.lib.stride_tricks.sliding_window_view(h, 2 * L + 1)
    wl = np.lib.stride_tricks.sliding_window_view(l, 2 * L + 1)
    ch, cl = wh[:, L], wl[:, L]
    mh = (ch > wh[:, :L].max(axis=1)) & (ch >= wh[:, L + 1:].max(axis=1))
    ml = (cl < wl[:, :L].min(axis=1)) & (cl <= wl[:, L + 1:].min(axis=1))
    k = np.arange(len(ch)) + 2 * L          # onay indeksi
    ph[k[mh]] = ch[mh]
    pl[k[ml]] = cl[ml]
    return ph, pl


@dataclass
class Sw:
    x: int
    y: float
    hi: bool
    r: float


def _nearest_rank_idx(ts: np.ndarray, t: int) -> int:
    if len(ts) == 0 or t < ts[0]:
        return -1
    j = int(np.searchsorted(ts, t, side="left"))
    return min(j, len(ts) - 1)


# ═════════════════════════════ motor ═════════════════════════════
@dataclass
class RunResult:
    pats: list[Pat]
    events: list[Ev]
    new_ids: list[str] = field(default_factory=list)


class Engine:
    def __init__(self, S: EngineSettings, rules: list[Rule]):
        self.S = S
        self.rules = rules
        self.lim = S.entry_mode == "limit"

    # ───────────── skor ─────────────
    @staticmethod
    def _acc(v: float, lo: float, hi: float) -> float:
        ctr = (lo + hi) / 2.0
        half = max((hi - lo) / 2.0, 0.03)
        return max(0.0, 1.0 - abs(v - ctr) / half)

    def _score(self, i: int, acc: float, width: float, xa_atr: float, sg: int, sc: int, tp: int) -> float:
        S, ind = self.S, self.ind
        atr = ind.atr[i]
        s = 38.0 + acc * 22.0
        s += (1.0 - min(1.0, width / max(3.0 * atr, 1e-12))) * 8.0
        s += min(xa_atr / 12.0, 1.0) * 6.0
        s += sc * 3.0
        if S.c_vol and ind.vdry[i]:
            s += 4.0
        if S.c_htf:
            up, dn = bool(ind.htfup[i]), bool(ind.htfdn[i])
            al = ((sg > 0 and up) or (sg < 0 and dn)) if S.with_trend else ((sg > 0 and dn) or (sg < 0 and up))
            s += 7.0 if al else -4.0
        if S.c_ema:
            up, dn = bool(ind.trup[i]), bool(ind.trdn[i])
            al = ((sg > 0 and up) or (sg < 0 and dn)) if S.with_trend else ((sg > 0 and dn) or (sg < 0 and up))
            s += 5.0 if al else -3.0
        if S.c_loc:
            edge = (1.0 - ind.loc[i]) if sg > 0 else ind.loc[i]
            s += (edge - 0.5) * 10.0
        if S.use_prob:
            w, l = self.stats.get(tp, (0, 0))
            if w + l >= S.min_samp:
                s += (self._prob(tp)[0] - 50.0) * 0.12
        return max(5.0, min(99.0, s))

    def _prob(self, tp: int) -> tuple[float, int]:
        w, l = self.stats.get(tp, (0, 0))
        return 100.0 * (w + 1.0) / (w + l + 2.0), w + l

    # ───────────── ZigZag ─────────────
    def _sw_add(self, sw: list[Sw], price: float, is_hi: bool, pivot_idx: int, rsi_v: float, i: int) -> None:
        if np.isnan(price):
            return
        handled = False
        if sw:
            last = sw[-1]
            if last.hi == is_hi:
                if (is_hi and price > last.y) or ((not is_hi) and price < last.y):
                    sw[-1] = Sw(pivot_idx, price, is_hi, rsi_v)
                handled = True
            else:
                atr = self.ind.atr[i]
                thr = (atr if not np.isnan(atr) else 0.0) * self.S.piv_atr
                if abs(price - last.y) < thr:
                    handled = True
        if not handled:
            sw.append(Sw(pivot_idx, price, is_hi, rsi_v))
        if len(sw) > 16:
            del sw[0]

    # ───────────── yaşam döngüsü ─────────────
    def _cancel(self, p: Pat, i: int, reason: str) -> None:
        p.state = 5
        p.end_ts = int(self.B.ts[i])
        p.cancel_reason = reason
        self.events.append(Ev("cancel", p, i, p.end_ts, {"reason": reason}))

    def _finish(self, p: Pat, i: int, state: int, kind: str) -> None:
        p.state = state
        p.end_ts = int(self.B.ts[i])
        p.result = "win" if p.thit >= self.S.succ_target else "loss"
        self.events.append(Ev(kind, p, i, p.end_ts, {"thit": p.thit}))

    def _step(self, p: Pat, i: int) -> None:
        S, B, ind = self.S, self.B, self.ind
        sg = p.dir
        if sg > 0:
            lo, hi = B.l[i], B.h[i]
        else:
            lo, hi = -B.h[i], -B.l[i]
        cl, op = sg * B.c[i], sg * B.o[i]
        ts = int(B.ts[i])
        eU, sU, cU, bU = sg * p.ent, sg * p.stp, sg * p.cP, sg * p.bP
        zTop = max(sg * p.zLo, sg * p.zHi)
        atr = ind.atr[i]

        if p.state == 0:
            prev_min = p.minlo
            if not p.live and (lo <= bU or lo <= eU):
                p.live = True
                p.live_ts = ts
                self.events.append(Ev("armed", p, i, ts))
            if p.live:
                p.minlo = lo if p.minlo is None else min(p.minlo, lo)
                if p.zone_ts is None and lo <= zTop:
                    p.zone_ts = ts
                    self.events.append(Ev("zone", p, i, ts))
            if lo <= eU:
                p.touched = True
            fin = False
            if p.touched:
                if lo <= sU:
                    if self.lim:
                        p.fill, p.fill_ts, p.di = p.ent, ts, i
                        self.events.append(Ev("entry", p, i, ts, {"price": p.ent}))
                        self._finish(p, i, 4, "stop")
                    else:
                        self._cancel(p, i, "stop_before")
                    fin = True
                elif self.lim or cl > op:
                    p.state = 1
                    p.fill = p.ent if self.lim else float(B.c[i])
                    p.fill_ts, p.di = ts, i
                    if S.c_div:
                        if sg > 0:
                            dv = B.l[i] < p.bP and ind.rsi[i] > p.rB + S.div_min
                        else:
                            dv = B.h[i] > p.bP and ind.rsi[i] < p.rB - S.div_min
                        if dv:
                            p.div_ok = True
                            p.score = min(99.0, p.score + 8.0)
                    if S.c_vol and ind.volz[i] >= S.vol_z:
                        p.vol_ok = True
                        p.score = min(99.0, p.score + 5.0)
                    self.events.append(Ev("entry", p, i, ts, {"price": p.fill}))
                    fin = True
            if not fin:
                if S.cancel_c and hi > cU:
                    self._cancel(p, i, "c_exceeded")
                elif S.cancel_timeout and (i - p.ci) > S.wait:
                    self._cancel(p, i, "timeout")
                elif (S.cancel_escape and p.live and p.zone_ts is None and prev_min is not None
                      and not np.isnan(atr)
                      and hi >= prev_min + S.escape_atr * atr and (prev_min - zTop) > S.near_atr * atr):
                    self._cancel(p, i, "escape")

        elif p.state == 1:
            if i > p.di:
                sl = sg * p.fill if (S.be_after_t1 and p.thit >= 1) else sU
                if lo <= sl:
                    be = S.be_after_t1 and p.thit >= 1
                    self._finish(p, i, 3 if p.thit >= 1 else 4, "be" if be else "stop")
                else:
                    for j in (1, 2, 3):
                        if p.thit < j:
                            tU = sg * (p.tg1 if j == 1 else p.tg2 if j == 2 else p.tg3)
                            if hi >= tU:
                                p.thit = j
                                self.events.append(Ev("target", p, i, ts, {"n": j, "price": sg * tU}))
                            else:
                                break
                    if p.thit >= 3:
                        self._finish(p, i, 3, "complete")
                    elif (i - p.di) > S.hold:
                        self._finish(p, i, 3, "timeout")

    # ───────────── tespit ─────────────
    def _try(self, sw: list[Sw], off: int, sc: int, i: int) -> None:
        S, ind = self.S, self.ind
        n = len(sw)
        if n < off + 4:
            return
        C, Bp, A, X = sw[-1 - off], sw[-2 - off], sw[-3 - off], sw[-4 - off]
        if (i - C.x) > S.max_age:
            return
        if not (C.hi != Bp.hi and Bp.hi != A.hi and A.hi != X.hi):
            return
        sg = 1 if C.hi else -1
        if (sg > 0 and S.direction == "bear") or (sg < 0 and S.direction == "bull"):
            return
        atr, unit = ind.atr[i], ind.unit[i]
        if np.isnan(atr) or np.isnan(unit) or unit <= 0:
            return
        Xu, Au, Bu, Cu = sg * X.y, sg * A.y, sg * Bp.y, sg * C.y
        XA, AB, BC, XC = Au - Xu, Au - Bu, Cu - Bu, Cu - Xu
        if not (XA > 0 and AB > 0 and BC > 0 and XC > 0 and Bu > Xu and XA >= S.min_xa * unit and BC >= S.min_bc * unit):
            return
        rAB, rBC, rXC = AB / XA, BC / AB, XC / XA
        tol = S.tol
        best: Pat | None = None
        for r, R in enumerate(self.rules):
            if not R.on:
                continue
            if not (R.ab[0] - tol <= rAB <= R.ab[1] + tol and R.bc[0] - tol <= rBC <= R.bc[1] + tol
                    and R.xc[0] - tol <= rXC <= R.xc[1] + tol):
                continue
            xcr = R.ref == "XC"
            ref = XC if xcr else XA
            base = Cu if xcr else Au
            z1hi, z1lo = base - R.d[0] * ref, base - R.d[1] * ref
            z2hi, z2lo = Cu - R.cd[0] * BC, Cu - R.cd[1] * BC
            zhi, zlo = min(z1hi, z2hi), max(z1lo, z2lo)
            if zlo > zhi + tol * XA:
                continue
            if zlo > zhi:
                zlo = zhi = (zlo + zhi) / 2.0
            e_raw = base - R.ent * ref
            eU = max(zlo, min(zhi, e_raw))
            sU = (Xu if R.stp == 0.0 else Au - R.stp * XA) - atr * S.stop_buf_atr
            if not (eU > sU and eU < Cu):
                continue
            acc = (self._acc(rAB, *R.ab) + self._acc(rBC, *R.bc)) / 2.0
            sco = self._score(i, acc, zhi - zlo, XA / max(atr, 1e-12), sg, sc, r)
            leg = Au - eU
            pa, pb = sg * zlo, sg * zhi
            prob, pn = self._prob(r)
            q = Pat(tp=r, rule=R.name, dir=sg, scale=sc,
                    xt=int(self.B.ts[X.x]), at=int(self.B.ts[A.x]), bt=int(self.B.ts[Bp.x]), ct=int(self.B.ts[C.x]),
                    xP=X.y, aP=A.y, bP=Bp.y, cP=C.y,
                    ent=sg * eU, stp=sg * sU, zLo=min(pa, pb), zHi=max(pa, pb),
                    tg1=sg * (eU + leg * S.t1), tg2=sg * (eU + leg * S.t2), tg3=sg * (eU + leg * S.t3),
                    rAB=rAB, rBC=rBC, rXC=rXC, rCD=(Cu - eU) / BC, rDref=(base - eU) / ref, dref=R.ref,
                    rB=float(Bp.r) if not np.isnan(Bp.r) else 50.0, score=sco, prob=prob, prob_n=pn,
                    htf_ok=bool(ind.htfup[i] if sg > 0 else ind.htfdn[i]),
                    xi=X.x, ai=A.x, bi=Bp.x, ci=C.x)
            if S.best_only:
                if best is None or q.score > best.score:
                    best = q
            else:
                self._add(q, i)
        if S.best_only and best is not None:
            self._add(best, i)

    def _add(self, q: Pat, i: int) -> None:
        S = self.S
        if q.score < S.min_score:
            return
        tol = S.pivot_len * 4
        for e in self.pats:
            if e.tp == q.tp and e.dir == q.dir and abs(e.xi - q.xi) <= tol and abs(e.ci - q.ci) <= tol:
                if e.scale != q.scale and not e.ms and S.ms_bonus > 0:
                    e.ms = True
                    e.score = min(99.0, e.score + S.ms_bonus)
                return
        ts = int(self.B.ts[i])
        q.id = f"{self.symbol}|{self.tf}|{q.dir}|{q.rule}|{q.xt}|{q.ct}"
        q.symbol, q.tf = self.symbol, self.tf
        q.created_ts = ts
        q.src = "live" if self.mode == "live" else "bt"
        self.pats.append(q)
        self.new_ids.append(q.id)
        if not S.need_b:
            q.live = True
            q.live_ts = ts
            self.events.append(Ev("armed", q, i, ts))
        for k in range(q.ci + 1, i + 1):
            self._step(q, k)
            if q.state >= 3:
                break

    # ───────────── ana giriş ─────────────
    def run(self, B: Bars, htf: Bars | None, htf_tf: str | None, tracked: list[Pat], start_idx: int,
            stats: dict[int, tuple[int, int]], symbol: str, tf: str, mode: str) -> RunResult:
        """Penceredeki tüm mumlardan ZigZag kurar; start_idx'ten itibaren yaşam döngüsü ve tespiti işletir.

        tracked : veritabanından gelen, daha önce bulunmuş formasyonlar (start_idx öncesine kadar işlenmiş)
        stats   : {kural_no: (başarılı, başarısız)} ampirik olasılık için
        mode    : 'warm' (ilk tarama / geçmiş) veya 'live'
        """
        self.B, self.symbol, self.tf, self.mode, self.stats = B, symbol, tf, mode, stats
        self.ind = compute_indicators(B, htf, htf_tf)
        self.pats: list[Pat] = list(tracked)
        self.events: list[Ev] = []
        self.new_ids: list[str] = []
        n = len(B)
        S = self.S
        # tracked formasyonların indekslerini bu penceredeki mumlara bağla
        for p in self.pats:
            p.xi = _nearest_rank_idx(B.ts, p.xt)
            p.ai = _nearest_rank_idx(B.ts, p.at)
            p.bi = _nearest_rank_idx(B.ts, p.bt)
            p.ci = _nearest_rank_idx(B.ts, p.ct)
            p.di = _nearest_rank_idx(B.ts, p.fill_ts) if p.fill_ts else -1
            if p.state <= 1 and (p.ci < 0 or (p.state == 1 and p.di < 0)):
                p.state, p.cancel_reason, p.end_ts = 5, "expired", int(B.ts[-1])
        scales = [S.pivot_len * (k + 1) for k in range(3)][:max(1, min(3, S.scales))]
        piv = [_pivot_arrays(B.h, B.l, L) for L in scales]
        sws: list[list[Sw]] = [[] for _ in piv]
        rsi = self.ind.rsi
        for i in range(n):
            for si, (ph, pl) in enumerate(piv):
                L = scales[si]
                if not np.isnan(ph[i]):
                    self._sw_add(sws[si], float(ph[i]), True, i - L, float(rsi[i - L]), i)
                if not np.isnan(pl[i]):
                    self._sw_add(sws[si], float(pl[i]), False, i - L, float(rsi[i - L]), i)
            if i < start_idx:
                continue
            for p in self.pats:           # önce mevcutlar, sonra yeni tespitler (Pine sırası)
                if p.state <= 1:
                    self._step(p, i)
            for si in range(len(piv)):
                for off in range(S.shift + 1):
                    self._try(sws[si], off, si, i)
        return RunResult(self.pats, self.events, self.new_ids)
