"""Структура строки среза состояния: что в ней лежит."""
import json, sys

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/h300q_base.json.state.jsonl"
with open(path) as f:
    line = f.readline()
r = json.loads(line)
print("top keys:", list(r.keys()))
for k, v in r.items():
    n = len(v) if hasattr(v, "__len__") else v
    print(f"  {k}: {type(v).__name__} {str(n)[:120]}")

# если есть вложенное наблюдение — показать его ключи
for key in ("observation", "obs", "sections", "state"):
    v = r.get(key)
    if isinstance(v, dict):
        print(f"\n{key} keys:", list(v.keys()))
        for k2, v2 in v.items():
            print(f"   {k2}: {type(v2).__name__} {str(len(v2) if hasattr(v2,'__len__') else v2)[:80]}")
        break
    if isinstance(v, list):
        print(f"\n{key}: list len={len(v)}; elem0 type={type(v[0]).__name__}")
        if isinstance(v[0], dict):
            print("   elem0 keys:", list(v[0].keys()))
        break