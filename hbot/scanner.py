"""7/24 tarayıcı: her (parite, zaman dilimi) için yeni KAPANMIŞ mum gelince motoru çalıştırır,
durum değişince Telegram'a mesaj (görselli) gönderir. Tüm durum SQLite'ta tutulur (yeniden başlatmaya dayanıklı)."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import numpy as np

from . import messages
from .config import HTF_OF, TF_SECONDS, classify
from .data import DataError, fx_market_closed
from .db import DB
from .engine import Engine, EngineSettings, build_rules
from .models import Bars, Pat
from .render import render_card
from .telegram_api import Telegram, TelegramError

log = logging.getLogger("hbot.scan")
LIMIT = 800          # çekilen mum sayısı
WARM_BARS = 400      # ilk taramada geriye dönük işlenen mum (istatistik + olasılık için, SESSİZ)


class Notifier:
    """Görsel kart + HTML başlığı yetkili sohbetlere gönderir. İlk sohbet 'ana' sohbettir: mesaj zinciri (reply) orada kurulur."""

    def __init__(self, tg: Telegram, chats: Callable[[], list[int]], tz: str = "Europe/Istanbul"):
        self.tg, self.chats, self.tz = tg, chats, tz

    def warn(self, text: str) -> None:
        for chat in self.chats():
            try:
                self.tg.send_message(chat, text)
            except Exception as e:  # noqa: BLE001
                log.warning("uyarı gönderilemedi: %s", e)

    def send(self, p: Pat, kind: str, B: Bars, S: dict, *, prob: float | None, n: int, reason: str = "", tp_j: int = 0) -> None:
        text = messages.build(kind, p, tv=B.tv, prob=prob, samples=n, reason=reason, tp_j=tp_j)
        png = None
        if S.get("card", True):
            try:
                png = render_card(B, p, kind, tz=self.tz, reason=reason, tp_j=tp_j, prob=prob, samples=n)
            except Exception:  # noqa: BLE001
                log.exception("kart çizilemedi (%s %s)", p.symbol, p.tf)
        for k, chat in enumerate(self.chats()):
            primary = k == 0
            reply = (p.msg_armed or p.msg_last) if primary else None
            try:
                try:
                    mid = self.tg.send_photo(chat, png, text, reply_to=reply) if png else self.tg.send_message(chat, text, reply_to=reply)
                except TelegramError as e:
                    if not png:
                        raise
                    log.warning("foto gönderilemedi (%s), metin olarak deneniyor", e)
                    mid = self.tg.send_message(chat, text, reply_to=reply)
                if primary:
                    p.msg_last = mid
                    if kind == "armed":
                        p.msg_armed = mid
            except Exception as e:  # noqa: BLE001
                log.error("mesaj gönderilemedi %s → %s: %s", p.symbol, chat, e)


class Scanner:
    def __init__(self, db: DB, hub, notifier: Notifier, workers: int = 4, now_fn: Callable[[], float] = time.time):
        self.db, self.hub, self.notifier, self.now = db, hub, notifier, now_fn
        self.sched: dict[tuple, dict] = {}
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scan")
        self.fail_streak: dict[str, int] = {}
        self.sym_fails: dict[str, int] = {}
        self.last_warn: dict[str, float] = {}
        self.warned_sym: set[str] = set()
        self.last_ok: dict[str, float] = {}
        self.started_at = time.time()
        self.scans_done = 0

    # ───────── çekirdek ─────────
    def scan_key(self, sym: str, tf: str, S: dict) -> tuple[int, bool]:
        """(son kapanmış mum zamanı, yeni mum var mıydı)"""
        inst = classify(sym)
        if inst is None:
            raise DataError(f"geçersiz sembol: {sym}")
        B = self.hub.get_bars(inst, tf, limit=LIMIT)
        n, last_ts = len(B), int(B.ts[-1])
        st = self.db.get_scan_state(sym, tf)
        prev = int(st["last_ts"]) if st and st.get("last_ts") else None
        if prev is not None and prev >= last_ts:
            self.db.set_scan_state(sym, tf, last_ts, B.source)
            return last_ts, False

        htf, htf_tf = None, (HTF_OF.get(tf) if S.get("c_htf") else None)
        if htf_tf:
            try:
                htf = self.hub.get_bars(inst, htf_tf, limit=300, ttl=900)
            except DataError:
                htf, htf_tf = None, None

        es = EngineSettings.from_dict(S)
        rules = build_rules(S.get("rules"), S["patterns"])
        first = prev is None
        start = max(60, n - WARM_BARS) if first else int(np.searchsorted(B.ts, prev, side="right"))
        mode = "warm" if first else "live"
        tracked = self.db.load_tracked(sym, tf, int(B.ts[max(0, n - 120)]))
        succ = int(S.get("succ_target", 1))
        stats = self.db.rule_stats(succ)
        res = Engine(es, rules).run(B, htf, htf_tf, tracked, start, stats, sym, tf, mode)

        fresh_i = (n - 2) if first else start
        new_ids = set(res.new_ids)
        for p in res.pats:
            self._announce(p, [e for e in res.events if e.pat is p], p.id in new_ids, fresh_i, mode, B, S, stats, succ)
            self.db.upsert_pattern(p)
        self.db.set_scan_state(sym, tf, last_ts, B.source)
        self.scans_done += 1
        return last_ts, True

    def _announce(self, p: Pat, evs: list, is_new: bool, fresh_i: int, mode: str, B: Bars, S: dict, stats: dict, succ: int) -> None:
        w, l = stats.get(p.tp, (0, 0))
        n = w + l
        prob = 100.0 * (w + 1.0) / (n + 2.0) if n >= int(S.get("min_samp", 8)) else None
        ntf = S.get("notify", {})
        fresh = [e for e in evs if e.i >= fresh_i]
        ft = {e.type for e in fresh}
        send = lambda kind, **kw: self.notifier.send(p, kind, B, S, prob=prob, n=n, **kw)  # noqa: E731

        if "cancel" in ft:
            if (p.ann_armed or p.ann_zone) and ntf.get("cancel", True):
                send("cancel", reason=p.cancel_reason)
            return
        if "zone" in ft:
            if ntf.get("zone", True):
                send("zone")
            p.ann_zone = p.ann_armed = True
        elif (not p.ann_armed) and p.live and p.state == 0:
            if "armed" in ft or (is_new and mode == "live"):
                if ntf.get("armed", True):
                    send("armed")
                p.ann_armed = True
            elif mode == "warm":                    # ilk taramada eski ihtimaller: sessizce kaydet (/aktif'te görünür)
                p.ann_armed = True
        if not (p.ann_armed or p.ann_zone) or not ntf.get("result", True):
            return
        tps = [e for e in fresh if e.type == "target"]
        term = [e for e in fresh if e.type in ("stop", "be", "timeout", "complete")]
        if tps and not any(e.type == "complete" for e in term):
            send("target", tp_j=int(tps[-1].detail.get("n", p.thit)))
        for e in term:
            send(e.type)

    # ───────── zamanlayıcı ─────────
    def keys(self, S: dict) -> list[tuple[str, str]]:
        off = set(S.get("symbols_off", []))
        return [(sym, tf) for sym in S["symbols"] if sym not in off for tf in S["timeframes"]]

    def _slot(self, key):
        return self.sched.setdefault(key, dict(next=0.0, fails=0, busy=False))

    def tick(self) -> int:
        S = self.db.load_settings()
        if S.get("paused"):
            return 0
        now, started = self.now(), 0
        for sym, tf in self.keys(S):
            st = self._slot((sym, tf))
            if st["busy"] or st["next"] > now:
                continue
            inst = classify(sym)
            if inst is not None and inst.is_fx and fx_market_closed(now):
                st["next"] = now + 300
                continue
            st["busy"] = True
            self.pool.submit(self._job, sym, tf, S)
            started += 1
        return started

    def seed_schedule(self) -> None:
        """Yeniden başlatmada (ör. GitHub Actions) yeni mumu beklenmeyen anahtarları ertele."""
        S, now = self.db.load_settings(), self.now()
        for sym, tf in self.keys(S):
            st = self.db.get_scan_state(sym, tf)
            if st and st.get("last_ts") and not st.get("last_err"):
                nxt = int(st["last_ts"]) + 2 * TF_SECONDS[tf] + 4
                if nxt > now:
                    self._slot((sym, tf))["next"] = nxt

    def finish(self, grace: float = 40.0) -> None:
        """Çalışan taramaların bitmesini bekle (veritabanı tutarlı kalsın)."""
        self.pool.shutdown(wait=False, cancel_futures=True)
        end = time.time() + grace
        while time.time() < end and any(v["busy"] for v in self.sched.values()):
            time.sleep(0.5)

    def force_all(self) -> int:
        S = self.db.load_settings()
        keys = self.keys(S)
        for key in keys:
            self._slot(key)["next"] = 0.0
        return len(keys)

    def _job(self, sym: str, tf: str, S: dict) -> None:
        st = self._slot((sym, tf))
        market = "fx" if (classify(sym) and classify(sym).is_fx) else "crypto"
        try:
            last_ts, _ = self.scan_key(sym, tf, S)
            now = self.now()
            nxt = last_ts + 2 * TF_SECONDS[tf] + (4 if market == "crypto" else 12)
            if nxt > now:
                st["fails"] = 0
            else:                       # beklenen yeni mum henüz yayınlanmadı → kademeli yeniden dene
                st["fails"] += 1
                nxt = now + min(30 * 2 ** min(st["fails"], 5), 600)
            st["next"] = nxt
            self.fail_streak[market] = 0
            self.sym_fails[sym] = 0
            self.warned_sym.discard(sym)
            self.last_ok[market] = now
        except Exception as e:  # noqa: BLE001
            st["fails"] += 1
            st["next"] = self.now() + min(60 * 2 ** min(st["fails"], 4), 900)
            self._on_fail(sym, tf, market, e)
        finally:
            st["busy"] = False

    def _on_fail(self, sym: str, tf: str, market: str, e: Exception) -> None:
        log.warning("tarama hatası %s %s: %s", sym, tf, str(e)[:200])
        self.db.set_scan_state(sym, tf, None, err=str(e)[:200])
        self.sym_fails[sym] = self.sym_fails.get(sym, 0) + 1
        limit = 40 if "hız sınırı" in str(e) else 6          # geçici hız sınırında kullanıcıyı hemen rahatsız etme
        if self.sym_fails[sym] >= limit and sym not in self.warned_sym:
            self.warned_sym.add(sym)
            self.notifier.warn(f"⚠️ <b>{sym}</b> için veri alınamıyor ({str(e)[:160]}).\nListeden çıkarmak için: /cikar {sym}")
        self.fail_streak[market] = self.fail_streak.get(market, 0) + 1
        if self.fail_streak[market] >= (80 if "hız sınırı" in str(e) else 12) and self.now() - self.last_warn.get(market, 0) > 3600:
            self.last_warn[market] = self.now()
            self.notifier.warn(f"⚠️ <b>{market}</b> veri kaynağı art arda hata veriyor: {str(e)[:200]}")

    def run_forever(self, stop: threading.Event) -> None:
        log.info("tarayıcı başladı")
        while not stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("tick hatası")
            stop.wait(3.0)
        self.pool.shutdown(wait=False, cancel_futures=True)
