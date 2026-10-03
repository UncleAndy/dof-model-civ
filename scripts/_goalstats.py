import json, collections, sys
path = sys.argv[1] if len(sys.argv) > 1 else '/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/traces_def.jsonl'
c = collections.Counter()
keys = collections.Counter()
n = 0
for l in open(path):
    try:
        d = json.loads(l)
    except Exception:
        continue
    n += 1
    for k in d:
        keys[k] += 1
    v = d.get('выбрано') or {}
    g = v.get('goal')
    if g:
        c[g] += 1
print("записей:", n)
print("ключи:", dict(keys))
print("goals:", dict(c.most_common(20)))
