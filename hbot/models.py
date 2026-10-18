"""Ortak veri yapıları."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

import numpy as np


@dataclass
class Bars:
    """Sadece KAPANMIŞ mumlar. ts = mum açılış zamanı (epoch saniye)."""
    ts: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    source: str = ""
    tv: str = ""          # TradingView sembolü (ör. BINANCE:BTCUSDT)

    def __len__(self) -> int:
        return len(self.ts)

    def tail(self, n: int) -> "Bars":
        return Bars(self.ts[-n:], self.o[-n:], self.h[-n:], self.l[-n:], self.c[-n:], self.v[-n:], self.source, self.tv)

    def head_until(self, i: int) -> "Bars":
        """0..i (dahil) mumlarını döndürür."""
        j = i + 1
        return Bars(self.ts[:j], self.o[:j], self.h[:j], self.l[:j], self.c[:j], self.v[:j], self.source, self.tv)


@dataclass
class Pat:
    id: str = ""
    symbol: str = ""
    tf: str = ""
    src: str = "bt"                 # bt = geçmiş tarama, live = canlı
    tp: int = 0
    rule: str = ""
    dir: int = 1                    # 1 bullish, -1 bearish
    scale: int = 0
    xt: int = 0
    at: int = 0
    bt: int = 0
    ct: int = 0
    xP: float = 0.0
    aP: float = 0.0
    bP: float = 0.0
    cP: float = 0.0
    ent: float = 0.0
    stp: float = 0.0
    zLo: float = 0.0
    zHi: float = 0.0
    tg1: float = 0.0
    tg2: float = 0.0
    tg3: float = 0.0
    rAB: float = 0.0
    rBC: float = 0.0
    rXC: float = 0.0
    rCD: float = 0.0
    rDref: float = 0.0              # D'nin referans bacağa oranı (giriş seviyesinde)
    dref: str = "XA"
    rB: float = 50.0
    score: float = 0.0
    prob: float = 50.0              # tespit anındaki ampirik olasılık (%)
    prob_n: int = 0
    # yaşam döngüsü
    state: int = 0                  # 0 bekliyor · 1 pozisyonda · 3 bitti · 4 stop · 5 iptal
    live: bool = False
    touched: bool = False
    live_ts: int | None = None
    zone_ts: int | None = None
    fill_ts: int | None = None
    fill: float | None = None
    end_ts: int | None = None
    thit: int = 0
    minlo: float | None = None
    result: str = ""                # win | loss | (boş = sürüyor)
    cancel_reason: str = ""
    ms: bool = False
    div_ok: bool = False
    vol_ok: bool = False
    htf_ok: bool = False
    # bildirim durumu
    ann_armed: bool = False
    ann_zone: bool = False
    msg_last: int | None = None
    msg_armed: int | None = None
    created_ts: int = 0
    # geçici indeksler (saklanmaz)
    xi: int = field(default=-1, repr=False)
    ai: int = field(default=-1, repr=False)
    bi: int = field(default=-1, repr=False)
    ci: int = field(default=-1, repr=False)
    di: int = field(default=-1, repr=False)

    _TRANSIENT = ("xi", "ai", "bi", "ci", "di")

    def to_dict(self) -> dict[str, Any]:
        d = {}
        for f in fields(self):
            if f.name in self._TRANSIENT:
                continue
            d[f.name] = getattr(self, f.name)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Pat":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    @property
    def status(self) -> str:
        return {0: "pending", 1: "active", 3: "done", 4: "stopped", 5: "cancelled"}.get(self.state, "pending")

    @property
    def zone_top(self) -> float:
        return max(self.zLo, self.zHi)

    @property
    def zone_bottom(self) -> float:
        return min(self.zLo, self.zHi)


@dataclass
class Ev:
    type: str            # armed | zone | entry | target | stop | be | timeout | complete | cancel
    pat: Pat
    i: int               # mum indeksi
    ts: int
    detail: dict = field(default_factory=dict)


@dataclass
class Alert:
    kind: str            # armed | zone | cancel | entry | result
    pat: Pat
    bars: Bars | None
    ts: int
    detail: dict = field(default_factory=dict)
