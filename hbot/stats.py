"""İstatistik: veritabanındaki formasyon kayıtlarından özet tablo (Telegram'da <pre> olarak gösterilir)."""
from __future__ import annotations

import html
from collections import defaultdict

from .db import DB

GROUPS = {"rule": "Formasyon", "tf": "Zaman dilimi", "symbol": "Parite"}
SOURCES = {"all": "Hepsi", "live": "Canlı", "bt": "Geçmiş tarama"}


def summarize(db: DB, group: str = "rule", source: str = "all", succ: int = 1) -> list[dict]:
    """Her grup için: doğan (B geçildi), girişe ulaşan, başarılı, başarısız, iptal, sürüyor, başarı %."""
    rows = db.stat_rows({"all": None, "live": True, "bt": False}[source])
    key = {"rule": "rule_name", "tf": "tf", "symbol": "symbol"}[group]
    agg: dict[str, dict] = defaultdict(lambda: dict(born=0, entered=0, win=0, loss=0, cancel=0, open=0))
    for r in rows:
        a = agg[str(r[key])]
        a["born"] += 1
        if r["status"] == "cancelled":
            a["cancel"] += 1
            continue
        if r["entered"]:
            a["entered"] += 1
            if r["status"] in ("done", "stopped"):
                a["win" if r["thit"] >= succ else "loss"] += 1
            else:
                a["open"] += 1
    out = []
    for name, a in agg.items():
        n = a["win"] + a["loss"]
        out.append(dict(name=name, rate=(100.0 * a["win"] / n if n else None), n=n, **a))
    out.sort(key=lambda d: (-d["born"], d["name"]))
    return out


def render(db: DB, group: str = "rule", source: str = "all", succ: int = 1, limit: int = 18) -> str:
    rows = summarize(db, group, source, succ)
    head = (f"📊 <b>İstatistik</b> · {SOURCES[source]} · {GROUPS[group]} bazlı\n"
            f"Başarı = girişten sonra en az TP{succ}'e ulaşma. İptal ve henüz sonuçlanmayanlar oranı etkilemez.\n")
    if not rows:
        return head + "\nHenüz kayıt yok. Bot ilk taramasını tamamladıkça dolacak."
    w = max(7, min(12, max(len(r["name"]) for r in rows)))
    lines = [f"{'':<{w}} {'doğ':>4} {'gir':>4} {'✔':>3} {'✘':>3} {'iptal':>5} {'başarı':>7}"]
    tot = dict(born=0, entered=0, win=0, loss=0, cancel=0)
    for r in rows[:limit]:
        rate = "  —" if r["rate"] is None else f"{r['rate']:5.0f}%"
        lines.append(f"{html.escape(r['name'][:w]):<{w}} {r['born']:>4} {r['entered']:>4} {r['win']:>3} {r['loss']:>3} "
                     f"{r['cancel']:>5} {rate:>7}")
    for r in rows:
        for k in tot:
            tot[k] += r[k]
    n = tot["win"] + tot["loss"]
    rate = "  —" if not n else f"{100.0 * tot['win'] / n:5.0f}%"
    lines.append("─" * (w + 33))
    lines.append(f"{'TOPLAM':<{w}} {tot['born']:>4} {tot['entered']:>4} {tot['win']:>3} {tot['loss']:>3} {tot['cancel']:>5} {rate:>7}")
    more = f"\n… ve {len(rows) - limit} satır daha" if len(rows) > limit else ""
    return head + "\n<pre>" + "\n".join(lines) + "</pre>" + more + "\n<i>doğ: B geçilip duyurulan · gir: girişe ulaşan</i>"
