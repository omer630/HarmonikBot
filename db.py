"""SQLite kalıcılık: ayarlar, formasyonlar, tarama durumu, istatistik sorguları."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from .config import merged_settings
from .models import Pat

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS patterns (
    id TEXT PRIMARY KEY, symbol TEXT, tf TEXT, src TEXT, dir INTEGER, rule INTEGER, rule_name TEXT,
    status TEXT, live INTEGER, entered INTEGER, thit INTEGER, result TEXT, cancel_reason TEXT,
    c_ts INTEGER, created_ts INTEGER, end_ts INTEGER, score REAL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pat_sym ON patterns(symbol, tf, c_ts);
CREATE INDEX IF NOT EXISTS ix_pat_status ON patterns(status);
CREATE TABLE IF NOT EXISTS scan_state (
    symbol TEXT, tf TEXT, last_ts INTEGER, last_scan REAL, source TEXT, err_count INTEGER DEFAULT 0, last_err TEXT,
    PRIMARY KEY (symbol, tf)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class DB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=%s" % ("DELETE" if os.environ.get("RUN_ONCE") == "1" else "WAL"))
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        """WAL'ı ana dosyaya işle ve kapat (tek dosya olarak saklanabilsin)."""
        with self.lock:
            try:
                self.conn.commit()
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                self.conn.close()

    # ───────── ayarlar ─────────
    def load_settings(self) -> dict:
        with self.lock:
            rows = self.conn.execute("SELECT key, value FROM settings").fetchall()
        return merged_settings({r["key"]: json.loads(r["value"]) for r in rows})

    def save_setting(self, key: str, value) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                              (key, json.dumps(value, ensure_ascii=False)))
            self.conn.commit()

    def get_meta(self, key: str, default=None):
        with self.lock:
            r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def set_meta(self, key: str, value) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                              (key, json.dumps(value)))
            self.conn.commit()

    # ───────── formasyonlar ─────────
    def upsert_pattern(self, p: Pat) -> None:
        d = p.to_dict()
        with self.lock:
            self.conn.execute(
                """INSERT INTO patterns(id,symbol,tf,src,dir,rule,rule_name,status,live,entered,thit,result,cancel_reason,
                                        c_ts,created_ts,end_ts,score,data)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET src=excluded.src,status=excluded.status,live=excluded.live,
                     entered=excluded.entered,thit=excluded.thit,result=excluded.result,cancel_reason=excluded.cancel_reason,
                     end_ts=excluded.end_ts,score=excluded.score,data=excluded.data""",
                (p.id, p.symbol, p.tf, p.src, p.dir, p.tp, p.rule, p.status, int(p.live), int(p.fill_ts is not None), p.thit,
                 p.result, p.cancel_reason, p.ct, p.created_ts, p.end_ts, p.score, json.dumps(d, ensure_ascii=False)))
            self.conn.commit()

    def upsert_many(self, pats: list[Pat]) -> None:
        for p in pats:
            self.upsert_pattern(p)

    def get_pattern(self, pid: str) -> Pat | None:
        with self.lock:
            r = self.conn.execute("SELECT data FROM patterns WHERE id=?", (pid,)).fetchone()
        return Pat.from_dict(json.loads(r["data"])) if r else None

    def update_fields(self, pid: str, **fields) -> None:
        """Bildirim bayrakları / mesaj kimlikleri gibi alanları günceller."""
        with self.lock:
            r = self.conn.execute("SELECT data FROM patterns WHERE id=?", (pid,)).fetchone()
            if not r:
                return
            d = json.loads(r["data"])
            d.update(fields)
            self.conn.execute("UPDATE patterns SET data=?, src=? WHERE id=?", (json.dumps(d, ensure_ascii=False), d.get("src", "bt"), pid))
            self.conn.commit()

    def load_tracked(self, symbol: str, tf: str, min_c_ts: int) -> list[Pat]:
        """Aktif (pending/active) olanlar + tekrar tespiti önlemek için yakın zamanda bulunmuş olanlar."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT data FROM patterns WHERE symbol=? AND tf=? AND (status IN ('pending','active') OR c_ts>=?)",
                (symbol, tf, min_c_ts)).fetchall()
        return [Pat.from_dict(json.loads(r["data"])) for r in rows]

    def active_patterns(self, announced_only: bool = True) -> list[Pat]:
        with self.lock:
            rows = self.conn.execute("SELECT data FROM patterns WHERE status IN ('pending','active') AND live=1").fetchall()
        out = [Pat.from_dict(json.loads(r["data"])) for r in rows]
        if announced_only:
            out = [p for p in out if p.ann_armed or p.ann_zone]
        return out

    # ───────── tarama durumu ─────────
    def get_scan_state(self, symbol: str, tf: str) -> dict | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM scan_state WHERE symbol=? AND tf=?", (symbol, tf)).fetchone()
        return dict(r) if r else None

    def set_scan_state(self, symbol: str, tf: str, last_ts: int | None, source: str = "", err: str = "") -> None:
        with self.lock:
            old = self.conn.execute("SELECT * FROM scan_state WHERE symbol=? AND tf=?", (symbol, tf)).fetchone()
            if err:
                cnt = (old["err_count"] if old else 0) + 1
                self.conn.execute(
                    "INSERT INTO scan_state(symbol,tf,last_ts,last_scan,source,err_count,last_err) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(symbol,tf) DO UPDATE SET err_count=?, last_err=?, last_scan=?",
                    (symbol, tf, old["last_ts"] if old else None, time.time(), source, cnt, err, cnt, err, time.time()))
            else:
                self.conn.execute(
                    "INSERT INTO scan_state(symbol,tf,last_ts,last_scan,source,err_count,last_err) VALUES(?,?,?,?,?,0,'') "
                    "ON CONFLICT(symbol,tf) DO UPDATE SET last_ts=?, last_scan=?, source=?, err_count=0, last_err=''",
                    (symbol, tf, last_ts, time.time(), source, last_ts, time.time(), source))
            self.conn.commit()

    def all_scan_states(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM scan_state").fetchall()]

    # ───────── istatistik ─────────
    def stat_rows(self, only_live: bool | None = None) -> list[sqlite3.Row]:
        q = "SELECT symbol,tf,src,dir,rule,rule_name,status,live,entered,thit,result,cancel_reason,created_ts FROM patterns WHERE live=1"
        if only_live is True:
            q += " AND src='live'"
        elif only_live is False:
            q += " AND src='bt'"
        with self.lock:
            return self.conn.execute(q).fetchall()

    def rule_stats(self, succ: int) -> dict[int, tuple[int, int]]:
        """{kural_no: (başarılı, başarısız)} — sonuçlanmış girişler (canlı + geçmiş)."""
        out: dict[int, list[int]] = {}
        with self.lock:
            rows = self.conn.execute("SELECT rule,thit,status FROM patterns WHERE entered=1 AND status IN ('done','stopped')").fetchall()
        for r in rows:
            w = out.setdefault(r["rule"], [0, 0])
            if r["thit"] >= succ:
                w[0] += 1
            else:
                w[1] += 1
        return {k: (v[0], v[1]) for k, v in out.items()}
