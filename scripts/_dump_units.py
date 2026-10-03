import json

d = json.load(open('/home/hermes/projects/AI/DOF-MODEL-CIV/knowledge/world_v2109.json'))
ents = d['entities']
kinds = {}
for e in ents:
    kinds.setdefault(e['kind'], []).append(e)
for k, v in kinds.items():
    print(f"{k}: {len(v)}")
print()
for k in ('unit', 'city', 'unit_type'):
    for e in kinds.get(k, [])[:4]:
        print(k, '->', json.dumps(e, ensure_ascii=False)[:400])
    print()
