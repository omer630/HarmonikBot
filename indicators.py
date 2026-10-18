from __future__ import annotations

import numpy as np
import pandas as pd


def ema(x, n: int) -> np.ndarray:
    return pd.Series(x, dtype="float64").ewm(span=n, adjust=False).mean().to_numpy()


def rma(x, n: int) -> np.ndarray:
    return pd.Series(x, dtype="float64").ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def atr(h, l, c, n: int = 14) -> np.ndarray:
    pc = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return rma(tr, n)


def rsi(c, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    ru, rd = rma(up, n), rma(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(rd == 0, np.inf, ru / np.where(rd == 0, 1.0, rd))
    return 100.0 - 100.0 / (1.0 + rs)
