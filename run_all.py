"""Tüm testleri çalıştırır (pytest gerekmez):  python tests/run_all.py"""
import importlib, os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
fails = 0
for mod in ("test_engine", "test_data", "test_scanner_flow", "test_bot", "test_once"):
    m = importlib.import_module(f"tests.{mod}")
    for name in sorted(n for n in dir(m) if n.startswith("test_")):
        try:
            getattr(m, name)(); print(f"✔ {mod}.{name}")
        except Exception:
            fails += 1; print(f"✘ {mod}.{name}"); traceback.print_exc()
print("\nTÜM TESTLER GEÇTİ" if not fails else f"\n{fails} TEST BAŞARISIZ")
sys.exit(1 if fails else 0)
