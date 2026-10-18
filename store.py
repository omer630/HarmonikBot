"""SQLite: ayarlar, formasyonlar (durumlarıyla), tarama kayıtları ve istatistik."""
from __future__ import annotations

import copy
import json
import math
import sqlite3
import threading
import time
from dataclasses import fields
from typing import Optional

from .config import default_settings
from .engine import (BIG, PAT_FIELDS, Pat, S_CANCEL, S_DONE, S_OPEN, S_STALE, S_STOP, S_WAIT)

_TYPES = {f.name: str(f.type) for f in fields(Pat)}


def _sqltype(t: str) -> str:
    return "REAL" if t == "float" else "INTEGER" if t == "int" else "TEXT"


class Store:
    def __init__(self, path: str):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._settings: Optional[dict] = None
        self._prob_cache: dict = {}
        with self.lock:
            cols = ", ".join(f"{n} {_sqltype(_TYPES[n])}" for n in PAT_FIELDS if n != "id")
            self.db.execute(f"CREATE TABLE IF NOT EXISTS patterns (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols})")
            self.db.execute("CREATE INDEX IF NOT EXISTS ix_pat ON patterns(symbol, tf, state)")
            self.db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS scan (k TEXT PRIMARY KEY, last_ts INTEGER)")
            # yeni sürümde eklenen sütunlar için basit göç
            have = {r["name"] for r in self.db.execute("PRAGMA table_info(patterns)")}
            for n in PAT_FIELDS:
                if n != "id" and n not in have:
                    self.db.execute(f"ALTER TABLE patterns ADD COLUMN {n} {_sqltype(_TYPES[n])}")
            self.db.commit()
            self.purge()

    # ───────── ayarlar ─────────
    def get_settings(self) -> dict:
        with self.lock:
            if self._settings is None:
                base = default_settings()
                row = self.db.execute("SELECT v FROM kv WHERE k='settings'").fetchone()
                if row:
                    saved = json.loads(row["v"])
                    for k, v in saved.items():
                        if k in ("symbols", "patterns", "min_score") and isinstance(v, dict):
                            if k == "symbols":
                                base[k] = v  # kullanıcı listesi aynen korunur
                            else:
                                base[k].update(v)
                        else:
                            base[k] = v
                self._settings = base
            return copy.deepcopy(self._settings)

    def save_settings(self, S: dict) -> None:
        with self.lock:
            self._settings = copy.deepcopy(S)
            self.db.execute("INSERT OR REPLACE INTO kv(k, v) VALUES('settings', ?)", (json.dumps(S),))
            self.db.commit()

    def get_kv(self, k: str, default=None):
        with self.lock:
            row = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
            return json.loads(row["v"]) if row else default

    def set_kv(self, k: str, v) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO kv(k, v) VALUES(?, ?)", (k, json.dumps(v)))
            self.db.commit()

    # ───────── tarama kaydı ─────────
    def get_scan(self, sym: str, tf: str) -> int:
        with self.lock:
            row = self.db.execute("SELECT last_ts FROM scan WHERE k=?", (f"{sym}|{tf}",)).fetchone()
            return int(row["last_ts"]) if row else 0

    def set_scan(self, sym: str, tf: str, ts: int) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO scan(k, last_ts) VALUES(?, ?)", (f"{sym}|{tf}", int(ts)))
            self.db.commit()

    # ───────── formasyonlar ─────────
    @staticmethod
    def _from_row(row: sqlite3.Row) -> Pat:
        kw = {}
        for n in PAT_FIELDS:
            v = row[n]
            t = _TYPES[n]
            if t == "float":
                kw[n] = float("nan") if v is None else float(v)
            elif t == "int":
                kw[n] = int(v or 0)
            else:
                kw[n] = "" if v is None else str(v)
        return Pat(**kw)

    def insert(self, p: Pat) -> int:
        with self.lock:
            names = [n for n in PAT_FIELDS if n != "id"]
            p.created_ts = p.created_ts or int(time.time())
            cur = self.db.execute(
                f"INSERT INTO patterns({', '.join(names)}) VALUES({', '.join('?' * len(names))})",
                [self._val(p, n) for n in names])
            self.db.commit()
            p.id = int(cur.lastrowid)
            return p.id

    @staticmethod
    def _val(p: Pat, n: str):
        v = getattr(p, n)
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    def update(self, p: Pat) -> None:
        with self.lock:
            names = [n for n in PAT_FIELDS if n != "id"]
            self.db.execute(f"UPDATE patterns SET {', '.join(n + '=?' for n in names)} WHERE id=?",
                            [self._val(p, n) for n in names] + [p.id])
            self.db.commit()
            self._prob_cache.clear()

    def active(self, sym: str, tf: str) -> list[Pat]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM patterns WHERE symbol=? AND tf=? AND state IN (?, ?)",
                                   (sym, tf, S_WAIT, S_OPEN)).fetchall()
            return [self._from_row(r) for r in rows]

    def active_all(self, only_notified: bool = True) -> list[Pat]:
        with self.lock:
            q = "SELECT * FROM patterns WHERE state IN (?, ?)"
            if only_notified:
                q += " AND (notified_live=1 OR reach_ts>0)"
            rows = self.db.execute(q + " ORDER BY created_ts DESC", (S_WAIT, S_OPEN)).fetchall()
            return [self._from_row(r) for r in rows]

    def find_dup(self, sym: str, tf: str, direction: int, x_ts: int, c_ts: int, tol_sec: int) -> bool:
        with self.lock:
            row = self.db.execute(
                "SELECT 1 FROM patterns WHERE symbol=? AND tf=? AND dir=? AND ABS(x_ts-?)<=? AND ABS(c_ts-?)<=? LIMIT 1",
                (sym, tf, direction, x_ts, tol_sec, c_ts, tol_sec)).fetchone()
            return row is not None

    def purge(self, days: int = 90) -> None:
        cutoff = int(time.time()) - days * 86400
        self.db.execute("DELETE FROM patterns WHERE state=? AND created_ts<?", (S_STALE, cutoff))
        self.db.execute("DELETE FROM patterns WHERE state IN (?, ?, ?) AND created_ts<? AND notified_live=0 AND reach_ts=0",
                        (S_CANCEL, S_DONE, S_STOP, cutoff))
        self.db.commit()

    # ───────── istatistik ─────────
    def _signal_rows(self, since_ts: int) -> list[Pat]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM patterns WHERE state!=? AND (notified_live=1 OR reach_ts>0) AND created_ts>=?",
                (S_STALE, since_ts)).fetchall()
            return [self._from_row(r) for r in rows]

    @staticmethod
    def _tally(rows: list[Pat], success_tp: int) -> dict:
        d = dict(signal=len(rows), entered=0, win=0, loss=0, cancel=0, open=0)
        for p in rows:
            if p.reach_ts > 0:
                d["entered"] += 1
                if p.state in (S_DONE, S_STOP):
                    if p.t_hit >= success_tp:
                        d["win"] += 1
                    else:
                        d["loss"] += 1
                else:
                    d["open"] += 1
            elif p.state == S_CANCEL:
                d["cancel"] += 1
            else:
                d["open"] += 1
        n = d["win"] + d["loss"]
        d["rate"] = 100.0 * (d["win"] + 1.0) / (n + 2.0) if n else None  # Laplace
        d["raw_rate"] = 100.0 * d["win"] / n if n else None
        return d

    def stats(self, since_ts: int, success_tp: int) -> dict:
        rows = self._signal_rows(since_ts)
        out = {"all": self._tally(rows, success_tp), "by_pattern": {}, "by_tf": {}, "by_market": {}, "by_symbol": {}}
        for key, attr in (("by_pattern", "tp"), ("by_tf", "tf"), ("by_market", "market"), ("by_symbol", "symbol")):
            groups: dict = {}
            for p in rows:
                groups.setdefault(getattr(p, attr), []).append(p)
            out[key] = {g: self._tally(v, success_tp) for g, v in groups.items()}
        return out

    def pattern_prob(self, tp: str, success_tp: int, min_samples: int = 8) -> Optional[float]:
        key = (tp, success_tp)
        hit = self._prob_cache.get(key)
        if hit and time.time() - hit[0] < 120:
            return hit[1]
        with self.lock:
            rows = self.db.execute(
                "SELECT t_hit FROM patterns WHERE tp=? AND reach_ts>0 AND state IN (?, ?) AND state!=?",
                (tp, S_DONE, S_STOP, S_STALE)).fetchall()
        n = len(rows)
        val = None
        if n >= min_samples:
            w = sum(1 for r in rows if int(r["t_hit"] or 0) >= success_tp)
            val = 100.0 * (w + 1.0) / (n + 2.0)
        self._prob_cache[key] = (time.time(), val)
        return val

    def pattern_prob_info(self, tp: str, success_tp: int) -> tuple[Optional[float], int]:
        with self.lock:
            rows = self.db.execute(
                "SELECT t_hit FROM patterns WHERE tp=? AND reach_ts>0 AND state IN (?, ?)", (tp, S_DONE, S_STOP)).fetchall()
        n = len(rows)
        if n == 0:
            return None, 0
        w = sum(1 for r in rows if int(r["t_hit"] or 0) >= success_tp)
        return 100.0 * (w + 1.0) / (n + 2.0), n
