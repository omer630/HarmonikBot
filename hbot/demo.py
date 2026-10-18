"""Sentetik (ama oran olarak gerçek) harmonik veri üretici — test, /test komutu ve önizleme için."""
from __future__ import annotations

import time

import numpy as np

from .config import TF_SECONDS
from .models import Bars

# (XA tabanı 100→130 olacak şekilde) formasyon başına örnek oranlar
SAMPLES = {
    # ad: (AB/XA, BC/AB, D oranı (XA'ya göre))
    "Bat": (0.45, 0.70, 0.886),
    "Gartley": (0.618, 0.62, 0.786),
    "Butterfly": (0.786, 0.62, 1.27),
    "Crab": (0.50, 0.70, 1.618),
}


def synthetic_bars(pattern: str = "Bat", direction: int = 1, stage: str = "armed", tf: str = "4h",
                   seed: int = 7, noise: float = 0.35) -> Bars:
    """stage: armed (B geçildi, PRZ'ye yaklaşıyor) · zone (PRZ'ye değdi) · target (T1+ geçti) · cancel (C aşıldı)."""
    rng = np.random.default_rng(seed)
    ab, bc, dr = SAMPLES[pattern]
    X, A = 100.0, 130.0
    XA = A - X
    B = A - ab * XA
    C = B + bc * (A - B)
    D = A - dr * XA
    knots = [(0, 122.0), (60, 111.0), (118, 112.0), (150, X), (176, A), (196, B), (212, C)]
    if stage == "armed":
        knots += [(226, B - (B - D) * 0.55)]
    elif stage == "zone":
        knots += [(236, D - 0.15), (238, D + 1.0)]
    elif stage == "target":
        leg = A - D
        knots += [(236, D - 0.1), (250, D + 0.5 * leg)]
    elif stage == "cancel":
        knots += [(222, B - 0.6), (234, C + 3.5)]
    xs = np.array([k[0] for k in knots], dtype=float)
    ys = np.array([k[1] for k in knots], dtype=float)
    n = int(xs[-1]) + 1
    path = np.interp(np.arange(n), xs, ys)
    close = path + rng.normal(0, noise, n)
    # kritik noktaları sabitle (pivotlar net olsun)
    for k, y in knots[3:]:
        close[k] = y
    open_ = np.concatenate(([close[0]], close[:-1]))
    up = np.abs(rng.normal(0, noise * 0.9, n))
    dn = np.abs(rng.normal(0, noise * 0.9, n))
    high = np.maximum(open_, close) + up
    low = np.minimum(open_, close) - dn
    # tepe noktaları gerçekten tepe, dip noktaları gerçekten dip olsun
    for k, y in knots[3:]:
        if k in (176, 212) or (stage == "cancel" and k == 234):
            high[k] = y + 0.2
            close[k] = min(close[k], y)
        else:
            low[k] = y - 0.2
            close[k] = max(close[k], y)
    vol = rng.uniform(800, 1500, n)
    if direction < 0:
        K = 260.0
        o2, c2, h2, l2 = K - open_, K - close, K - low, K - high
        open_, close, high, low = o2, c2, h2, l2
    # fiyat ölçeği (BTC benzeri)
    scale = 650.0
    tf_s = TF_SECONDS[tf]
    end = int(time.time() // tf_s) * tf_s - tf_s
    ts = end - (n - 1) * tf_s + np.arange(n) * tf_s
    return Bars(ts.astype(np.int64), open_ * scale, high * scale, low * scale, close * scale, vol,
                source="demo", tv="BINANCE:BTCUSDT")
