import json

path = '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_v2109.jsonl'
for i, line in enumerate(open(path)):
    if i > 3:
        break
    d = json.loads(line)
    print(f"--- запись {i}, ход {d.get('ход')} ---")
    for k in d:
        v = d[k]
        s = json.dumps(v, ensure_ascii=False)
        print(f"  {k}: {s[:160]}")
    print()
