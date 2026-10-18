import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from hbot.config import merged_settings
from hbot.demo import synthetic_bars
from hbot.engine import Engine, EngineSettings, build_rules


def run(pat, d, stage, **over):
    S = merged_settings(None); S.update(over)
    es = EngineSettings.from_dict(S); es.min_score = 40
    B = synthetic_bars(pat, d, stage)
    r = Engine(es, build_rules(S.get("rules"), S["patterns"])).run(B, None, None, [], 0, {}, "BTCUSDT", "4h", "live")
    return r


def test_lifecycle_and_mirror():
    for d in (1, -1):                                            # bullish ve bearish aynı sonucu vermeli
        assert [e.type for e in run("Gartley", d, "armed").events] == ["armed"]
        assert [e.type for e in run("Gartley", d, "zone").events][:3] == ["armed", "zone", "entry"]
        assert "target" in [e.type for e in run("Gartley", d, "target").events]
        ev = run("Bat", d, "cancel").events
        assert [e.type for e in ev] == ["armed", "cancel"] and ev[-1].pat.cancel_reason in ("c_exceeded", "escape")


def test_manual_ranges_are_respected():
    # Gartley AB/XA aralığını imkansız bir yere taşı -> formasyon bulunmamalı
    r = run("Gartley", 1, "armed", rules={"Gartley": {"ab": [0.10, 0.12]}}, patterns={"Gartley": True, "Bat": False, "Alt Bat": False, "Butterfly": False, "Crab": False, "Deep Crab": False, "Shark": False, "Cypher": False})
    assert not [p for p in r.pats if p.rule == "Gartley"]
    r = run("Gartley", 1, "armed", direction="bear")
    assert not r.pats                                            # yön filtresi


def test_cancel_rules_toggle():
    r = run("Bat", 1, "cancel", cancel_c=False, cancel_escape=False, cancel_timeout=False)
    assert "cancel" not in [e.type for e in r.events]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("OK", name)
