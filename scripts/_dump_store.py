import json

d = json.load(open('/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/world_v2109.json'))
for k in d:
    v = d[k]
    t = type(v).__name__
    n = len(v) if hasattr(v, '__len__') else '-'
    print(f"=== {k} ({t}, len={n}) ===")
    if isinstance(v, dict):
        ks = list(v.keys())[:8]
        print("   ключи:", ks)
        if ks:
            print("   пример:", json.dumps(v[ks[0]], ensure_ascii=False)[:300])
    elif isinstance(v, list):
        print("   первые:", json.dumps(v[:2], ensure_ascii=False)[:300])
    print()
