"""Ortam ayarları, sabitler ve varsayılan kullanıcı ayarları."""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from pathlib import Path

# ───────────────────────── zaman dilimleri ─────────────────────────
TF_SECONDS = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
SELECTABLE_TFS = ["15m", "30m", "1h", "4h", "1d"]
TF_LABEL = {"15m": "15M", "30m": "30M", "1h": "1H", "4h": "4H", "1d": "1D", "1w": "1W"}
TV_INTERVAL = {"15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D", "1w": "W"}
# Üst periyot (Pine'daki otomatik seçimle aynı): ≤15m→4h, ≤1h→1d, ≤1d→1w
HTF_OF = {"15m": "4h", "30m": "1d", "1h": "1d", "4h": "1w", "1d": "1w"}

PATTERN_NAMES = ["Gartley", "Bat", "Alt Bat", "Butterfly", "Crab", "Deep Crab", "Shark", "Cypher", "Özel"]

# ───────────────────────── varsayılan formasyon kuralları ─────────────────────────
# ab: AB/XA, xc: XC/XA, bc: BC/AB, cd: CD/BC, d: D oranı aralığı (PRZ), ref: D hangi bacağa göre
# ent: giriş oranı (PRZ içinde), stp: stop oranı (XA'dan, 0 = X noktası)
DEFAULT_RULES: dict[str, dict] = {
    "Gartley":   {"ab": [0.608, 0.67], "xc": [0.0, 99.0], "bc": [0.382, 0.886], "cd": [1.13, 1.618], "d": [0.76, 0.81],
                  "ref": "XA", "ent": 0.786, "stp": 0.0},
    "Bat":       {"ab": [0.382, 0.57], "xc": [0.0, 99.0], "bc": [0.382, 0.886], "cd": [1.618, 2.618], "d": [0.87, 0.90],
                  "ref": "XA", "ent": 0.886, "stp": 0.0},
    "Alt Bat":   {"ab": [0.33, 0.41], "xc": [0.0, 99.0], "bc": [0.382, 0.886], "cd": [2.0, 3.618], "d": [1.10, 1.16],
                  "ref": "XA", "ent": 1.13, "stp": 1.27},
    "Butterfly": {"ab": [0.74, 0.886], "xc": [0.0, 99.0], "bc": [0.382, 0.886], "cd": [1.618, 2.24], "d": [1.25, 1.618],
                  "ref": "XA", "ent": 1.27, "stp": 1.414},
    "Crab":      {"ab": [0.382, 0.618], "xc": [0.0, 99.0], "bc": [0.382, 0.886], "cd": [2.24, 3.618], "d": [1.60, 1.64],
                  "ref": "XA", "ent": 1.618, "stp": 2.0},
    "Deep Crab": {"ab": [0.856, 0.999], "xc": [0.0, 99.0], "bc": [0.382, 0.886], "cd": [2.24, 3.618], "d": [1.60, 1.64],
                  "ref": "XA", "ent": 1.618, "stp": 2.0},
    "Shark":     {"ab": [0.382, 0.618], "xc": [0.0, 99.0], "bc": [1.13, 1.618], "cd": [1.618, 2.24], "d": [0.886, 1.13],
                  "ref": "XA", "ent": 0.886, "stp": 1.27},
    "Cypher":    {"ab": [0.382, 0.618], "xc": [1.13, 1.414], "bc": [1.13, 2.618], "cd": [0.382, 2.618], "d": [0.76, 0.81],
                  "ref": "XC", "ent": 0.786, "stp": 0.0},
    "Özel":      {"ab": [0.5, 0.786], "xc": [0.0, 99.0], "bc": [0.382, 0.886], "cd": [1.13, 2.618], "d": [0.70, 1.00],
                  "ref": "XA", "ent": 0.786, "stp": 0.0},
}

# ───────────────────────── varsayılan kullanıcı ayarları ─────────────────────────
DEFAULT_CRYPTO = ["BTC", "ETH", "ZEC", "SOL", "XRP", "HYPE", "BNB", "NEAR", "ADA", "SUI", "UNI", "DOGE", "ENA",
                  "PUMP", "WLD", "TAO", "AVAX", "LTC", "ARB", "DOT", "HBAR", "INJ", "ONDO", "FIL"]
DEFAULT_FX = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDJPY", "USDCHF", "XAUUSD", "XAGUSD"]

DEFAULT_SETTINGS: dict = {
    "symbols": [s + "USDT" for s in DEFAULT_CRYPTO] + DEFAULT_FX,
    "symbols_off": [],                       # geçici kapatılan pariteler
    "timeframes": ["15m", "1h", "4h", "1d"],
    "patterns": {n: (n != "Özel") for n in PATTERN_NAMES},
    "direction": "both",                     # bull | bear | both
    "min_score": 55,
    "notify": {"armed": True, "zone": True, "cancel": True, "result": True},
    "card": True,                            # mesajlara görsel kart ekle
    "paused": False,
    # ── motor ──
    "entry_mode": "limit",                   # limit | reversal
    "pivot_len": 3, "scales": 2, "piv_atr": 0.4, "shift": 1, "max_age": 40,
    "min_xa": 4.5, "min_bc": 1.5, "need_b": True, "best_only": True, "tol": 0.005,
    "wait": 80, "hold": 150,
    "t1": 0.382, "t2": 0.618, "t3": 1.0, "succ_target": 1, "be_after_t1": True, "stop_buf_atr": 0.0,
    # ── iptal kuralları ──
    "cancel_c": True, "cancel_timeout": True, "cancel_escape": True, "escape_atr": 3.0, "near_atr": 1.0,
    # ── teyitler / skor ──
    "c_vol": True, "vol_z": 1.0, "c_div": True, "div_min": 1.5,
    "c_htf": True, "c_ema": True, "with_trend": True, "c_loc": True, "ms_bonus": 8,
    "use_prob": True, "min_samp": 8,
    # ── işlem planı hesabı (sadece bilgi) ──
    "account": 100000.0, "risk_pct": 1.0,
}

# ───────────────────────── enstrüman sınıflandırma ─────────────────────────
FX_CODES = {"EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY", "XAU", "XAG", "TRY", "SEK", "NOK", "DKK",
            "PLN", "MXN", "ZAR", "SGD", "HKD", "CNH", "HUF", "CZK"}


@dataclass(frozen=True)
class Instrument:
    symbol: str   # BTCUSDT, EURUSD, XAUUSD
    kind: str     # crypto | fx

    @property
    def is_fx(self) -> bool:
        return self.kind == "fx"


def normalize_symbol(raw: str) -> str:
    s = raw.strip().upper().replace("İ", "I").replace("Ş", "S").replace("Ğ", "G")
    s = re.sub(r"[^A-Z0-9]", "", s.replace(".P", ""))
    return s


def classify(raw: str) -> Instrument | None:
    s = normalize_symbol(raw)
    if not s:
        return None
    if len(s) == 6 and s[:3] in FX_CODES and s[3:] in FX_CODES:
        return Instrument(s, "fx")
    if s.endswith("USDT"):
        base = s[:-4]
    elif s.endswith("USD") and len(s) > 5:   # BTCUSD → BTCUSDT
        base = s[:-3]
    else:
        base = s
    if not base or len(base) > 15:
        return None
    return Instrument(base + "USDT", "crypto")


# ───────────────────────── ortam ─────────────────────────
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


@dataclass
class Env:
    token: str
    chat_id: str
    allowed: set[int]
    crypto_sources: list[str]
    fx_sources: list[str]
    twelve_key: str
    twelve_rpm: int
    tz: str
    data_dir: Path
    log_level: str


def load_env(dotenv: str | Path | None = None) -> Env:
    _load_dotenv(Path(dotenv) if dotenv else Path(".env"))
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    allowed_raw = os.environ.get("ALLOWED_USER_IDS", "").strip()
    allowed: set[int] = set()
    for part in re.split(r"[,\s]+", allowed_raw or chat):
        if re.fullmatch(r"-?\d+", part or ""):
            allowed.add(int(part))
    split = lambda k, d: [x.strip() for x in os.environ.get(k, d).split(",") if x.strip()]
    data_dir = Path(os.environ.get("DATA_DIR", "./data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Env(
        token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        chat_id=chat,
        allowed=allowed,
        crypto_sources=split("CRYPTO_SOURCES", "binance_spot,bybit_linear,bybit_spot,gate_spot,binance_futures"),
        fx_sources=split("FX_SOURCES", "yahoo,twelvedata"),
        twelve_key=os.environ.get("TWELVEDATA_API_KEY", "").strip(),
        twelve_rpm=int(os.environ.get("TWELVEDATA_RPM", "7") or 7),
        tz=os.environ.get("TZ", "Europe/Istanbul"),
        data_dir=data_dir,
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )


def merged_settings(stored: dict | None) -> dict:
    """Kayıtlı ayarları varsayılanlarla birleştirir (yeni anahtarlar otomatik gelir)."""
    out = copy.deepcopy(DEFAULT_SETTINGS)
    for k, v in (stored or {}).items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k].update(v)
        else:
            out[k] = v
    return out
