"""Telegram komutları, /ayar menüsü ve güncelleme döngüsü (long polling)."""
from __future__ import annotations

import html
import logging
import re
import threading
import time

from . import menus, stats
from .config import PATTERN_NAMES, Env, classify
from .data import DataError
from .db import DB
from .demo import synthetic_bars
from .engine import Engine, EngineSettings, build_rules
from .messages import TF_TXT, build
from .render import render_card
from .scanner import Scanner
from .telegram_api import Telegram, TelegramError

log = logging.getLogger("hbot.bot")

COMMANDS = [("aktif", "Aktif formasyonlar"), ("durum", "Bot durumu"), ("istatistik", "Başarı istatistiği"),
            ("ayar", "Ayar menüsü"), ("liste", "Takip listesi"), ("ekle", "Parite ekle"), ("cikar", "Parite çıkar"),
            ("kural", "Formasyon oranları"), ("hedef", "TP oranları"), ("duraklat", "Taramayı duraklat"),
            ("devam", "Taramaya devam"), ("tara", "Şimdi tara"), ("test", "Örnek kart gönder"), ("yardim", "Yardım")]

HELP = (
    "🤖 <b>HaP Harmonik Bot</b>\n"
    "Kripto ve forex'te harmonik formasyonları 7/24 tarar; <b>kapanmış mumlarla</b> çalışır.\n\n"
    "🟡 <b>PRZ belirlendi</b> — ihtimal (fiyat B'yi geçince)\n"
    "🟢 <b>PRZ'ye ulaştı</b> — giriş, stop, TP1-2-3\n"
    "🔴 <b>İptal</b> — C aşıldı / süre doldu / PRZ'ye yaklaşmadan ters yöne kaçtı\n"
    "🎯 Sonuç — TP / stop / maliyette kapanış\n\n"
    "<b>Komutlar</b>\n"
    "/aktif — şu an takip edilen formasyonlar\n"
    "/istatistik — başarı oranları (formasyon / zaman dilimi / parite)\n"
    "/ayar — pariteler, zaman dilimleri, formasyonlar, yön, skor, bildirimler\n"
    "/ekle BTC SOL EURUSD — parite ekle · /cikar BTC — çıkar\n"
    "/kural — formasyon oran aralıklarını göster / değiştir\n"
    "/hedef 0.382 0.618 1.0 — TP oranları\n"
    "/liste · /durum · /duraklat · /devam · /tara · /test\n\n"
    "<i>Analiz aracıdır, yatırım tavsiyesi değildir.</i>")


def _ago(t: float | None) -> str:
    if not t:
        return "—"
    s = max(0, int(time.time() - t))
    return f"{s}sn önce" if s < 90 else f"{s // 60}dk önce" if s < 5400 else f"{s // 3600}sa önce"


def _chunks(lines: list[str], limit: int = 3800) -> list[str]:
    out, cur = [], ""
    for ln in lines:
        if len(cur) + len(ln) + 1 > limit and cur:
            out.append(cur)
            cur = ""
        cur += ln + "\n"
    if cur:
        out.append(cur)
    return out


class BotApp:
    def __init__(self, tg: Telegram, db: DB, scanner: Scanner, env: Env, hub):
        self.tg, self.db, self.sc, self.env, self.hub = tg, db, scanner, env, hub
        self.offset = 0
        self.started = time.time()

    # ───────── yetki / sohbetler ─────────
    def chats(self) -> list[int]:
        ids: list[int] = []
        if re.fullmatch(r"-?\d+", self.env.chat_id or ""):
            ids.append(int(self.env.chat_id))
        for i in sorted(self.env.allowed) + list(self.db.get_meta("owners", [])):
            if i not in ids:
                ids.append(int(i))
        return ids

    def _authorized(self, uid: int, chat: int) -> bool:
        return uid in self.chats() or chat in self.chats()

    def _say(self, chat: int, text: str, markup: dict | None = None) -> int | None:
        try:
            return self.tg.send_message(chat, text, reply_markup=markup)
        except Exception as e:  # noqa: BLE001
            log.error("mesaj gönderilemedi: %s", e)
            return None

    # ───────── güncelleme döngüsü ─────────
    def poll_forever(self, stop: threading.Event) -> None:
        self.tg.set_commands(COMMANDS)
        self.announce_start()
        log.info("komut dinleyici başladı")
        while not stop.is_set():
            try:
                updates = self.tg.get_updates(self.offset, timeout=25)
            except Exception as e:  # noqa: BLE001
                log.warning("getUpdates hatası: %s", e)
                stop.wait(5)
                continue
            for u in updates:
                self.offset = int(u["update_id"]) + 1
                try:
                    self.handle(u)
                except Exception:  # noqa: BLE001
                    log.exception("güncelleme işlenemedi")

    def poll_until(self, deadline: float, stop: threading.Event | None = None) -> None:
        """Tek seferlik (GitHub Actions) mod: süre dolana kadar komutları dinler; offset DB'de saklanır."""
        self.offset = int(self.db.get_meta("tg_offset", 0) or 0)
        if not self.db.get_meta("cmds_set"):
            self.tg.set_commands(COMMANDS)
            self.db.set_meta("cmds_set", 1)
        if self.chats() and not self.db.get_meta("start_announced"):
            self.announce_start()
            self.db.set_meta("start_announced", 1)
        while time.time() < deadline and not (stop and stop.is_set()):
            wait = int(min(20, max(1, deadline - time.time() - 2)))
            try:
                updates = self.tg.get_updates(self.offset, timeout=wait)
            except Exception as e:  # noqa: BLE001
                log.warning("getUpdates hatası: %s", e)
                time.sleep(3)
                continue
            for u in updates:
                self.offset = int(u["update_id"]) + 1
                self.db.set_meta("tg_offset", self.offset)
                try:
                    self.handle(u)
                except Exception:  # noqa: BLE001
                    log.exception("güncelleme işlenemedi")

    def announce_start(self) -> None:
        S = self.db.load_settings()
        chats = self.chats()
        if not chats:
            log.info("Henüz sahip yok: botu Telegram'da açıp /start yaz.")
            return
        off = set(S["symbols_off"])
        n = sum(1 for s in S["symbols"] if s not in off)
        for c in chats[:1] + chats[1:]:
            self._say(c, f"✅ <b>Bot başladı</b> · {n} parite × {len(S['timeframes'])} zaman dilimi izleniyor.\n"
                         "İlk tarama geçmişi sessizce işler; yeni sinyaller kapanan mumlarla gelir. /ayar · /yardim")

    def handle(self, u: dict) -> None:
        if "callback_query" in u:
            return self._on_callback(u["callback_query"])
        m = u.get("message")
        if not m or not m.get("text"):
            return
        chat, uid, text = int(m["chat"]["id"]), int(m.get("from", {}).get("id", m["chat"]["id"])), m["text"].strip()
        if not text.startswith("/"):
            return
        parts = text.split()
        cmd, args = parts[0][1:].split("@")[0].lower(), parts[1:]
        if cmd == "start" and not self.chats() and m["chat"].get("type") == "private":
            self.db.set_meta("owners", [uid])
            self._say(chat, "👋 Sahip olarak kaydedildin. Bildirimler bu sohbete gelecek.\n\n" + HELP)
            return
        if not self._authorized(uid, chat):
            self._say(chat, "⛔ Bu bot özeldir; yetkin yok.")
            return
        fn = getattr(self, f"cmd_{ {'yardım': 'yardim', 'çıkar': 'cikar', 'istatistik': 'istatistik'}.get(cmd, cmd) }", None)
        if fn is None:
            self._say(chat, "Bilinmeyen komut. /yardim")
            return
        fn(chat, args)

    # ───────── komutlar ─────────
    def cmd_start(self, chat, args):
        self._say(chat, HELP)

    def cmd_yardim(self, chat, args):
        self._say(chat, HELP)

    def _tv(self, sym: str) -> str:
        inst = classify(sym)
        try:
            return self.hub.tv_symbol(inst)
        except Exception:  # noqa: BLE001
            return f"OANDA:{sym}" if inst and inst.is_fx else f"BINANCE:{sym}"

    def cmd_aktif(self, chat, args):
        from .data import tv_link
        pats = self.db.active_patterns(announced_only=True)
        if not pats:
            self._say(chat, "Şu anda duyurulmuş aktif formasyon yok.\nYeni ihtimaller kapanan mumlarla gelir.")
            return
        pats.sort(key=lambda p: (-p.state, -p.score))
        lines = [f"📋 <b>Aktif formasyonlar</b> ({len(pats)})\n"]
        from .fmt import fmt_price as fp
        for p in pats[:30]:
            st = f"⚡ pozisyonda {p.thit}/3" if p.state == 1 else ("🟢 PRZ'de" if p.zone_ts else "⏳ PRZ bekleniyor")
            url = html.escape(tv_link(self._tv(p.symbol), p.tf), quote=True)
            lines.append(f"{st} · <b>{p.symbol}</b> {TF_TXT.get(p.tf, p.tf)} {'▲' if p.dir > 0 else '▼'} {p.rule} ⭐{p.score:.0f}\n"
                         f"   PRZ {fp(p.zone_bottom, p.symbol)}–{fp(p.zone_top, p.symbol)} · giriş {fp(p.ent, p.symbol)} · "
                         f"stop {fp(p.stp, p.symbol)} · <a href=\"{url}\">grafik</a>")
        for part in _chunks(lines):
            self._say(chat, part)

    def cmd_durum(self, chat, args):
        S = self.db.load_settings()
        keys = self.sc.keys(S)
        states = self.db.all_scan_states()
        errs = sorted((s for s in states if s["err_count"] > 0), key=lambda s: -s["err_count"])
        act = len(self.db.active_patterns(announced_only=True))
        up = int(time.time() - self.started)
        lines = [f"🩺 <b>Durum</b>{'  ⏸ DURAKLATILDI' if S.get('paused') else '  ▶️ çalışıyor'}",
                 f"Çalışma süresi: {up // 86400}g {up % 86400 // 3600}sa {up % 3600 // 60}dk",
                 f"İzlenen: {len(keys)} (parite × zaman dilimi) · tamamlanan tarama: {self.sc.scans_done}",
                 f"Aktif formasyon: {act}",
                 f"Son başarılı veri → kripto: {_ago(self.sc.last_ok.get('crypto'))} · forex: {_ago(self.sc.last_ok.get('fx'))}"]
        if errs:
            lines.append(f"\n⚠️ <b>Hatalı {len(errs)} anahtar</b>")
            for s in errs[:6]:
                lines.append(f"• {s['symbol']} {s['tf']} ({s['err_count']}×): {html.escape((s.get('last_err') or '')[:90])}")
        he = getattr(self.hub, "errors", [])[-3:]
        if he:
            lines.append("\nSon veri hataları:")
            lines += [f"• {html.escape(sym)}: {html.escape(msg[:100])}" for _, sym, msg in he]
        self._say(chat, "\n".join(lines))

    def cmd_liste(self, chat, args):
        S = self.db.load_settings()
        off = set(S["symbols_off"])
        fmt = lambda xs: " ".join((("⬜" if s in off else "") + (s[:-4] if s.endswith("USDT") else s)) for s in xs)  # noqa: E731
        crypto = [s for s in S["symbols"] if classify(s) and not classify(s).is_fx]
        fx = [s for s in S["symbols"] if classify(s) and classify(s).is_fx]
        pats = [n for n in PATTERN_NAMES if S["patterns"].get(n)]
        text = (f"📋 <b>Takip listesi</b>\n\n<b>Kripto ({len(crypto)})</b>\n{fmt(crypto)}\n\n<b>Forex / emtia ({len(fx)})</b>\n{fmt(fx)}\n\n"
                f"⏱ {', '.join(menus.TF_NAMES[t] for t in S['timeframes'])}\n📐 {', '.join(pats)}\n"
                f"↕️ {menus.DIR_NAMES[S['direction']]} · ⭐ min skor {S['min_score']}\n<i>⬜ = geçici kapalı</i>")
        self._say(chat, text)

    def cmd_ekle(self, chat, args):
        if not args:
            self._say(chat, "Kullanım: <code>/ekle BTC SOL EURUSD XAUUSD</code>")
            return
        ok, bad = menus.parse_symbols(args)
        S = self.db.load_settings()
        syms, off, added, failed = list(S["symbols"]), set(S["symbols_off"]), [], []
        for s in ok:
            if s in syms and s not in off:
                continue
            try:
                self.hub.get_bars(classify(s), "1h", limit=120, ttl=0)
            except DataError as e:
                failed.append(f"{s} ({html.escape(str(e)[:80])})")
                continue
            if s not in syms:
                syms.append(s)
            off.discard(s)
            added.append(s)
        self.db.save_setting("symbols", syms)
        self.db.save_setting("symbols_off", sorted(off))
        msg = []
        if added:
            msg.append("✅ Eklendi: " + ", ".join(added))
        if failed:
            msg.append("❌ Veri bulunamadı, eklenmedi: " + "; ".join(failed))
        if bad:
            msg.append("❓ Anlaşılamadı: " + ", ".join(html.escape(b) for b in bad))
        self._say(chat, "\n".join(msg) or "Hepsi zaten listede.")

    def cmd_cikar(self, chat, args):
        if not args:
            self._say(chat, "Kullanım: <code>/cikar BTC SOL</code>")
            return
        ok, bad = menus.parse_symbols(args)
        S = self.db.load_settings()
        syms = [s for s in S["symbols"] if s not in ok]
        gone = [s for s in ok if s in S["symbols"]]
        self.db.save_setting("symbols", syms)
        self.db.save_setting("symbols_off", [s for s in S["symbols_off"] if s in syms])
        self._say(chat, ("🗑 Çıkarıldı: " + ", ".join(gone)) if gone else "Listede bulunamadı.")

    def cmd_ayar(self, chat, args):
        text, kb = menus.main_menu(self.db.load_settings())
        self._say(chat, text, kb)

    def cmd_kural(self, chat, args):
        S = self.db.load_settings()
        name, rest = menus.find_rule(args)
        if name is None:
            self._say(chat, menus.RULE_HELP)
        elif not rest:
            self._say(chat, menus.rule_text(S, name))
        else:
            self._say(chat, menus.set_rule(self.db, S, name, rest))

    def cmd_hedef(self, chat, args):
        try:
            a, b, c = (float(x.replace(",", ".")) for x in args[:3])
            assert 0 < a < b < c <= 5
        except Exception:  # noqa: BLE001
            self._say(chat, "Kullanım: <code>/hedef 0.382 0.618 1.0</code> (artan, A→D bacağının oranı)")
            return
        for k, v in zip(("t1", "t2", "t3"), (a, b, c)):
            self.db.save_setting(k, v)
        self._say(chat, f"✅ Hedefler: TP1 {a} · TP2 {b} · TP3 {c}")

    def cmd_duraklat(self, chat, args):
        self.db.save_setting("paused", True)
        self._say(chat, "⏸ Tarama duraklatıldı. /devam ile sürdür.")

    def cmd_devam(self, chat, args):
        self.db.save_setting("paused", False)
        self._say(chat, "▶️ Tarama sürüyor.")

    def cmd_tara(self, chat, args):
        n = self.sc.force_all()
        self._say(chat, f"🔄 {n} anahtar için yeni mum kontrolü başlatıldı.")

    def cmd_istatistik(self, chat, args):
        g = {"formasyon": "rule", "tf": "tf", "zaman": "tf", "parite": "symbol"}
        s = {"canli": "live", "canlı": "live", "gecmis": "bt", "geçmiş": "bt", "hepsi": "all"}
        group = next((g[a.lower()] for a in args if a.lower() in g), "rule")
        src = next((s[a.lower()] for a in args if a.lower() in s), "all")
        self._send_stats(chat, None, group, src)

    def _stats_kb(self, group: str, src: str) -> dict:
        mark = lambda cur, k: "🔘 " if cur == k else "⚪ "  # noqa: E731
        return {"inline_keyboard": [
            [{"text": mark(group, k) + v, "callback_data": f"st:{k}:{src}"} for k, v in stats.GROUPS.items()],
            [{"text": mark(src, k) + v, "callback_data": f"st:{group}:{k}"} for k, v in stats.SOURCES.items()]]}

    def _send_stats(self, chat, mid, group, src):
        succ = int(self.db.load_settings().get("succ_target", 1))
        text = stats.render(self.db, group, src, succ)
        kb = self._stats_kb(group, src)
        if mid:
            self.tg.edit_message_text(chat, mid, text, reply_markup=kb)
        else:
            self._say(chat, text, kb)

    def cmd_test(self, chat, args):
        S = self.db.load_settings()
        B = synthetic_bars("Gartley", 1, "zone")
        es = EngineSettings.from_dict(S)
        es.min_score = 30
        res = Engine(es, build_rules(S.get("rules"), S["patterns"])).run(B, None, None, [], 0, {}, "BTCUSDT", "4h", "live")
        p = next((x for x in res.pats if x.rule == "Gartley"), None)
        if p is None:
            self._say(chat, "Örnek formasyon üretilemedi.")
            return
        text = "🧪 <b>TEST — örnek kart (gerçek sinyal değildir)</b>\n" + build("zone", p, tv=B.tv, prob=58, samples=24)
        try:
            png = render_card(B, p, "zone", tz=self.env.tz, prob=58, samples=24)
            self.tg.send_photo(chat, png, text)
        except (TelegramError, Exception) as e:  # noqa: BLE001
            log.exception("test kartı")
            self._say(chat, f"Kart gönderilemedi: {html.escape(str(e)[:150])}\n\n{text}")

    # ───────── inline düğmeler ─────────
    def _on_callback(self, cq: dict) -> None:
        msg = cq.get("message") or {}
        chat, mid = int(msg.get("chat", {}).get("id", 0)), int(msg.get("message_id", 0))
        uid = int(cq.get("from", {}).get("id", 0))
        if not self._authorized(uid, chat):
            self.tg.answer_callback(cq["id"], "Yetkisiz")
            return
        data = cq.get("data", "")
        try:
            if data.startswith("st:"):
                _, group, src = data.split(":")
                self._send_stats(chat, mid, group, src)
                self.tg.answer_callback(cq["id"])
                return
            menu, toast = menus.apply_callback(self.db, data)
            if menu == "close":
                self.tg.edit_message_text(chat, mid, "✅ Ayarlar kaydedildi. Değişiklikler bir sonraki taramada geçerli olur.")
            else:
                text, kb = menus.MENUS[menu](self.db.load_settings())
                self.tg.edit_message_text(chat, mid, text, reply_markup=kb)
            self.tg.answer_callback(cq["id"], toast)
        except TelegramError as e:
            log.warning("callback: %s", e)
            self.tg.answer_callback(cq["id"])
