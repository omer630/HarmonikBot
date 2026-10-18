"""/ayar menüleri (inline klavye) ve ayar değiştirme. Saf fonksiyonlar: (metin, klavye) döndürür."""
from __future__ import annotations

from .config import DEFAULT_RULES, PATTERN_NAMES, SELECTABLE_TFS, classify
from .db import DB

TF_NAMES = {"15m": "15 dk", "30m": "30 dk", "1h": "1 saat", "4h": "4 saat", "1d": "Günlük"}
DIR_NAMES = {"bull": "Sadece Bullish ▲", "bear": "Sadece Bearish ▼", "both": "İkisi de ▲▼"}


def _b(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def _kb(rows: list) -> dict:
    return {"inline_keyboard": rows}


def _ck(v: bool) -> str:
    return "✅" if v else "⬜"


def _short(sym: str) -> str:
    return sym[:-4] if sym.endswith("USDT") else sym


def _back() -> list:
    return [_b("⬅️ Geri", "m:main"), _b("✖️ Kapat", "m:close")]


# ───────────────────────── menüler ─────────────────────────
def main_menu(S: dict) -> tuple[str, dict]:
    off = set(S["symbols_off"])
    n_on = sum(1 for s in S["symbols"] if s not in off)
    pats = [n for n in PATTERN_NAMES if S["patterns"].get(n)]
    ntf = S["notify"]
    text = (
        "⚙️ <b>Ayarlar</b>" + ("  ·  <b>⏸ DURAKLATILDI</b>" if S.get("paused") else "") + "\n\n"
        f"📊 Pariteler: <b>{n_on}</b> aktif / {len(S['symbols'])} kayıtlı\n"
        f"⏱ Zaman dilimleri: <b>{', '.join(TF_NAMES[t] for t in SELECTABLE_TFS if t in S['timeframes']) or '—'}</b>\n"
        f"📐 Formasyonlar: <b>{len(pats)}</b> açık ({', '.join(pats[:5])}{'…' if len(pats) > 5 else ''})\n"
        f"↕️ Yön: <b>{DIR_NAMES[S['direction']]}</b>\n"
        f"⭐ Min. skor: <b>{S['min_score']}</b>\n"
        f"🔔 Bildirim: {_ck(ntf['armed'])} ihtimal  {_ck(ntf['zone'])} PRZ  {_ck(ntf['cancel'])} iptal  {_ck(ntf['result'])} sonuç\n"
        f"🖼 Görsel kart: {_ck(S['card'])}\n\n"
        "Parite eklemek: <code>/ekle BTC SOL EURUSD</code>\nÇıkarmak: <code>/cikar BTC</code>\n"
        "Oran aralıkları: <code>/kural</code>")
    rows = [
        [_b("📊 Pariteler", "m:sym"), _b("⏱ Zaman dilimleri", "m:tf")],
        [_b("📐 Formasyonlar", "m:pat"), _b("↕️ Yön", "m:dir")],
        [_b("⭐ Min. skor", "m:score"), _b("🔔 Bildirimler", "m:ntf")],
        [_b("🎯 Giriş / Hedef", "m:trade"), _b("🚫 İptal kuralları", "m:cancel")],
        [_b("▶️ Devam et" if S.get("paused") else "⏸ Duraklat", "s:pause")],
        [_b("✖️ Kapat", "m:close")]]
    return text, _kb(rows)


def sym_menu(S: dict) -> tuple[str, dict]:
    off = set(S["symbols_off"])
    syms = list(S["symbols"])
    rows, row = [], []
    for s in syms:
        row.append(_b(f"{_ck(s not in off)} {_short(s)}", f"s:sym:{s}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(_back())
    text = ("📊 <b>Pariteler</b>\n✅ taranıyor · ⬜ geçici kapalı (listede kalır)\n\n"
            "Yeni eklemek için <code>/ekle ADA XRP USDCHF</code>, listeden silmek için <code>/cikar ADA</code>.")
    return text, _kb(rows)


def tf_menu(S: dict) -> tuple[str, dict]:
    rows = [[_b(f"{_ck(t in S['timeframes'])} {TF_NAMES[t]}", f"s:tf:{t}")] for t in SELECTABLE_TFS]
    rows.append(_back())
    return "⏱ <b>Zaman dilimleri</b>\nİstediklerini aç/kapat. Değişiklik bir sonraki taramada devreye girer.", _kb(rows)


def pat_menu(S: dict) -> tuple[str, dict]:
    rows, row = [], []
    for i, n in enumerate(PATTERN_NAMES):
        row.append(_b(f"{_ck(S['patterns'].get(n, False))} {n}", f"s:pat:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(_back())
    return ("📐 <b>Formasyonlar</b>\nAçık olanlar taranır. Oran aralıklarını değiştirmek için <code>/kural</code>.\n"
            "<i>Özel</i> = kendi kuralın (varsayılan kapalı)."), _kb(rows)


def dir_menu(S: dict) -> tuple[str, dict]:
    rows = [[_b(("🔘 " if S["direction"] == k else "⚪ ") + v, f"s:dir:{k}")] for k, v in DIR_NAMES.items()]
    rows.append(_back())
    return "↕️ <b>Yön</b>\nHangi yöndeki formasyonlar bildirilsin?", _kb(rows)


def score_menu(S: dict) -> tuple[str, dict]:
    v = S["min_score"]
    rows = [[_b("−5", "s:score:-5"), _b(f"  {v}  ", "m:score"), _b("+5", "s:score:+5")],
            [_b(str(x), f"s:score:={x}") for x in (45, 50, 55, 60)],
            [_b(str(x), f"s:score:={x}") for x in (65, 70, 75, 80)], _back()]
    return (f"⭐ <b>Minimum kalite skoru: {v}</b>\nDaha yüksek = daha az ama daha seçici sinyal. "
            "Skor; oran isabeti, PRZ darlığı, trend (EMA/üst periyot), konum ve geçmiş başarıdan oluşur."), _kb(rows)


def ntf_menu(S: dict) -> tuple[str, dict]:
    n = S["notify"]
    rows = [[_b(f"{_ck(n['armed'])} 🟡 PRZ belirlendi (ihtimal)", "s:ntf:armed")],
            [_b(f"{_ck(n['zone'])} 🟢 PRZ'ye ulaştı (giriş/stop/TP)", "s:ntf:zone")],
            [_b(f"{_ck(n['cancel'])} 🔴 Formasyon iptal", "s:ntf:cancel")],
            [_b(f"{_ck(n['result'])} 🎯 Sonuç (TP / stop / maliyet)", "s:ntf:result")],
            [_b(f"{_ck(S['card'])} 🖼 Mesajlara görsel kart ekle", "s:ntf:card")], _back()]
    return "🔔 <b>Bildirimler</b>", _kb(rows)


def trade_menu(S: dict) -> tuple[str, dict]:
    sc = int(S["succ_target"])
    rows = [[_b(("🔘 " if sc == k else "⚪ ") + f"Başarı = TP{k}", f"s:succ:{k}") for k in (1, 2, 3)],
            [_b(("🔘 " if S["entry_mode"] == "limit" else "⚪ ") + "Giriş: limit (D'ye değince)", "s:entry:limit")],
            [_b(("🔘 " if S["entry_mode"] == "reversal" else "⚪ ") + "Giriş: dönüş mumu teyidi", "s:entry:reversal")],
            [_b(f"{_ck(S['be_after_t1'])} TP1 sonrası stop maliyete", "s:adv:be_after_t1")], _back()]
    return (f"🎯 <b>Giriş / Hedef</b>\nHedefler (A→D bacağı): TP1 {S['t1']} · TP2 {S['t2']} · TP3 {S['t3']}\n"
            "Değiştirmek için: <code>/hedef 0.382 0.618 1.0</code>\n"
            "<i>Başarı</i>, istatistikte bir formasyonun kazanç sayılması için ulaşması gereken hedeftir."), _kb(rows)


def cancel_menu(S: dict) -> tuple[str, dict]:
    rows = [[_b(f"{_ck(S['cancel_c'])} C noktası aşılırsa iptal", "s:adv:cancel_c")],
            [_b(f"{_ck(S['cancel_timeout'])} Süre dolarsa iptal ({S['wait']} mum)", "s:adv:cancel_timeout")],
            [_b("−10 mum", "s:wait:-10"), _b("+10 mum", "s:wait:+10")],
            [_b(f"{_ck(S['cancel_escape'])} PRZ'ye yaklaşmadan ters yöne kaçarsa ({S['escape_atr']} ATR)", "s:adv:cancel_escape")],
            [_b("−0.5 ATR", "s:escape:-0.5"), _b("+0.5 ATR", "s:escape:+0.5")],
            [_b(f"{_ck(S['need_b'])} İhtimal mesajı için fiyat B'yi geçmeli", "s:adv:need_b")], _back()]
    return "🚫 <b>İptal kuralları</b>\nİptal mesajı sadece daha önce duyurulmuş formasyonlar için gönderilir.", _kb(rows)


MENUS = {"main": main_menu, "sym": sym_menu, "tf": tf_menu, "pat": pat_menu, "dir": dir_menu, "score": score_menu,
         "ntf": ntf_menu, "trade": trade_menu, "cancel": cancel_menu}


# ───────────────────────── ayar uygulama ─────────────────────────
def apply_callback(db: DB, data: str) -> tuple[str, str]:
    """Geri dönüş: (yeniden çizilecek menü adı, kullanıcıya kısa bildirim)."""
    parts = data.split(":")
    if parts[0] == "m":
        return parts[1], ""
    S = db.load_settings()
    kind, key = parts[1], parts[2] if len(parts) > 2 else ""
    if kind == "pause":
        db.save_setting("paused", not S.get("paused", False))
        return "main", "Duraklatıldı" if not S.get("paused") else "Devam ediyor"
    if kind == "sym":
        off = set(S["symbols_off"])
        off.symmetric_difference_update({key})
        db.save_setting("symbols_off", sorted(off))
        return "sym", f"{_short(key)} {'kapatıldı' if key in off else 'açıldı'}"
    if kind == "tf":
        tfs = [t for t in SELECTABLE_TFS if (t in S["timeframes"]) != (t == key)]
        if not tfs:
            return "tf", "En az bir zaman dilimi açık olmalı"
        db.save_setting("timeframes", tfs)
        return "tf", ""
    if kind == "pat":
        name = PATTERN_NAMES[int(key)]
        pats = dict(S["patterns"])
        pats[name] = not pats.get(name, False)
        db.save_setting("patterns", pats)
        return "pat", ""
    if kind == "dir":
        db.save_setting("direction", key)
        return "dir", ""
    if kind == "score":
        v = int(key[1:]) if key.startswith("=") else S["min_score"] + int(key)
        db.save_setting("min_score", max(30, min(95, v)))
        return "score", ""
    if kind == "ntf":
        if key == "card":
            db.save_setting("card", not S["card"])
        else:
            n = dict(S["notify"])
            n[key] = not n.get(key, True)
            db.save_setting("notify", n)
        return "ntf", ""
    if kind == "succ":
        db.save_setting("succ_target", int(key))
        return "trade", ""
    if kind == "entry":
        db.save_setting("entry_mode", key)
        return "trade", ""
    if kind == "adv":
        db.save_setting(key, not S[key])
        return ("trade" if key == "be_after_t1" else "cancel"), ""
    if kind == "wait":
        db.save_setting("wait", max(10, min(300, S["wait"] + int(key))))
        return "cancel", ""
    if kind == "escape":
        db.save_setting("escape_atr", round(max(1.0, min(10.0, S["escape_atr"] + float(key))), 1))
        return "cancel", ""
    return "main", ""


# ───────────────────────── /kural ─────────────────────────
def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum()).replace("ö", "o")


def find_rule(tokens: list[str]) -> tuple[str | None, list[str]]:
    names = {_norm(n): n for n in PATTERN_NAMES}
    for k in (3, 2, 1):
        if len(tokens) >= k and _norm(" ".join(tokens[:k])) in names:
            return names[_norm(" ".join(tokens[:k]))], tokens[k:]
    return None, tokens


def rule_text(S: dict, name: str) -> str:
    r = dict(DEFAULT_RULES[name])
    r.update((S.get("rules") or {}).get(name, {}))
    mark = "  <i>(özelleştirilmiş)</i>" if name in (S.get("rules") or {}) else ""
    return (f"<b>{name}</b>{mark}\n"
            f"AB/XA: {r['ab'][0]} – {r['ab'][1]}\nXC/XA: {r['xc'][0]} – {r['xc'][1]}\n"
            f"BC/AB: {r['bc'][0]} – {r['bc'][1]}\nCD/BC: {r['cd'][0]} – {r['cd'][1]}\n"
            f"D oranı: {r['d'][0]} – {r['d'][1]}  (<b>{r['ref']}</b> bacağına göre)\n"
            f"Giriş oranı: {r['ent']}   ·   Stop oranı: {r['stp']} {'(X noktası)' if r['stp'] == 0 else '(XA)'}")


RULE_HELP = (
    "📐 <b>Formasyon kuralları</b>\n"
    "<code>/kural Gartley</code> — kuralı göster\n"
    "<code>/kural Gartley ab 0.60 0.68</code> — AB/XA aralığı\n"
    "<code>/kural Gartley bc 0.382 0.886</code> · alanlar: <code>ab xc bc cd d</code>\n"
    "<code>/kural Bat giris 0.886</code> — giriş oranı\n"
    "<code>/kural Bat stop 0</code> — stop oranı (0 = X noktası)\n"
    "<code>/kural Cypher ref XC</code> — D hangi bacağa göre (XA/XC)\n"
    "<code>/kural Bat sifirla</code> — varsayılana dön\n"
    "Adlar: " + ", ".join(PATTERN_NAMES) + "\nXC/XA için 0 – 99 = kısıtlama yok.")


def set_rule(db: DB, S: dict, name: str, rest: list[str]) -> str:
    rules = {k: dict(v) for k, v in (S.get("rules") or {}).items()}
    base = rules.setdefault(name, {})
    cur = dict(DEFAULT_RULES[name])
    cur.update(base)
    field = rest[0].lower() if rest else ""
    try:
        if field in ("sifirla", "sıfırla", "reset"):
            rules.pop(name, None)
        elif field in ("ab", "xc", "bc", "cd", "d"):
            lo, hi = (float(x.replace(",", ".")) for x in rest[1:3])
            if lo < 0 or hi < lo:
                return "❌ Aralık hatalı: en az ≤ en çok olmalı."
            base[field] = [lo, hi]
        elif field in ("giris", "giriş", "ent"):
            base["ent"] = float(rest[1].replace(",", "."))
        elif field in ("stop", "stp"):
            base["stp"] = float(rest[1].replace(",", "."))
        elif field == "ref":
            if rest[1].upper() not in ("XA", "XC"):
                return "❌ ref: XA veya XC olmalı."
            base["ref"] = rest[1].upper()
        else:
            return RULE_HELP
    except (ValueError, IndexError):
        return "❌ Değer okunamadı.\n\n" + RULE_HELP
    db.save_setting("rules", rules)
    S2 = db.load_settings()
    return "✅ Kaydedildi.\n\n" + rule_text(S2, name) + "\n<i>Yeni oranlar bir sonraki taramada geçerli olur.</i>"


def parse_symbols(tokens: list[str]) -> tuple[list[str], list[str]]:
    ok, bad = [], []
    for t in tokens:
        inst = classify(t)
        if inst is None:
            bad.append(t)
        elif inst.symbol not in ok:
            ok.append(inst.symbol)
    return ok, bad
