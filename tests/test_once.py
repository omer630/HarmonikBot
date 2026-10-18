import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests.test_bot import make, msg
from hbot.db import DB


def test_poll_until_persists_offset_and_handles_commands():
    app, tg, db, sc = make()
    n = {"c": 0}
    def gu(offset, timeout=25):
        n["c"] += 1
        return [{**msg("/durum", 111), "update_id": 41}] if n["c"] == 1 else []
    tg.get_updates = gu
    app.poll_until(time.time() + 1.5)
    assert db.get_meta("tg_offset") == 42
    assert any(m[0] == "msg" and "Bot" in m[2] or "tarama" in m[2].lower() or "durum" in m[2].lower() for m in tg.sent)
    assert db.get_meta("cmds_set") == 1


def test_seed_schedule_and_close():
    app, tg, db, sc = make()
    S = db.load_settings(); sym, tf = sc.keys(S)[0]
    db.set_scan_state(sym, tf, int(time.time()) - 100, "x")
    sc.seed_schedule()
    assert sc.sched[(sym, tf)]["next"] > time.time()
    sc.finish(1)
    db.close()
    assert DB(db.path).get_meta("cmds_set", 0) in (0, 1)
