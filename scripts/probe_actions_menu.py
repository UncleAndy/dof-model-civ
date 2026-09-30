"""Структура меню действий: отдаёт ли мир список переходов по актёрам (основа измеренного DoF)."""
import json, sys, os

def probe(path, depth=2):
    print(f"\n===== {os.path.basename(path)} =====")
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        print("  не читается:", e)
        return
    print("  тип:", type(data).__name__, "len:", len(data) if hasattr(data, "__len__") else "")
    if isinstance(data, list):
        print("  elem0:", json.dumps(data[0], ensure_ascii=False)[:1200])
        if len(data) > 1:
            print("  elem1:", json.dumps(data[1], ensure_ascii=False)[:600])
    elif isinstance(data, dict):
        for k, v in list(data.items())[:10]:
            print(f"  [{k}] {type(v).__name__}: {json.dumps(v, ensure_ascii=False)[:500] if not isinstance(v, str) else v[:300]}")

for p in sys.argv[1:] or ["tests/fixtures/real_available_actions.json", "tests/fixtures/real_actions.json"]:
    probe(p)